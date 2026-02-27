"""Ingest trigger endpoint — run the seed pipeline via API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from src.api.dependencies import get_storage
from src.storage.manager import StorageManager

router = APIRouter(tags=["ingest"])


def _load_interventions() -> dict[str, list[str]]:
    """Load interventions.json, return {name: [aliases]}."""
    path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "interventions.json"
    with open(path) as f:
        data = json.load(f)
    return {item["name"]: item.get("aliases", []) for item in data["interventions"]}


@router.post("/ingest/{name}")
async def trigger_ingest(
    name: str,
    sources: str | None = Query(None, description="Comma-separated sources (e.g. pubmed,europe_pmc). Default: all"),
    max_results: int = Query(50, ge=1, le=500, description="Max results per source"),
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Trigger the ingest pipeline for an intervention.

    Runs all (or selected) ingest agents and stores results.
    This is a synchronous endpoint — it blocks until ingest completes.
    """
    from src.ingest.clinical_trials import ClinicalTrialsAgent
    from src.ingest.drugage import DrugAgeAgent
    from src.ingest.europe_pmc import EuropePMCAgent
    from src.ingest.fda import FDAAgent
    from src.ingest.google_trends import fetch_trends
    from src.ingest.nih_reporter import NIHReporterAgent
    from src.ingest.patents import PatentAgent
    from src.ingest.pubmed import PubMedAgent
    from src.ingest.query_expander import expand_query
    from src.ingest.semantic_scholar import SemanticScholarAgent
    from src.ingest.social import SocialAgent
    from src.ingest.tavily import TavilyAgent

    ALL_SOURCES = {
        "pubmed": PubMedAgent,
        "clinicaltrials": ClinicalTrialsAgent,
        "europe_pmc": EuropePMCAgent,
        "semantic_scholar": SemanticScholarAgent,
        "drugage": DrugAgeAgent,
        "nih_reporter": NIHReporterAgent,
        "patents": PatentAgent,
        "fda": FDAAgent,
        "tavily": TavilyAgent,
        "social": SocialAgent,
    }
    EXTRA_SOURCES = {"trends"}

    # Look up aliases
    interventions = _load_interventions()
    intervention = name.lower()
    aliases = interventions.get(intervention, [])
    if not aliases:
        logger.warning(f"'{intervention}' not in interventions.json, proceeding with no aliases")

    # Parse sources
    valid = set(ALL_SOURCES.keys()) | EXTRA_SOURCES
    if sources:
        requested = [s.strip() for s in sources.split(",")]
        invalid = [s for s in requested if s not in valid]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown sources: {invalid}. Valid: {sorted(valid)}",
            )
    else:
        requested = list(ALL_SOURCES.keys()) + list(EXTRA_SOURCES)

    doc_sources = [s for s in requested if s in ALL_SOURCES]
    run_trends = "trends" in requested

    # Expand query terms
    logger.info(f"API ingest: expanding search terms for '{intervention}'...")
    query_expansion = await expand_query(intervention, aliases)

    # Run document-producing agents
    total_added = 0
    source_results: dict[str, dict] = {}
    for source_name in doc_sources:
        agent_cls = ALL_SOURCES[source_name]
        agent = agent_cls(storage=storage)
        try:
            docs = await agent.ingest(
                intervention=intervention,
                aliases=aliases,
                query_expansion=query_expansion,
                max_results=max_results,
            )
            added = 0
            if docs:
                added = await storage.save_documents(intervention, docs, aliases)
            source_results[source_name] = {"status": "ok", "new_documents": added}
            total_added += added
        except Exception as e:
            logger.error(f"Ingest {source_name} failed: {e}")
            source_results[source_name] = {"status": "error", "error": str(e)}

    # Google Trends
    trends_result = None
    if run_trends:
        try:
            trends = await fetch_trends(intervention, aliases)
            if trends:
                trends_result = {
                    "status": "ok",
                    "data_points": len(trends.data_points),
                    "peak_interest": trends.peak_interest,
                }
            else:
                trends_result = {"status": "ok", "data_points": 0}
        except Exception as e:
            trends_result = {"status": "error", "error": str(e)}

    total_stored = await storage.count_documents(intervention)
    return {
        "intervention": intervention,
        "new_documents_added": total_added,
        "total_documents_stored": total_stored,
        "sources": source_results,
        "trends": trends_result,
    }
