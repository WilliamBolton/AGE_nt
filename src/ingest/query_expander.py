"""LLM-powered query expansion for intervention search terms.

Given an intervention name (e.g., 'rapamycin'), generates comprehensive search
terms including synonyms, analogs, mechanism terms, MeSH terms, and
source-specific optimized queries. Results are cached per intervention.
"""

from __future__ import annotations

import json
from pathlib import Path

import openai
from loguru import logger
from pydantic import BaseModel, Field

from src.config import LLMProvider, settings

EXPANSION_SYSTEM_PROMPT = """You are a biomedical research expert specialising in aging and longevity interventions.

Given an intervention name and any known aliases, generate a comprehensive set of search terms for finding ALL relevant research across multiple databases.

Return ONLY valid JSON matching this exact schema:
{
  "primary_name": "the canonical name",
  "synonyms": ["generic names", "brand names", "chemical names", "abbreviations"],
  "analogs": ["related compounds in the same class, if any"],
  "mechanism_terms": ["pathway/target names", "mechanism of action terms"],
  "mesh_terms": ["relevant MeSH vocabulary terms for PubMed"],
  "queries": {
    "pubmed": "optimized PubMed query using MeSH and boolean operators",
    "clinical_trials": "terms for ClinicalTrials.gov intervention search",
    "general": "natural language search query for web/news search",
    "preprint": "search terms for bioRxiv/medRxiv"
  }
}

Important:
- Include ALL known names, even obscure ones
- For the pubmed query, use MeSH terms with [MeSH Terms] tags where appropriate
- For clinical_trials, focus on intervention names (no aging terms, those go in condition field)
- For general, write a natural language query a journalist might search
- Be comprehensive — missing a synonym means missing relevant papers"""

EXPANSION_USER_TEMPLATE = """Intervention: {intervention}
Known aliases: {aliases}

Generate comprehensive search terms for finding aging/longevity research on this intervention."""


class QueryExpansion(BaseModel):
    """Expanded search terms for an intervention."""

    primary_name: str
    synonyms: list[str] = Field(default_factory=list)
    analogs: list[str] = Field(default_factory=list)
    mechanism_terms: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    queries: dict[str, str] = Field(default_factory=dict)


def _cache_path(intervention: str) -> Path:
    return settings.query_cache_dir / f"{intervention.lower()}.json"


def load_cached_expansion(intervention: str) -> QueryExpansion | None:
    """Load cached query expansion from disk, if available."""
    path = _cache_path(intervention)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return QueryExpansion.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to load cached expansion for {intervention}: {e}")
    return None


def _save_cache(intervention: str, expansion: QueryExpansion) -> None:
    settings.query_cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(intervention)
    path.write_text(expansion.model_dump_json(indent=2))
    logger.debug(f"Cached query expansion to {path}")


async def expand_query(
    intervention: str,
    aliases: list[str] | None = None,
) -> QueryExpansion:
    """Generate expanded search terms for an intervention using LLM.

    Checks cache first. Falls back to basic expansion if LLM is unavailable.
    """
    # Check cache
    cached = load_cached_expansion(intervention)
    if cached is not None:
        logger.info(f"Using cached query expansion for '{intervention}'")
        return cached

    aliases = aliases or []

    # Try LLM expansion
    try:
        expansion = await _llm_expand(intervention, aliases)
        _save_cache(intervention, expansion)
        logger.info(
            f"Generated query expansion for '{intervention}': "
            f"{len(expansion.synonyms)} synonyms, {len(expansion.analogs)} analogs"
        )
        return expansion
    except Exception as e:
        logger.warning(f"LLM query expansion failed for '{intervention}': {e}")
        logger.info("Falling back to basic expansion from aliases")
        return _basic_expansion(intervention, aliases)


async def _llm_expand(intervention: str, aliases: list[str]) -> QueryExpansion:
    """Call LLM to generate expanded search terms."""
    user_msg = EXPANSION_USER_TEMPLATE.format(
        intervention=intervention,
        aliases=", ".join(aliases) if aliases else "none known",
    )

    if settings.llm_provider == LLMProvider.OPENAI:
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": EXPANSION_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        raw = resp.choices[0].message.content or "{}"
    else:
        # Gemini path
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        resp = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"{EXPANSION_SYSTEM_PROMPT}\n\n{user_msg}",
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        raw = resp.text or "{}"

    data = json.loads(raw)
    return QueryExpansion.model_validate(data)


def _basic_expansion(intervention: str, aliases: list[str]) -> QueryExpansion:
    """Fallback: create basic expansion from intervention name + known aliases."""
    all_terms = [intervention] + aliases
    pubmed_terms = " OR ".join(f'"{t}"' for t in all_terms)
    pubmed_query = f"({pubmed_terms}) AND (aging[MeSH Terms] OR longevity OR senescence)"

    return QueryExpansion(
        primary_name=intervention,
        synonyms=aliases,
        analogs=[],
        mechanism_terms=[],
        mesh_terms=[],
        queries={
            "pubmed": pubmed_query,
            "clinical_trials": " OR ".join(all_terms),
            "general": f"{intervention} aging longevity research evidence",
            "preprint": f"{intervention} aging longevity",
        },
    )
