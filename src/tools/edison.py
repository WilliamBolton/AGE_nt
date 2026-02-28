"""Edison Scientific tool — deep literature synthesis via PaperQA3.

Standalone tool that accepts research questions from an orchestrator agent,
submits them to Edison's API, and saves results to data/edison/ as both
structured JSON and human-readable Markdown.

This is NOT part of the ingest pipeline. It sits alongside other tools
(e.g. gap analysis) that reasoning agents or orchestrators can invoke.

Usage:
    from src.tools.edison import ask_edison, run_edison_research

    # Single query
    result = await ask_edison("What is the evidence for rapamycin extending lifespan?")

    # Batch with file output
    path = await run_edison_research("rapamycin", [
        "What do the NIA ITP studies show about rapamycin?",
        "What are the side effects of low-dose rapamycin?",
    ])
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EDISON_DATA_DIR = PROJECT_ROOT / "data" / "edison"

# Module-level flag: set when Edison returns auth/credit errors.
# Once set, all subsequent calls skip the API immediately.
_EDISON_EXHAUSTED = False


def edison_is_exhausted() -> bool:
    """Check whether Edison credits have been exhausted this session."""
    return _EDISON_EXHAUSTED


def _check_edison_exhaustion(error: Exception) -> bool:
    """Return True if this error indicates Edison auth/credit issues."""
    msg = str(error).lower()
    return any(term in msg for term in (
        "429", "rate limit", "insufficient", "credit", "quota",
        "unauthorized", "forbidden", "403", "too many requests",
    ))


def _patch_coredis() -> None:
    """Fix coredis 2.3.x compatibility: alias StrictRedis → Redis.

    edison-client's dependency chain (ldp → lmi → coredis) expects
    coredis.Redis which was renamed to StrictRedis in newer versions.
    """
    try:
        import coredis

        if not hasattr(coredis, "Redis") and hasattr(coredis, "StrictRedis"):
            coredis.Redis = coredis.StrictRedis  # type: ignore[attr-defined]
    except ImportError:
        pass


def _import_edison():
    """Lazy-import edison_client with coredis compatibility patch."""
    _patch_coredis()
    from edison_client import EdisonClient, JobNames
    return EdisonClient, JobNames


def _get_job_name(job_type: str):
    """Map string job_type to JobNames enum value."""
    _, JobNames = _import_edison()

    job_map = {
        "literature": JobNames.LITERATURE,
        "literature_high": JobNames.LITERATURE_HIGH,
        "precedent": JobNames.PRECEDENT,
        "analysis": JobNames.ANALYSIS,
        "molecules": JobNames.MOLECULES,
    }
    return job_map.get(job_type, JobNames.LITERATURE)


async def ask_edison(
    query: str,
    job_type: str = "literature",
) -> dict | None:
    """Ask Edison a single research question.

    Args:
        query: The research question to submit.
        job_type: Edison job type — "literature", "literature_high",
                  "precedent", "analysis", or "molecules".

    Returns:
        Dict with keys {query, answer, formatted_answer, successful, task_id}
        on success, or None on failure.
    """
    global _EDISON_EXHAUSTED

    if _EDISON_EXHAUSTED:
        logger.info("Edison credits exhausted — skipping")
        return None

    if not settings.edison_api_key:
        logger.debug("EDISON_API_KEY not set — skipping")
        return None

    try:
        EdisonClient, _ = _import_edison()
    except ImportError:
        logger.warning("edison-client package not installed. Run: pip install edison-client")
        return None

    try:
        client = EdisonClient(api_key=settings.edison_api_key)
        task_data = {"name": _get_job_name(job_type), "query": query}
        response = await client.arun_tasks_until_done(task_data)

        # arun_tasks_until_done may return a list or single response
        resp = response[0] if isinstance(response, list) else response

        successful = getattr(resp, "has_successful_answer", False)
        return {
            "query": query,
            "answer": getattr(resp, "answer", "") or "",
            "formatted_answer": getattr(resp, "formatted_answer", "") or "",
            "successful": successful,
            "task_id": str(getattr(resp, "task_id", "") or ""),
            "job_type": job_type,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        if _check_edison_exhaustion(e):
            _EDISON_EXHAUSTED = True
            logger.warning(
                f"Edison credits/auth exhausted: {e}. "
                "Skipping Edison for all remaining queries."
            )
        else:
            logger.error(f"Edison query failed: {e}")
        return None


async def run_edison_batch(
    queries: list[str],
    job_type: str = "literature",
) -> list[dict]:
    """Submit multiple queries to Edison in parallel.

    Args:
        queries: List of research questions.
        job_type: Edison job type for all queries.

    Returns:
        List of result dicts (only successful responses included).
    """
    global _EDISON_EXHAUSTED

    if _EDISON_EXHAUSTED:
        logger.info("Edison credits exhausted — skipping batch")
        return []

    if not settings.edison_api_key:
        logger.debug("EDISON_API_KEY not set — skipping Edison batch")
        return []

    if not queries:
        return []

    try:
        EdisonClient, _ = _import_edison()
    except ImportError:
        logger.warning("edison-client package not installed. Run: pip install edison-client")
        return []

    job_name = _get_job_name(job_type)

    try:
        client = EdisonClient(api_key=settings.edison_api_key)
        task_data = [{"name": job_name, "query": q} for q in queries]

        logger.info(f"Edison: submitting {len(queries)} queries (this may take 1-2 minutes)...")
        responses = await client.arun_tasks_until_done(task_data)

        # Normalise to list
        if not isinstance(responses, list):
            responses = [responses]

    except Exception as e:
        if _check_edison_exhaustion(e):
            _EDISON_EXHAUSTED = True
            logger.warning(
                f"Edison credits/auth exhausted: {e}. "
                "Skipping Edison for all remaining queries."
            )
        else:
            logger.error(f"Edison batch failed: {e}")
        return []

    results: list[dict] = []
    for i, resp in enumerate(responses):
        query_text = queries[i] if i < len(queries) else "unknown"
        successful = getattr(resp, "has_successful_answer", False)

        if not successful:
            logger.warning(f"Edison query unsuccessful: {query_text[:80]}...")
            continue

        answer = getattr(resp, "answer", "") or ""
        if not answer:
            continue

        results.append({
            "query": query_text,
            "answer": answer,
            "formatted_answer": getattr(resp, "formatted_answer", "") or "",
            "successful": True,
            "task_id": str(getattr(resp, "task_id", "") or ""),
            "job_type": job_type,
            "timestamp": datetime.now().isoformat(),
        })

    logger.info(f"Edison: {len(results)}/{len(queries)} queries returned successful answers")
    return results


async def run_edison_research(
    intervention: str,
    queries: list[str],
    job_type: str = "literature",
) -> Path | None:
    """Run Edison research for an intervention and save results.

    High-level function for orchestrator agents. Submits queries in batch,
    saves results to data/edison/{intervention}.json and .md, and returns
    the path to the JSON file.

    Appends to existing results if the file already exists (deduplicates
    by query text).

    Args:
        intervention: Canonical intervention name.
        queries: Research questions to submit.
        job_type: Edison job type for all queries.

    Returns:
        Path to the JSON output file, or None if all queries failed.
    """
    results = await run_edison_batch(queries, job_type)
    if not results:
        logger.warning(f"Edison: no successful results for '{intervention}'")
        return None

    # Merge with existing results (deduplicate by query text)
    EDISON_DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = EDISON_DATA_DIR / f"{intervention.lower()}.json"
    md_path = EDISON_DATA_DIR / f"{intervention.lower()}.md"

    existing_results: list[dict] = []
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text())
            existing_results = data.get("results", [])
        except Exception:
            pass

    # Deduplicate: keep existing results, add new ones with unseen queries
    existing_queries = {r["query"] for r in existing_results}
    new_results = [r for r in results if r["query"] not in existing_queries]
    all_results = existing_results + new_results

    # Write JSON
    output = {
        "intervention": intervention.lower(),
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "results": all_results,
    }
    json_path.write_text(json.dumps(output, indent=2))
    logger.info(f"Edison: saved {len(all_results)} results to {json_path}")

    # Write Markdown
    _write_markdown(intervention, all_results, md_path)
    logger.info(f"Edison: saved Markdown report to {md_path}")

    return json_path


def _write_markdown(
    intervention: str,
    results: list[dict],
    path: Path,
) -> None:
    """Write Edison results as a formatted Markdown document."""
    lines: list[str] = [
        f"# Edison Research: {intervention.title()}",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d')}*",
        "",
    ]

    for r in results:
        lines.append(f"## {r['query']}")
        lines.append("")
        # Use formatted_answer (with citations) if available, else plain answer
        answer = r.get("formatted_answer") or r.get("answer", "")
        lines.append(answer)
        lines.append("")
        task_id = r.get("task_id", "")
        job = r.get("job_type", "literature")
        meta_parts = [f"Edison Scientific ({job})"]
        if task_id:
            meta_parts.append(f"Task: {task_id}")
        lines.append(f"*Source: {' | '.join(meta_parts)}*")
        lines.append("")
        lines.append("---")
        lines.append("")

    path.write_text("\n".join(lines))
