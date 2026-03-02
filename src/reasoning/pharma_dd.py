"""Pharma due diligence orchestrator.

Discovers available tools dynamically, loads pharma + biotech profiles,
computes strategic fit, and uses Gemini for narrative synthesis.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from google import genai
from loguru import logger
from pydantic import BaseModel, Field

from src.api.routes.tools import discover_tools
from src.config import PROJECT_ROOT
from src.storage.manager import StorageManager

# ── Output models ────────────────────────────────────────────────────────────


class BiotechTarget(BaseModel):
    rank: int = 0
    company: str = ""
    stage: str = ""
    strategy: str = ""  # "opportunistic" | "competitive" | "evaluate" | "monitor"
    strategy_detail: str = ""  # Gemini-generated narrative
    relevance_score: float = 0.0
    evidence_summary: dict = Field(default_factory=dict)
    acquisition_estimate: dict = Field(default_factory=dict)
    matched_interventions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    competitive_advantages: list[str] = Field(default_factory=list)


class AcquisitionLandscape(BaseModel):
    pharma: str = ""
    analysis_date: str = ""
    executive_summary: str = ""  # Gemini-generated
    landscape_stats: dict = Field(default_factory=dict)
    top_targets: list[BiotechTarget] = Field(default_factory=list)
    category_landscape: dict[str, dict] = Field(default_factory=dict)
    hallmark_heatmap: dict[str, dict] = Field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _load_profile(directory: Path, company_slug: str) -> dict | None:
    """Load a profile JSON by slug."""
    path = directory / f"{company_slug}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _load_all_profiles(directory: Path) -> list[dict]:
    """Load all profiles from a directory."""
    if not directory.exists():
        return []
    profiles = []
    for path in sorted(directory.glob("*.json")):
        try:
            profiles.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load {path}: {e}")
    return profiles


def _load_interventions() -> dict:
    """Load interventions.json as {name: {category, aliases}}."""
    path = PROJECT_ROOT / "data" / "interventions.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {
        item["name"]: {
            "category": item.get("category", ""),
            "aliases": item.get("aliases", []),
        }
        for item in data.get("interventions", [])
    }


def map_biotech_to_interventions(
    biotech: dict,
    interventions: dict,
) -> list[str]:
    """Map a biotech's pipeline to our intervention names.

    Matches via:
    - intervention_link on pipeline compounds
    - category_links matching intervention categories
    - compound name matching intervention name or alias
    """
    matched = set()

    # Direct links from pipeline compounds
    for compound in biotech.get("pipeline", []):
        link = compound.get("intervention_link")
        if link and link in interventions:
            matched.add(link)

    # Category matching
    biotech_categories = set(biotech.get("category_links", []))
    for name, info in interventions.items():
        if info["category"] in biotech_categories:
            matched.add(name)

    # Name matching (compound names vs intervention names/aliases)
    for compound in biotech.get("pipeline", []):
        compound_name = compound.get("compound", "").lower()
        for name, info in interventions.items():
            all_names = [name.lower()] + [a.lower() for a in info["aliases"]]
            if compound_name in all_names:
                matched.add(name)

    return sorted(matched)


def compute_strategic_relevance(
    pharma: dict,
    biotech: dict,
) -> float:
    """Compute strategic fit score (0-100) based on hallmark overlap."""
    pharma_hallmarks = set(pharma.get("pipeline_hallmarks_overlap", []))
    biotech_hallmarks = set(biotech.get("hallmarks_targeted", []))

    if not pharma_hallmarks and not biotech_hallmarks:
        return 25.0  # baseline when no hallmark data

    if not pharma_hallmarks or not biotech_hallmarks:
        return 30.0

    overlap = pharma_hallmarks & biotech_hallmarks
    union = pharma_hallmarks | biotech_hallmarks
    jaccard = len(overlap) / len(union) if union else 0

    # Scale to 0-100 with bonuses
    score = jaccard * 60

    # Bonus for many overlapping hallmarks
    score += min(len(overlap) * 5, 20)

    # Bonus for biotech stage
    stage_bonus = {"approved": 15, "clinical": 10, "preclinical": 5}
    score += stage_bonus.get(biotech.get("stage", ""), 0)

    return min(score, 100.0)


def estimate_acquisition_value(biotech: dict, evidence_score: float) -> dict:
    """Estimate acquisition value based on stage, funding, and evidence."""
    funding = biotech.get("total_funding_usd") or 0
    stage = biotech.get("stage", "preclinical")

    # Stage multipliers
    multipliers = {
        "preclinical": (3, 8),
        "clinical": (5, 15),
        "approved": (8, 25),
    }
    low_mult, high_mult = multipliers.get(stage, (3, 8))

    # Evidence bonus
    evidence_mult = 1.0 + (evidence_score / 100) * 0.5

    # Use existing estimate if available
    existing = biotech.get("acquisition_estimate")
    if existing and existing.get("low_usd"):
        return existing

    if funding > 0:
        low = int(funding * low_mult * evidence_mult)
        high = int(funding * high_mult * evidence_mult)
    else:
        # Default ranges by stage
        defaults = {
            "preclinical": (50_000_000, 300_000_000),
            "clinical": (200_000_000, 2_000_000_000),
            "approved": (1_000_000_000, 10_000_000_000),
        }
        low, high = defaults.get(stage, (50_000_000, 300_000_000))

    return {
        "low_usd": low,
        "high_usd": high,
        "methodology": f"Based on {stage} stage, ${funding:,} funding, {evidence_score:.0f}/100 evidence score",
        "comparable_deals": [],
    }


def _determine_strategy(relevance: float, stage: str) -> str:
    """Determine acquisition strategy based on relevance and stage."""
    if relevance >= 70:
        return "competitive" if stage in ("clinical", "approved") else "opportunistic"
    if relevance >= 40:
        return "evaluate"
    return "monitor"


# ── Gemini narrative ─────────────────────────────────────────────────────────

NARRATIVE_PROMPT = """You are a pharma M&A strategist specialising in longevity and aging therapeutics.

Given the structured analysis below, reason deeply about:
- **Hallmark overlap**: Which aging hallmarks does {pharma_name}'s existing pipeline target? Which biotechs address the SAME hallmarks (synergy) vs COMPLEMENTARY hallmarks (portfolio expansion)? Why does this matter for M&A strategy?
- **Evidence quality**: For each biotech's matched interventions, what does the evidence confidence score tell us? High-evidence interventions (50+) de-risk acquisitions. Low-evidence ones (<30) are speculative bets.
- **Strategic fit**: Does this biotech fill a gap in {pharma_name}'s portfolio, or is it a competitive play to block rivals? Consider stage (preclinical vs clinical), mechanism novelty, and IP landscape.
- **Category concentration**: Which intervention categories are crowded (many biotechs, high competition) vs underserved (few players, opportunity)?

Write:
1. An executive summary (2-3 paragraphs) synthesising the strategic landscape. Be specific — name companies, cite hallmark overlaps, and reference evidence scores. Identify the top 2-3 themes (e.g. "senolytic consolidation play", "epigenetic portfolio gap").
2. For each top target, a 2-3 sentence strategy_detail that explains: (a) why this target is relevant to {pharma_name} specifically (hallmark overlap), (b) the evidence strength for their lead programs, and (c) recommended approach (acquire, partner, monitor).

Pharma profile:
{pharma_json}

Top biotech targets (ranked by strategic relevance score, hallmark overlap + stage bonus):
{targets_json}

Category landscape (intervention category → number of biotechs + company list):
{categories_json}

Hallmark heatmap (aging hallmark → number of biotechs targeting it):
{hallmarks_json}

Return JSON:
{{
  "executive_summary": "...",
  "target_details": {{
    "company_name": "strategy detail text",
    ...
  }}
}}"""


async def _generate_narrative(
    pharma: dict,
    targets: list[dict],
    categories: dict,
    hallmarks: dict,
    gemini_key: str,
) -> dict:
    """Use Gemini to reason over overlaps and generate narrative for the DD report."""
    try:
        client = genai.Client(api_key=gemini_key)
        prompt = NARRATIVE_PROMPT.format(
            pharma_name=pharma.get("company", ""),
            pharma_json=json.dumps(pharma, indent=2, default=str)[:3000],
            targets_json=json.dumps(targets[:10], indent=2, default=str)[:4000],
            categories_json=json.dumps(categories, indent=2, default=str)[:1500],
            hallmarks_json=json.dumps(hallmarks, indent=2, default=str)[:1500],
        )
        resp = await client.aio.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return json.loads(resp.text or "{}")
    except Exception as e:
        logger.error(f"Gemini narrative failed: {e}")
        return {
            "executive_summary": f"Analysis of longevity acquisition targets for {pharma.get('company', '')}. "
            f"Found {len(targets)} potential targets across the longevity biotech landscape.",
            "target_details": {},
        }


# ── Main orchestrator ────────────────────────────────────────────────────────

async def analyse_acquisition_landscape(
    pharma_name: str,
    storage: StorageManager,
    gemini_key: str = "",
    top_n: int = 10,
) -> AcquisitionLandscape:
    """Run full pharma DD analysis.

    1. Load pharma + biotech profiles
    2. Map biotechs to interventions
    3. Run available tools for matched interventions
    4. Compute strategic relevance + acquisition value
    5. Rank targets
    6. Use Gemini for narrative
    """
    pharma_dir = PROJECT_ROOT / "data" / "pharma_profiles"
    biotech_dir = PROJECT_ROOT / "data" / "biotech_profiles"

    # 1. Load pharma profile
    pharma = _load_profile(pharma_dir, _slug(pharma_name))
    if not pharma:
        raise ValueError(f"Pharma profile not found: {pharma_name}")

    # 2. Load all biotech profiles
    biotechs = _load_all_profiles(biotech_dir)
    if not biotechs:
        raise ValueError("No biotech profiles found")

    # 3. Load intervention mappings
    interventions = _load_interventions()

    # 4. Discover available tools
    tools = discover_tools()
    logger.info(f"DD analysis: {len(tools)} tools available: {list(tools.keys())}")

    # 5. Analyse each biotech
    targets: list[BiotechTarget] = []
    category_counts: dict[str, dict] = {}
    hallmark_counts: dict[str, dict] = {}

    for biotech in biotechs:
        company = biotech.get("company", "unknown")

        # Map to interventions
        matched = map_biotech_to_interventions(biotech, interventions)

        # Run available tools for matched interventions
        evidence_data: dict = {}
        total_evidence_score = 0.0
        tool_count = 0

        for intervention in matched[:5]:  # limit to top 5 for performance
            for tool_name, (fn, _, _) in tools.items():
                try:
                    result = fn(intervention, storage)
                    result_dict = result.model_dump() if hasattr(result, "model_dump") else result
                    evidence_data[f"{tool_name}_{intervention}"] = result_dict

                    # Extract composite score if available
                    if "composite_score" in result_dict:
                        total_evidence_score += result_dict["composite_score"]
                        tool_count += 1
                except Exception as e:
                    logger.debug(f"Tool {tool_name} failed for {intervention}: {e}")

        avg_evidence_score = total_evidence_score / tool_count if tool_count > 0 else 30.0

        # Compute strategic relevance
        relevance = compute_strategic_relevance(pharma, biotech)

        # Estimate acquisition value
        acq_estimate = estimate_acquisition_value(biotech, avg_evidence_score)

        # Determine strategy
        strategy = _determine_strategy(relevance, biotech.get("stage", ""))

        target = BiotechTarget(
            company=company,
            stage=biotech.get("stage", "unknown"),
            strategy=strategy,
            relevance_score=relevance,
            evidence_summary={
                "matched_interventions": matched,
                "evidence_score": avg_evidence_score,
                "tools_run": list(evidence_data.keys()),
            },
            acquisition_estimate=acq_estimate,
            matched_interventions=matched,
            risks=biotech.get("risks", []),
            competitive_advantages=biotech.get("competitive_advantages", []),
        )
        targets.append(target)

        # Track categories and hallmarks
        for cat in biotech.get("category_links", []):
            if cat not in category_counts:
                category_counts[cat] = {"count": 0, "companies": []}
            category_counts[cat]["count"] += 1
            category_counts[cat]["companies"].append(company)

        for hallmark in biotech.get("hallmarks_targeted", []):
            if hallmark not in hallmark_counts:
                hallmark_counts[hallmark] = {"count": 0, "companies": []}
            hallmark_counts[hallmark]["count"] += 1
            hallmark_counts[hallmark]["companies"].append(company)

    # 6. Rank by relevance
    targets.sort(key=lambda t: t.relevance_score, reverse=True)
    for i, t in enumerate(targets):
        t.rank = i + 1

    # 7. Generate narrative with Gemini (reasons over hallmark overlaps + evidence)
    narrative = {"executive_summary": "", "target_details": {}}
    if gemini_key:
        narrative = await _generate_narrative(
            pharma,
            [t.model_dump() for t in targets[:top_n]],
            category_counts,
            hallmark_counts,
            gemini_key,
        )

    # Apply narrative to targets
    target_details = narrative.get("target_details", {})
    for target in targets[:top_n]:
        detail = target_details.get(target.company, "")
        if detail:
            target.strategy_detail = detail

    return AcquisitionLandscape(
        pharma=pharma.get("company", pharma_name),
        analysis_date=datetime.now().isoformat(),
        executive_summary=narrative.get("executive_summary", ""),
        landscape_stats={
            "total_biotechs_analysed": len(biotechs),
            "total_matched_interventions": len({
                i for t in targets for i in t.matched_interventions
            }),
            "tools_available": list(tools.keys()),
            "categories_covered": len(category_counts),
            "hallmarks_covered": len(hallmark_counts),
        },
        top_targets=targets[:top_n],
        category_landscape=category_counts,
        hallmark_heatmap=hallmark_counts,
    )
