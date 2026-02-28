"""Batch seed all interventions from data/interventions.json.

Designed to run overnight — handles rate limits, failures, and API credit
budgets gracefully.

Usage:
  uv run python scripts/seed_all.py                                    # all interventions, all sources
  uv run python scripts/seed_all.py --skip-tavily                      # conserve Tavily credits
  uv run python scripts/seed_all.py --skip-edison                      # skip slow Edison queries
  uv run python scripts/seed_all.py --sources pubmed,clinicaltrials,drugage  # specific sources only
  uv run python scripts/seed_all.py --delay 20                         # 20s between interventions
  uv run python scripts/seed_all.py --start-from metformin             # resume from a specific intervention
  uv run python scripts/seed_all.py --dry-run                          # list interventions, don't seed
  uv run python scripts/seed_all.py --category senolytics              # only seed one category
  uv run python scripts/seed_all.py --max-results 100                  # max results per source
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
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
from src.ingest.tavily import TavilyAgent, tavily_is_exhausted
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

# Sources that hit rate-limited APIs and shouldn't run concurrently with each other.
# PubMed (3 req/s), Semantic Scholar (100 req/min), NIH Reporter — these share
# no rate limits with each other so they CAN run in parallel, but each internally
# respects its own rate limit via sleeps in the agent code.
#
# The only real conflict is storage writes (JSON append isn't thread-safe),
# so we gather ingest calls concurrently and save results sequentially.

# Retry config
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5  # seconds — exponential: 5, 10, 20

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INTERVENTIONS_PATH = PROJECT_ROOT / "data" / "interventions.json"
SUMMARY_PATH = PROJECT_ROOT / "data" / "seed_summary.json"


def _is_transient_error(e: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    msg = str(e).lower()
    return any(term in msg for term in (
        "429", "rate limit", "timeout", "timed out", "connection reset",
        "connection refused", "temporary", "service unavailable", "503",
        "502", "500", "server error", "too many requests",
    ))


async def _ingest_with_retry(
    agent: BaseIngestAgent,
    intervention: str,
    aliases: list[str],
    query_expansion,
    max_results: int,
    source_name: str,
) -> tuple[str, list]:
    """Run an agent's ingest with retry + exponential backoff.

    Returns (source_name, docs) — never raises.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            docs = await agent.ingest(
                intervention=intervention,
                aliases=aliases,
                query_expansion=query_expansion,
                max_results=max_results,
            )
            return source_name, docs or []
        except Exception as e:
            if attempt < MAX_RETRIES and _is_transient_error(e):
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    f"  {source_name} attempt {attempt}/{MAX_RETRIES} failed "
                    f"(transient: {e}), retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                if attempt > 1:
                    logger.error(f"  {source_name} failed after {attempt} attempts: {e}")
                else:
                    logger.error(f"  {source_name} failed: {e}")
                return source_name, e  # type: ignore[return-value]
    return source_name, []  # shouldn't reach here


def load_intervention_registry() -> list[dict]:
    """Load the full interventions.json registry."""
    with open(INTERVENTIONS_PATH) as f:
        data = json.load(f)
    return data["interventions"]


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}min"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h{mins:02d}m"


async def seed_one(
    intervention_entry: dict,
    storage: StorageManager,
    max_results: int,
    source_names: list[str],
    run_trends: bool,
) -> dict:
    """Seed a single intervention. Returns a result dict for the summary.

    Never raises — all errors are caught and recorded.
    """
    name = intervention_entry["name"]
    aliases = intervention_entry.get("aliases", [])
    category = intervention_entry.get("category")
    subcategory = intervention_entry.get("subcategory")

    result: dict = {
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "documents": 0,
        "sources": {},
        "duration_seconds": 0,
        "errors": [],
    }
    t0 = time.monotonic()

    # Expand query terms via LLM
    try:
        from src.ingest.query_expander import expand_query
        query_expansion = await expand_query(name, aliases)
    except Exception as e:
        logger.error(f"  Query expansion failed: {e}")
        result["errors"].append(f"query_expansion: {e}")
        query_expansion = None

    total_added = 0
    source_counts: dict[str, int | str] = {}

    # Build concurrent ingest tasks for all requested sources
    ingest_tasks = []
    skipped_sources: dict[str, str] = {}

    for source_name in source_names:
        if source_name == "tavily" and tavily_is_exhausted():
            skipped_sources[source_name] = "EXHAUSTED"
            continue

        agent_cls = ALL_SOURCES.get(source_name)
        if not agent_cls:
            continue

        agent = agent_cls(storage=storage)
        ingest_tasks.append(
            _ingest_with_retry(
                agent=agent,
                intervention=name,
                aliases=aliases,
                query_expansion=query_expansion,
                max_results=max_results,
                source_name=source_name,
            )
        )

    # Also include trends if requested
    if run_trends:
        async def _fetch_trends_wrapper() -> tuple[str, list | Exception]:
            try:
                trends = await fetch_trends(name, aliases)
                if trends:
                    return "trends", trends  # type: ignore[return-value]
                return "trends", []
            except Exception as e:
                return "trends", e  # type: ignore[return-value]

        ingest_tasks.append(_fetch_trends_wrapper())

    # Run all ingest agents concurrently
    ingest_results = await asyncio.gather(*ingest_tasks)

    # Apply skipped sources
    source_counts.update(skipped_sources)

    # Process results sequentially (storage writes need serialization)
    for source_name, docs_or_error in ingest_results:
        if isinstance(docs_or_error, Exception):
            source_counts[source_name] = "ERROR"
            result["errors"].append(f"{source_name}: {docs_or_error}")
            continue

        # Google Trends is special — not a document list
        if source_name == "trends":
            if docs_or_error and hasattr(docs_or_error, "data_points"):
                source_counts["trends"] = len(docs_or_error.data_points)
            else:
                source_counts["trends"] = 0
            continue

        # Normal document source — save to storage
        docs = docs_or_error
        if docs:
            try:
                added = await storage.save_documents(
                    name, docs, aliases,
                    category=category, subcategory=subcategory,
                )
                source_counts[source_name] = added
                total_added += added
            except Exception as e:
                logger.error(f"  Failed to save {source_name} docs for '{name}': {e}")
                source_counts[source_name] = "SAVE_ERROR"
                result["errors"].append(f"{source_name}_save: {e}")
        else:
            source_counts[source_name] = 0

    elapsed = time.monotonic() - t0
    result["documents"] = total_added
    result["sources"] = source_counts
    result["duration_seconds"] = round(elapsed, 1)

    return result


def build_progress_line(
    idx: int,
    total: int,
    name: str,
    result: dict,
    elapsed_total: float,
) -> str:
    """Build the per-intervention progress log line."""
    source_parts = []
    for src_name, count in result["sources"].items():
        if isinstance(count, int):
            source_parts.append(f"{src_name}:{count}")
        else:
            source_parts.append(f"{src_name}:{count}")
    sources_str = " ".join(source_parts)

    dur = format_duration(result["duration_seconds"])
    docs = result["documents"]

    # ETA
    if idx > 0:
        avg_per = elapsed_total / idx
        remaining = avg_per * (total - idx)
        eta_str = format_duration(remaining)
    else:
        eta_str = "?"

    return (
        f"[{idx}/{total}] {name} ... "
        f"{sources_str} "
        f"({docs} docs, {dur}) "
        f"| {format_duration(elapsed_total)} elapsed, ~{eta_str} remaining"
    )


def print_summary_table(results: list[dict]) -> None:
    """Print a summary table of all interventions."""
    # Collect all source names that appear
    all_src_names: list[str] = []
    for r in results:
        for s in r["sources"]:
            if s not in all_src_names:
                all_src_names.append(s)

    # Header
    header = f"{'Intervention':<30} {'Total':>6}"
    for s in all_src_names:
        header += f" {s[:8]:>8}"
    header += f" {'Errors':>6}"
    logger.info("=" * len(header))
    logger.info(header)
    logger.info("-" * len(header))

    total_docs = 0
    total_errors = 0
    for r in results:
        line = f"{r['name']:<30} {r['documents']:>6}"
        for s in all_src_names:
            val = r["sources"].get(s, "-")
            if isinstance(val, int):
                line += f" {val:>8}"
            else:
                line += f" {val:>8}"
        err_count = len(r["errors"])
        line += f" {err_count:>6}"
        logger.info(line)
        total_docs += r["documents"]
        total_errors += err_count

    logger.info("-" * len(header))
    logger.info(f"{'TOTAL':<30} {total_docs:>6}" + " " * (9 * len(all_src_names)) + f" {total_errors:>6}")
    logger.info("=" * len(header))


async def run(args: argparse.Namespace) -> None:
    """Main batch seeding loop."""
    # Load registry
    registry = load_intervention_registry()

    # Filter by category
    if args.category:
        registry = [e for e in registry if e.get("category") == args.category]
        if not registry:
            logger.error(f"No interventions found for category '{args.category}'")
            return

    # Start-from: skip interventions before the named one
    if args.start_from:
        start_name = args.start_from.lower()
        names = [e["name"].lower() for e in registry]
        if start_name not in names:
            logger.error(f"'{args.start_from}' not found in interventions registry")
            return
        start_idx = names.index(start_name)
        registry = registry[start_idx:]
        logger.info(f"Resuming from '{args.start_from}' ({len(registry)} remaining)")

    total = len(registry)

    # Dry run
    if args.dry_run:
        logger.info(f"DRY RUN — {total} interventions would be seeded:\n")
        for i, entry in enumerate(registry, 1):
            cat = entry.get("category", "?")
            sub = entry.get("subcategory", "?")
            aliases_str = ", ".join(entry.get("aliases", [])[:3])
            if len(entry.get("aliases", [])) > 3:
                aliases_str += ", ..."
            logger.info(f"  [{i:>3}/{total}] {entry['name']:<30} {cat}/{sub}  ({aliases_str})")
        logger.info(f"\nTotal: {total} interventions")
        return

    # Determine sources to run
    if args.sources:
        requested_sources = args.sources.split(",")
    else:
        requested_sources = list(ALL_SOURCES.keys()) + list(EXTRA_SOURCES)

    # Apply skip flags
    if args.skip_tavily:
        requested_sources = [s for s in requested_sources if s != "tavily"]
    if args.skip_edison:
        # Edison is not an ingest source but flag it for downstream
        pass

    doc_sources = [s for s in requested_sources if s in ALL_SOURCES]
    run_trends = "trends" in requested_sources

    # Validate sources
    valid = set(ALL_SOURCES.keys()) | EXTRA_SOURCES
    for s in requested_sources:
        if s not in valid:
            logger.warning(f"Unknown source: '{s}' (valid: {', '.join(sorted(valid))})")

    # Initialize storage
    storage = StorageManager()
    await storage.initialize()

    started_at = datetime.now(timezone.utc)
    logger.info(
        f"Batch seed starting: {total} interventions, "
        f"sources={','.join(doc_sources)}, "
        f"delay={args.delay}s, max_results={args.max_results}"
    )

    results: list[dict] = []
    t_start = time.monotonic()

    for idx, entry in enumerate(registry):
        name = entry["name"]
        logger.info(f"\n[{idx + 1}/{total}] Seeding '{name}'...")

        result = await seed_one(
            intervention_entry=entry,
            storage=storage,
            max_results=args.max_results,
            source_names=doc_sources,
            run_trends=run_trends,
        )
        results.append(result)

        elapsed_total = time.monotonic() - t_start
        progress = build_progress_line(idx + 1, total, name, result, elapsed_total)
        logger.info(progress)

        if result["errors"]:
            for err in result["errors"]:
                logger.warning(f"  ERROR: {err}")

        # Delay between interventions (skip after the last one)
        if idx < total - 1 and args.delay > 0:
            logger.info(f"  Waiting {args.delay}s before next intervention...")
            await asyncio.sleep(args.delay)

    # Final summary
    completed_at = datetime.now(timezone.utc)
    total_elapsed = time.monotonic() - t_start
    total_docs = sum(r["documents"] for r in results)
    failed = sum(1 for r in results if r["errors"])

    logger.info(f"\n{'=' * 60}")
    logger.info("BATCH SEED COMPLETE")
    logger.info(f"{'=' * 60}")
    logger.info(f"Duration: {format_duration(total_elapsed)}")
    logger.info(f"Interventions: {total} ({total - failed} clean, {failed} with errors)")
    logger.info(f"Total documents added: {total_docs}")

    print_summary_table(results)

    # Save summary JSON
    summary = {
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round(total_elapsed, 1),
        "total_interventions": total,
        "successful": total - failed,
        "failed": failed,
        "total_documents": total_docs,
        "sources_used": doc_sources + (["trends"] if run_trends else []),
        "config": {
            "max_results": args.max_results,
            "delay": args.delay,
            "skip_tavily": args.skip_tavily,
            "skip_edison": args.skip_edison,
            "category_filter": args.category,
            "start_from": args.start_from,
        },
        "interventions": results,
    }

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str))
    logger.info(f"\nSummary saved to {SUMMARY_PATH}")

    await storage.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch seed all interventions from data/interventions.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--max-results", type=int, default=50,
        help="Max results per source per intervention (default: 50)",
    )
    parser.add_argument(
        "--sources", type=str, default=None,
        help=f"Comma-separated sources (default: all). Options: {','.join(sorted(ALL_SOURCES.keys()) + sorted(EXTRA_SOURCES))}",
    )
    parser.add_argument(
        "--delay", type=int, default=20,
        help="Seconds to wait between interventions (default: 20)",
    )
    parser.add_argument(
        "--start-from", type=str, default=None,
        help="Skip all interventions before this one (for resuming after a crash)",
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Only seed interventions matching this category",
    )
    parser.add_argument(
        "--skip-tavily", action="store_true",
        help="Skip Tavily web search (conserve API credits)",
    )
    parser.add_argument(
        "--skip-edison", action="store_true",
        help="Skip Edison queries (slow and expensive)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List interventions that would be seeded, don't actually seed",
    )

    args = parser.parse_args()

    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    # Also log to file for overnight runs
    log_path = PROJECT_ROOT / "data" / "seed_all.log"
    logger.add(str(log_path), level="DEBUG", rotation="50 MB")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
