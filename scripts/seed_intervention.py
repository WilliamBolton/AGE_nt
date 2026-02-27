"""CLI script to seed data for a single intervention.

Usage:
    python scripts/seed_intervention.py rapamycin
    python scripts/seed_intervention.py metformin --max-results 100
    python scripts/seed_intervention.py rapamycin --sources pubmed,europe_pmc,semantic_scholar,drugage,nih_reporter,trends
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure src is importable when running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.config import settings
from src.ingest.base import BaseIngestAgent
from src.ingest.clinical_trials import ClinicalTrialsAgent
from src.ingest.drugage import DrugAgeAgent
from src.ingest.europe_pmc import EuropePMCAgent
from src.ingest.fda import FDAAgent
from src.ingest.google_trends import fetch_trends
from src.ingest.nih_reporter import NIHReporterAgent
from src.ingest.patents import PatentAgent
from src.ingest.pubmed import PubMedAgent
from src.ingest.semantic_scholar import SemanticScholarAgent
from src.ingest.social import SocialAgent
from src.ingest.tavily import TavilyAgent
from src.stats.summary import generate_summary
from src.storage.manager import StorageManager

# Document-producing agents (implement BaseIngestAgent)
ALL_SOURCES: dict[str, type[BaseIngestAgent]] = {
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

# Non-document sources (handled separately)
EXTRA_SOURCES = {"trends"}


def load_interventions() -> dict[str, list[str]]:
    """Load interventions.json, return {name: [aliases]}."""
    path = Path(__file__).resolve().parent.parent / "data" / "interventions.json"
    with open(path) as f:
        data = json.load(f)
    return {item["name"]: item.get("aliases", []) for item in data["interventions"]}


async def seed(
    intervention: str,
    aliases: list[str],
    max_results: int,
    sources: list[str] | None = None,
) -> None:
    """Run ingest agents for a single intervention."""
    from src.ingest.query_expander import expand_query

    # 1. Initialize storage
    storage = StorageManager()
    await storage.initialize()

    # 2. Expand query terms via LLM
    logger.info(f"Expanding search terms for '{intervention}'...")
    query_expansion = await expand_query(intervention, aliases)
    logger.info(
        f"Search terms: {query_expansion.primary_name} + "
        f"{len(query_expansion.synonyms)} synonyms, "
        f"{len(query_expansion.analogs)} analogs"
    )

    # 3. Determine which sources to run
    requested = sources or (list(ALL_SOURCES.keys()) + list(EXTRA_SOURCES))
    doc_sources = [s for s in requested if s in ALL_SOURCES]
    run_trends = "trends" in requested

    # 4. Run document-producing agents
    total = 0
    for source_name in doc_sources:
        agent_cls = ALL_SOURCES[source_name]
        agent = agent_cls(storage=storage)
        logger.info(f"--- {agent.source_name} ---")
        try:
            docs = await agent.ingest(
                intervention=intervention,
                aliases=aliases,
                query_expansion=query_expansion,
                max_results=max_results,
            )
            if docs:
                added = await storage.save_documents(intervention, docs, aliases)
                logger.info(f"  {agent.source_name}: {added} new documents stored")
                total += added
            else:
                logger.info(f"  {agent.source_name}: no new documents")
        except Exception as e:
            logger.error(f"  {agent.source_name} failed: {e}")

    # 5. Run Google Trends (non-document, saves to data/trends/)
    if run_trends:
        logger.info("--- Google Trends ---")
        try:
            trends = await fetch_trends(intervention, aliases)
            if trends:
                logger.info(
                    f"  Trends: {len(trends.data_points)} data points, "
                    f"peak={trends.peak_interest} ({trends.peak_date})"
                )
            else:
                logger.info("  Trends: no data available")
        except Exception as e:
            logger.error(f"  Google Trends failed: {e}")

    # 6. Generate summary stats
    logger.info("--- Summary Stats ---")
    summary = generate_summary(intervention)
    if summary:
        logger.info(
            f"  Summary: {summary['total_documents']} docs across "
            f"{len(summary['by_source_type'])} sources"
        )

    # 7. Final report
    total_stored = await storage.count_documents(intervention)
    logger.info(f"\nSeeding complete for '{intervention}':")
    logger.info(f"  New documents added this run: {total}")
    logger.info(f"  Total documents stored: {total_stored}")

    await storage.close()


def main() -> None:
    all_source_names = sorted(ALL_SOURCES.keys()) + sorted(EXTRA_SOURCES)
    parser = argparse.ArgumentParser(description="Seed data for a longevity intervention")
    parser.add_argument("intervention", help="Intervention name (e.g., rapamycin)")
    parser.add_argument("--max-results", type=int, default=50, help="Max results per source (default: 50)")
    parser.add_argument(
        "--sources",
        type=str,
        default=None,
        help=f"Comma-separated sources to use (default: all). Options: {','.join(all_source_names)}",
    )
    args = parser.parse_args()

    # Look up aliases
    interventions = load_interventions()
    name = args.intervention.lower()
    if name in interventions:
        aliases = interventions[name]
    else:
        logger.warning(f"'{name}' not in interventions.json, proceeding with no aliases")
        aliases = []

    # Parse sources
    sources = args.sources.split(",") if args.sources else None

    # Validate sources
    if sources:
        valid = set(ALL_SOURCES.keys()) | EXTRA_SOURCES
        for s in sources:
            if s not in valid:
                logger.warning(f"Unknown source: {s} (valid: {','.join(sorted(valid))})")

    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)

    asyncio.run(seed(name, aliases, args.max_results, sources))


if __name__ == "__main__":
    main()
