"""Ingest pipeline tool — check if data exists and trigger sourcing if needed.

Wraps the existing ingest pipeline so it can be called from any chat
interface (MCP, CLI agent, web app). Shows the user what data exists
and optionally runs the pipeline for missing interventions.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from src.config import PROJECT_ROOT
from src.stats.summary import generate_summary
from src.storage.manager import StorageManager


def _load_registry() -> dict:
    """Load the interventions registry."""
    path = PROJECT_ROOT / "data" / "interventions.json"
    if path.exists():
        data = json.loads(path.read_text())
        return {item["name"]: item for item in data.get("interventions", [])}
    return {}


def check_intervention_data(intervention: str, storage: StorageManager) -> dict:
    """Check what data exists for an intervention.

    Returns a status dict showing whether data is collected, how many
    documents exist, which sources have data, and whether ingest is needed.

    This is a fast, synchronous check — no API calls or LLM needed.
    """
    name = intervention.lower().strip()
    registry = _load_registry()

    # Check if in registry
    in_registry = name in registry
    registry_entry = registry.get(name, {})

    # Check existing documents
    docs = storage.get_documents(name)
    doc_count = len(docs)

    # Source breakdown
    source_counts: dict[str, int] = {}
    for d in docs:
        st = d.source_type.value if hasattr(d.source_type, "value") else str(d.source_type)
        source_counts[st] = source_counts.get(st, 0) + 1

    # Check summary stats
    summary_path = PROJECT_ROOT / "data" / "summary" / f"{name}.json"
    has_summary = summary_path.exists()

    # Check classification
    class_path = PROJECT_ROOT / "data" / "classifications" / f"{name}.json"
    has_classification = class_path.exists()

    has_data = doc_count > 0

    return {
        "intervention": name,
        "has_data": has_data,
        "in_registry": in_registry,
        "document_count": doc_count,
        "source_breakdown": source_counts,
        "has_summary_stats": has_summary,
        "has_classification": has_classification,
        "category": registry_entry.get("category"),
        "aliases": registry_entry.get("aliases", []),
        "message": (
            f"'{name}' has {doc_count} documents from {len(source_counts)} sources. "
            f"{'Summary stats available.' if has_summary else 'No summary stats yet — run ingest to generate.'}"
            if has_data
            else f"No data collected for '{name}' yet. "
            + ("It is in the registry — run ingest to collect data." if in_registry else "It is NOT in the intervention registry.")
        ),
        "action_needed": "none" if has_data and has_summary else "ingest_recommended",
    }


async def run_ingest_pipeline(
    intervention: str,
    storage: StorageManager,
    sources: list[str] | None = None,
    max_results: int = 50,
    force: bool = False,
) -> dict:
    """Run the full ingest pipeline for an intervention.

    This is async and can take 1-3 minutes per intervention depending
    on sources. It fetches from all data sources, saves documents,
    and generates summary statistics.

    Args:
        intervention: Canonical intervention name.
        storage: StorageManager instance.
        sources: Optional list of sources to run. Default: all.
        max_results: Max results per source (default 50).

    Returns:
        Status dict with documents added, source results, and summary.
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

    name = intervention.lower().strip()

    # Skip if data already exists (unless force=True)
    if not force:
        existing = check_intervention_data(name, storage)
        if existing["has_data"] and existing["document_count"] > 0:
            logger.info(
                f"Ingest skipped for '{name}': "
                f"{existing['document_count']} documents already exist"
            )
            return {
                "intervention": name,
                "pipeline": "skipped",
                "reason": "data_already_exists",
                "existing_document_count": existing["document_count"],
                "existing_sources": existing["source_breakdown"],
                "message": (
                    f"Skipped ingest for '{name}' — already has "
                    f"{existing['document_count']} documents from "
                    f"{len(existing['source_breakdown'])} sources."
                ),
            }

    registry = _load_registry()
    aliases = registry.get(name, {}).get("aliases", [])

    # Expand query
    logger.info(f"Ingest tool: expanding queries for '{name}'...")
    query_expansion = await expand_query(name, aliases)

    # Determine sources to run
    if sources:
        doc_sources = [s for s in sources if s in ALL_SOURCES]
        run_trends = "trends" in sources
    else:
        doc_sources = list(ALL_SOURCES.keys())
        run_trends = True

    # Run agents
    total_added = 0
    source_results: dict[str, dict] = {}
    for source_name in doc_sources:
        agent_cls = ALL_SOURCES[source_name]
        agent = agent_cls(storage=storage)
        try:
            docs = await agent.ingest(
                intervention=name,
                aliases=aliases,
                query_expansion=query_expansion,
                max_results=max_results,
            )
            added = 0
            if docs:
                added = await storage.save_documents(name, docs, aliases)
            source_results[source_name] = {"status": "ok", "new_documents": added}
            total_added += added
            logger.info(f"  {source_name}: +{added} documents")
        except Exception as e:
            logger.error(f"  {source_name} failed: {e}")
            source_results[source_name] = {"status": "error", "error": str(e)}

    # Google Trends
    trends_result = None
    if run_trends:
        try:
            trends = await fetch_trends(name, aliases)
            if trends:
                trends_result = {"status": "ok", "data_points": len(trends.data_points)}
            else:
                trends_result = {"status": "ok", "data_points": 0}
        except Exception as e:
            trends_result = {"status": "error", "error": str(e)}

    # Generate summary stats
    summary = None
    try:
        summary = generate_summary(name)
        logger.info(f"Summary stats generated for '{name}'")
    except Exception as e:
        logger.warning(f"Summary generation failed: {e}")

    total_stored = len(storage.get_documents(name))

    return {
        "intervention": name,
        "pipeline": "completed",
        "new_documents_added": total_added,
        "total_documents_stored": total_stored,
        "sources": source_results,
        "trends": trends_result,
        "summary_generated": summary is not None,
        "message": f"Ingested {total_added} new documents for '{name}' from {len(doc_sources)} sources. Total: {total_stored} documents.",
    }
