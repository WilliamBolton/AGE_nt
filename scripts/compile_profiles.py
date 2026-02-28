"""Compile pharma and biotech company profiles using a strong reasoning model.

Uses OpenAI GPT (high reasoning) to generate structured profiles with source
citations. Every factual claim (funding, founding years, pipeline compounds,
acquisition prices) must cite a source URL or reference.

Usage:
    uv run python scripts/compile_profiles.py --type both
    uv run python scripts/compile_profiles.py --type pharma --company "Novartis"
    uv run python scripts/compile_profiles.py --type biotech --company "Altos Labs"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

import openai
from loguru import logger

from src.config import PROJECT_ROOT, settings
from src.schema.pharma import BiotechProfile, PharmaProfile

# ── Hardcoded company lists ──────────────────────────────────────────────────

PHARMA_COMPANIES = [
    "Novartis", "AbbVie", "Johnson & Johnson", "Eli Lilly", "Novo Nordisk",
    "Pfizer", "Roche", "AstraZeneca", "Merck", "Bristol-Myers Squibb",
    "Regeneron", "Amgen", "GSK", "Bayer", "Sanofi",
]

BIOTECH_COMPANIES = [
    "Altos Labs", "Calico", "Retro Bio", "NewLimit", "Unity Biotechnology",
    "Cambrian Bio", "BioAge Labs", "Life Biosciences", "Loyal",
    "Rejuvenate Bio", "Turn Bio", "Shift Bio", "Rubedo Life Sciences",
    "Oisin Biotechnologies", "Senolytic Therapeutics", "Dorian Therapeutics",
    "Fauna Bio", "Cellarity", "Juvena Therapeutics", "Genflow Biosciences",
    "Hevolution Foundation", "SENS Research Foundation",
    "Longevity Biotech Fellowship", "Deciduous Therapeutics",
    "Tornado Therapeutics",
]

# ── Aging hallmarks reference (passed to the LLM) ───────────────────────────

HALLMARKS = [
    "genomic_instability", "telomere_attrition", "epigenetic_alterations",
    "loss_of_proteostasis", "disabled_macroautophagy",
    "deregulated_nutrient_sensing", "mitochondrial_dysfunction",
    "cellular_senescence", "stem_cell_exhaustion",
    "altered_intercellular_communication", "chronic_inflammation", "dysbiosis",
]

# ── Intervention categories (from data/interventions.json) ──────────────────

def _load_intervention_categories() -> list[str]:
    """Load unique categories from interventions.json."""
    path = PROJECT_ROOT / "data" / "interventions.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return sorted({item.get("category", "") for item in data.get("interventions", []) if item.get("category")})


def _load_intervention_names() -> list[str]:
    """Load all intervention names."""
    path = PROJECT_ROOT / "data" / "interventions.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [item["name"] for item in data.get("interventions", [])]


# ── Prompts ──────────────────────────────────────────────────────────────────

PHARMA_SYSTEM_PROMPT = """You are a pharmaceutical industry analyst specialising in longevity and aging research.

Generate a structured profile for the given pharma company, analysing their relevance to the longevity/aging field.

CRITICAL REQUIREMENTS:
1. Every factual claim MUST cite a source (URL or reference). If you cannot cite a source, note "source needed" instead of making up a URL.
2. For funding amounts, market caps, founding years, and acquisition prices — be precise and cite.
3. For pipeline compounds — cite the clinical trial registry, press release, or SEC filing.
4. Rate aging_signal_strength 1-10 based on how actively the company is pursuing aging-related research.
5. Map existing_longevity_assets to our intervention names where possible (intervention_link field).
6. Map pipeline_hallmarks_overlap to the 12 hallmarks of aging.

Return ONLY valid JSON matching the schema below. No markdown, no commentary."""

BIOTECH_SYSTEM_PROMPT = """You are a biotech industry analyst specialising in longevity startups and aging biology.

Generate a structured profile for the given longevity biotech company.

CRITICAL REQUIREMENTS:
1. Every factual claim MUST cite a source (URL or reference). If you cannot cite a source, note "source needed".
2. For funding amounts, founding years — cite Crunchbase, PitchBook, press releases, or SEC filings.
3. For pipeline compounds — cite the company website, clinical trial registry, or publications.
4. Map pipeline compounds to our intervention names where possible (intervention_link field).
5. Map hallmarks_targeted to the 12 hallmarks of aging.
6. Map category_links to our intervention categories.
7. For acquisition_estimate — provide a range with methodology and comparable deals.
8. Be honest about risks — every longevity biotech has them.

Return ONLY valid JSON matching the schema below. No markdown, no commentary."""


def _pharma_user_prompt(company: str, categories: list[str], interventions: list[str]) -> str:
    return f"""Company: {company}

Our intervention categories: {json.dumps(categories)}
Our intervention names (use for intervention_link): {json.dumps(interventions[:20])}... (54 total)
Aging hallmarks: {json.dumps(HALLMARKS)}

Generate a PharmaProfile JSON with these fields:
{{
  "company": str,
  "ticker": str | null,
  "hq": str,
  "market_cap_approx": str | null (e.g. "$150B"),
  "therapeutic_areas": [str],
  "aging_relevance": "high" | "moderate" | "low",
  "aging_relevance_reasoning": str,
  "existing_longevity_assets": [{{
    "compound": str,
    "intervention_link": str | null (from our intervention names),
    "status": str,
    "indication": str,
    "relevance": str,
    "source": str (URL or reference)
  }}],
  "pipeline_hallmarks_overlap": [str] (from hallmarks list),
  "aging_signal_strength": int (1-10),
  "recent_acquisitions": [{{
    "target": str,
    "year": int | null,
    "value_usd": int | null,
    "relevance": str,
    "source": str
  }}],
  "acquisition_pattern": {{
    "preferred_stage": str,
    "avg_deal_size_usd": int | null,
    "focus_areas": [str],
    "recent_trend": str
  }},
  "sources": [str] (all source URLs/references used),
  "needs_review": true
}}"""


def _biotech_user_prompt(company: str, categories: list[str], interventions: list[str]) -> str:
    return f"""Company: {company}

Our intervention categories: {json.dumps(categories)}
Our intervention names (use for intervention_link): {json.dumps(interventions[:20])}... (54 total)
Aging hallmarks: {json.dumps(HALLMARKS)}

Generate a BiotechProfile JSON with these fields:
{{
  "company": str,
  "ticker": str | null,
  "founded": int | null,
  "hq": str | null,
  "stage": "preclinical" | "clinical" | "approved",
  "total_funding_usd": int | null,
  "pipeline": [{{
    "compound": str,
    "intervention_link": str | null (from our intervention names),
    "target": str,
    "mechanism": str,
    "indication": str | null,
    "phase": str,
    "hallmarks": [str] (from hallmarks list),
    "categories": [str] (from our categories),
    "source": str (URL or reference)
  }}],
  "hallmarks_targeted": [str],
  "category_links": [str],
  "key_people": [{{
    "name": str,
    "role": str,
    "background": str
  }}],
  "investors_notable": [str],
  "risks": [str],
  "competitive_advantages": [str],
  "acquisition_estimate": {{
    "low_usd": int | null,
    "high_usd": int | null,
    "methodology": str,
    "comparable_deals": [str]
  }} | null,
  "sources": [str],
  "needs_review": true
}}"""


# ── LLM Call ─────────────────────────────────────────────────────────────────

async def _call_openai(system_prompt: str, user_prompt: str) -> dict:
    """Call OpenAI GPT-5.2 with high reasoning effort via Responses API."""
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.responses.create(
        model=settings.openai_model,
        instructions=system_prompt,
        input=[{"role": "user", "content": user_prompt}],
        reasoning={"effort": "high"},
        text={"format": {"type": "json_object"}},
    )
    raw = resp.output_text or "{}"
    return json.loads(raw)


# ── Profile compilation ─────────────────────────────────────────────────────

def _slug(name: str) -> str:
    """Convert company name to filename slug."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


async def compile_pharma_profile(company: str) -> PharmaProfile:
    """Compile a pharma profile using LLM."""
    categories = _load_intervention_categories()
    interventions = _load_intervention_names()

    logger.info(f"Compiling pharma profile: {company}")
    data = await _call_openai(
        PHARMA_SYSTEM_PROMPT,
        _pharma_user_prompt(company, categories, interventions),
    )
    profile = PharmaProfile.model_validate(data)

    # Save
    out_dir = PROJECT_ROOT / "data" / "pharma_profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(company)}.json"
    out_path.write_text(profile.model_dump_json(indent=2))
    logger.info(f"Saved pharma profile: {out_path}")

    return profile


async def compile_biotech_profile(company: str) -> BiotechProfile:
    """Compile a biotech profile using LLM."""
    categories = _load_intervention_categories()
    interventions = _load_intervention_names()

    logger.info(f"Compiling biotech profile: {company}")
    data = await _call_openai(
        BIOTECH_SYSTEM_PROMPT,
        _biotech_user_prompt(company, categories, interventions),
    )
    profile = BiotechProfile.model_validate(data)

    # Save
    out_dir = PROJECT_ROOT / "data" / "biotech_profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(company)}.json"
    out_path.write_text(profile.model_dump_json(indent=2))
    logger.info(f"Saved biotech profile: {out_path}")

    return profile


# ── CLI ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Compile pharma/biotech company profiles")
    parser.add_argument("--type", choices=["pharma", "biotech", "both"], default="both")
    parser.add_argument("--company", type=str, help="Compile a single company (by name)")
    args = parser.parse_args()

    if args.company:
        # Single company
        if args.type == "pharma" or (args.type == "both" and args.company in PHARMA_COMPANIES):
            await compile_pharma_profile(args.company)
        elif args.type == "biotech" or (args.type == "both" and args.company in BIOTECH_COMPANIES):
            await compile_biotech_profile(args.company)
        else:
            # Try both — the LLM will figure it out
            if args.type in ("pharma", "both"):
                await compile_pharma_profile(args.company)
            if args.type in ("biotech", "both"):
                await compile_biotech_profile(args.company)
        return

    # All companies
    if args.type in ("pharma", "both"):
        logger.info(f"Compiling {len(PHARMA_COMPANIES)} pharma profiles...")
        for company in PHARMA_COMPANIES:
            try:
                await compile_pharma_profile(company)
            except Exception as e:
                logger.error(f"Failed to compile {company}: {e}")

    if args.type in ("biotech", "both"):
        logger.info(f"Compiling {len(BIOTECH_COMPANIES)} biotech profiles...")
        for company in BIOTECH_COMPANIES:
            try:
                await compile_biotech_profile(company)
            except Exception as e:
                logger.error(f"Failed to compile {company}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
