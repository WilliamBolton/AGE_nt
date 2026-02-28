"""LongevityLens MCP Server — exposes intervention data as MCP tools.

Run standalone:
    python -m src.mcp_server.server

Test with MCP Inspector:
    mcp dev src/mcp_server/server.py
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP

from src.stats.summary import generate_summary
from src.storage.manager import StorageManager


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Initialize StorageManager on startup, close on shutdown."""
    storage = StorageManager()
    await storage.initialize()
    logger.info("MCP server: StorageManager initialized")
    try:
        yield {"storage": storage}
    finally:
        await storage.close()
        logger.info("MCP server: StorageManager closed")


mcp = FastMCP(
    "longevity-lens",
    host="0.0.0.0",
    port=8001,
    lifespan=server_lifespan,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_storage(ctx: Context) -> StorageManager:
    """Extract StorageManager from lifespan context."""
    return ctx.request_context.lifespan_context["storage"]


async def _validate_intervention(
    storage: StorageManager, name: str
) -> tuple[str | None, list[str]]:
    """Validate intervention exists.

    Returns (error_json_or_None, interventions_list).
    """
    interventions = await storage.get_interventions()
    if name not in interventions:
        error = json.dumps(
            {"error": f"Intervention '{name}' not found", "available": interventions}
        )
        return error, interventions
    return None, interventions


def _json(obj: object) -> str:
    return json.dumps(obj, indent=2, default=str)


# ── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_interventions(ctx: Context) -> str:
    """List all indexed aging interventions with document counts and source type breakdown.

    Returns a JSON object with each intervention's name, total document count,
    and breakdown by source type (pubmed, clinicaltrials, drugage, etc.).
    """
    try:
        storage = _get_storage(ctx)
        interventions = await storage.get_interventions()
        result = []
        for name in interventions:
            count = await storage.count_documents(name)
            docs = storage.get_documents(name)
            source_counts: dict[str, int] = {}
            for doc in docs:
                st = doc.source_type.value
                source_counts[st] = source_counts.get(st, 0) + 1
            result.append(
                {"name": name, "document_count": count, "by_source_type": source_counts}
            )
        return _json({"interventions": result, "total": len(result)})
    except Exception as e:
        return _json({"error": str(e), "tool": "list_interventions"})


@mcp.tool()
async def get_intervention_stats(intervention: str, ctx: Context) -> str:
    """Get comprehensive summary statistics for an aging intervention.

    Includes document counts by source type, date ranges, PubMed publication types,
    clinical trial phases and enrollment, DrugAge lifespan data, NIH grant funding,
    patent filings, regulatory status, and Google Trends data.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin', 'senolytics')
    """
    try:
        storage = _get_storage(ctx)
        name = intervention.lower()
        error, _ = await _validate_intervention(storage, name)
        if error:
            return error
        summary = generate_summary(name)
        if not summary:
            return _json({"error": f"No data available for '{name}'"})
        return _json(summary)
    except Exception as e:
        return _json({"error": str(e), "tool": "get_intervention_stats"})


@mcp.tool()
async def get_evidence_grade(intervention: str, ctx: Context) -> str:
    """Get the evidence level distribution for an aging intervention.

    Shows how studies are distributed across evidence levels:
    Level 1 (systematic reviews), Level 2 (RCTs), Level 3 (observational),
    Level 4 (animal), Level 5 (in vitro), Level 6 (in silico).

    Note: Full evidence grading with LLM classification is not yet implemented.
    Use get_intervention_stats for detailed counts by source type.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin')
    """
    try:
        storage = _get_storage(ctx)
        name = intervention.lower()
        error, _ = await _validate_intervention(storage, name)
        if error:
            return error
        total = await storage.count_documents(name)
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Evidence grading not yet implemented. Use get_intervention_stats for basic counts.",
            "total_documents": total,
            "evidence_distribution": {},
            "composite_score": None,
            "confidence": None,
        })
    except Exception as e:
        return _json({"error": str(e), "tool": "get_evidence_grade"})


@mcp.tool()
async def get_evidence_trajectory(intervention: str, ctx: Context) -> str:
    """Analyse how evidence is accumulating over time for an aging intervention.

    Returns momentum score, phase label (emerging/accelerating/mature/stagnant/declining),
    publication velocity, and whether evidence is climbing the hierarchy.

    Note: Full trajectory scoring is not yet implemented.
    Use get_intervention_stats for year-by-year publication counts.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin')
    """
    try:
        storage = _get_storage(ctx)
        name = intervention.lower()
        error, _ = await _validate_intervention(storage, name)
        if error:
            return error
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Trajectory scoring not yet implemented. Use get_intervention_stats for year-by-year counts.",
            "momentum_score": None,
            "phase": None,
            "trend_direction": None,
        })
    except Exception as e:
        return _json({"error": str(e), "tool": "get_evidence_trajectory"})


@mcp.tool()
async def get_evidence_gaps(intervention: str, ctx: Context) -> str:
    """Identify what evidence is MISSING for an aging intervention.

    Checks for: no human data, no RCTs, no Cochrane review, single-lab findings,
    no female subjects, no dose-response data, no long-term follow-up.

    Note: Full gap analysis is not yet implemented.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin')
    """
    try:
        storage = _get_storage(ctx)
        name = intervention.lower()
        error, _ = await _validate_intervention(storage, name)
        if error:
            return error
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Gap analysis not yet implemented.",
            "gaps": [],
            "completeness_score": None,
        })
    except Exception as e:
        return _json({"error": str(e), "tool": "get_evidence_gaps"})


@mcp.tool()
async def get_hype_ratio(intervention: str, ctx: Context) -> str:
    """Compare scientific evidence strength against media and social media hype.

    Returns a bull/bear index flagging whether an intervention is overhyped
    or underhyped relative to its actual evidence base.

    Note: Full hype ratio analysis is not yet implemented.
    Use get_intervention_stats for raw Google Trends and social media data.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin')
    """
    try:
        storage = _get_storage(ctx)
        name = intervention.lower()
        error, _ = await _validate_intervention(storage, name)
        if error:
            return error
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Hype ratio not yet implemented. Use get_intervention_stats for raw trend data.",
            "hype_ratio": None,
            "evidence_score": None,
            "media_score": None,
        })
    except Exception as e:
        return _json({"error": str(e), "tool": "get_hype_ratio"})


@mcp.tool()
async def get_full_report(intervention: str, ctx: Context) -> str:
    """Generate a comprehensive evidence report for an aging intervention.

    Combines evidence grading, trajectory analysis, gap identification, and
    hype ratio into a single structured report with transparent confidence scoring.

    Note: Full report generation is not yet implemented.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin')
    """
    try:
        storage = _get_storage(ctx)
        name = intervention.lower()
        error, _ = await _validate_intervention(storage, name)
        if error:
            return error
        total = await storage.count_documents(name)
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Report generation not yet implemented.",
            "total_documents_analysed": total,
            "sections": {
                "evidence_grade": None,
                "trajectory": None,
                "gaps": None,
                "hype_ratio": None,
            },
            "overall_confidence": None,
            "summary": None,
        })
    except Exception as e:
        return _json({"error": str(e), "tool": "get_full_report"})


@mcp.tool()
async def search_documents(
    query: str,
    ctx: Context,
    intervention: str | None = None,
    source_type: str | None = None,
    limit: int = 20,
) -> str:
    """Search across all indexed longevity research documents.

    Performs text search on document titles and abstracts. Optionally filter
    by intervention name and/or source type.

    Args:
        query: Search text to match against titles and abstracts
        intervention: Optional intervention name to limit search scope
        source_type: Optional source type filter (pubmed, clinicaltrials, drugage, europe_pmc, semantic_scholar, nih_grant, patent, regulatory, news, social)
        limit: Maximum results to return (default 20, max 100)
    """
    try:
        storage = _get_storage(ctx)
        limit = min(max(limit, 1), 100)
        query_lower = query.lower()

        if intervention:
            name = intervention.lower()
            error, _ = await _validate_intervention(storage, name)
            if error:
                return error
            docs = storage.get_documents(name)
        else:
            all_interventions = await storage.get_interventions()
            docs = []
            for name in all_interventions:
                docs.extend(storage.get_documents(name))

        if source_type:
            docs = [d for d in docs if d.source_type.value == source_type]

        matches = []
        for doc in docs:
            text = f"{doc.title} {doc.abstract}".lower()
            if query_lower in text:
                matches.append({
                    "id": doc.id,
                    "source_type": doc.source_type.value,
                    "intervention": doc.intervention,
                    "title": doc.title,
                    "abstract": (
                        doc.abstract[:300] + "..." if len(doc.abstract) > 300 else doc.abstract
                    ),
                    "source_url": doc.source_url,
                    "date_published": doc.date_published.isoformat(),
                })
                if len(matches) >= limit:
                    break

        return _json({"query": query, "results": matches, "returned": len(matches)})
    except Exception as e:
        return _json({"error": str(e), "tool": "search_documents"})


# ── Entry Point ──────────────────────────────────────────────────────────────


def main():
    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
