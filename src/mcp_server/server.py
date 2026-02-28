"""AGE-nt MCP Server — exposes intervention data as MCP tools.

Run standalone:
    python -m src.mcp_server.server

Test with MCP Inspector:
    mcp dev src/mcp_server/server.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from contextlib import asynccontextmanager

import aiosqlite
from loguru import logger
from mcp.server.fastmcp import Context, FastMCP

from src.config import PROJECT_ROOT, settings
from src.stats.summary import generate_summary
from src.storage.manager import StorageManager
from src.tools.sql_query import (
    has_limit_clause,
    rewrite_select_star,
    validate_sql,
)

# Import dynamic tool discovery from API routes (shared logic)
from src.api.routes.tools import discover_tools, _read_cache, _write_cache


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Initialize StorageManager and read-only DB connection on startup."""
    storage = StorageManager()
    await storage.initialize()
    logger.info("MCP server: StorageManager initialized")

    # Separate read-only connection for sql_query tool
    ro_db = await aiosqlite.connect(str(settings.sqlite_path))
    ro_db.row_factory = aiosqlite.Row
    await ro_db.execute("PRAGMA query_only = ON")
    logger.info("MCP server: Read-only SQL connection initialized")

    try:
        yield {"storage": storage, "ro_db": ro_db}
    finally:
        await ro_db.close()
        await storage.close()
        logger.info("MCP server: connections closed")


mcp = FastMCP(
    "age-nt",
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


def _run_tool_cached(tool_name: str, intervention: str, storage: StorageManager) -> dict | None:
    """Try to run a dynamic tool from src/tools/ with caching.

    Returns the result dict if the tool exists and succeeds, None otherwise.
    """
    # Check cache first
    cached = _read_cache(tool_name, intervention)
    if cached is not None:
        return cached

    tools = discover_tools()
    if tool_name not in tools:
        return None

    fn, _, _ = tools[tool_name]
    try:
        result = fn(intervention, storage)
        result_dict = result.model_dump() if hasattr(result, "model_dump") else result
        _write_cache(tool_name, intervention, result_dict)
        return result_dict
    except Exception as e:
        logger.warning(f"Tool {tool_name} failed for {intervention}: {e}")
        return None


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

        # Try dynamic tool first
        result = _run_tool_cached("evidence", name, storage)
        if result is not None:
            return _json(result)

        # Fallback: stub response
        total = await storage.count_documents(name)
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Evidence grading tool not yet implemented. Use get_intervention_stats for basic counts.",
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

    Returns momentum score (0-1), phase label (emerging/accelerating/mature/
    stagnant/declining), publication velocity, source diversification, trial
    pipeline progression, and plot-ready time series arrays.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin')
    """
    try:
        storage = _get_storage(ctx)
        name = intervention.lower()
        error, _ = await _validate_intervention(storage, name)
        if error:
            return error

        # Try dynamic tool first
        result = _run_tool_cached("trajectory", name, storage)
        if result is not None:
            return _json(result)

        # Fallback: stub response
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Trajectory scoring tool not yet implemented. Use get_intervention_stats for year-by-year counts.",
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

        # Try dynamic tool first
        result = _run_tool_cached("gaps", name, storage)
        if result is not None:
            return _json(result)

        # Fallback: stub response
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Gap analysis tool not yet implemented.",
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

        # Try dynamic tool first
        result = _run_tool_cached("hype", name, storage)
        if result is not None:
            return _json(result)

        # Fallback: stub response
        return _json({
            "intervention": name,
            "status": "stub",
            "message": "Hype ratio tool not yet implemented. Use get_intervention_stats for raw trend data.",
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

        # Try dynamic tool first
        result = _run_tool_cached("report", name, storage)
        if result is not None:
            return _json(result)

        # Fallback: run each available sub-tool and assemble
        total = await storage.count_documents(name)
        sections = {
            "evidence_grade": _run_tool_cached("evidence", name, storage),
            "trajectory": _run_tool_cached("trajectory", name, storage),
            "gaps": _run_tool_cached("gaps", name, storage),
            "hype_ratio": _run_tool_cached("hype", name, storage),
        }
        has_any = any(v is not None for v in sections.values())

        return _json({
            "intervention": name,
            "status": "partial" if has_any else "stub",
            "message": "Assembled from available sub-tools." if has_any else "Report generation not yet implemented.",
            "total_documents_analysed": total,
            "sections": sections,
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


# ── Bryan Johnson / Influencer Takes ────────────────────────────────────────

_BRYAN_JOHNSON_DATA: dict | None = None


def _load_bryan_johnson() -> dict:
    """Lazy-load Bryan Johnson quotes from JSON."""
    global _BRYAN_JOHNSON_DATA
    if _BRYAN_JOHNSON_DATA is None:
        path = PROJECT_ROOT / "data" / "bryan_johnson.json"
        if path.exists():
            _BRYAN_JOHNSON_DATA = json.loads(path.read_text())
        else:
            _BRYAN_JOHNSON_DATA = {"interventions": {}}
    return _BRYAN_JOHNSON_DATA


@mcp.tool()
async def get_bryan_johnson_take(
    intervention: str,
    ctx: Context,
) -> str:
    """Get Bryan Johnson's take on an aging intervention.

    Returns his stance (strong_advocate/advocate/interested/neutral/cautious/
    skeptical/former_user), relevant quotes from Blueprint protocol posts and
    podcasts, and whether it's in his active protocol.

    Bryan Johnson is the founder of Blueprint — a protocol to measure and
    reverse biological aging through extreme self-experimentation. His takes
    are useful as a well-known reference point in the longevity space.

    Note: Quotes are representative paraphrases of his known public positions,
    not exact transcriptions. For primary sources, check blueprint.bryanjohnson.com.

    Args:
        intervention: Name of the intervention (e.g. 'rapamycin', 'metformin', 'exercise')
    """
    try:
        data = _load_bryan_johnson()
        interventions_data = data.get("interventions", {})
        name = intervention.lower().strip()

        # Direct match
        if name in interventions_data:
            entry = interventions_data[name]
            return _json({
                "intervention": name,
                "bryan_johnson": entry,
                "source": "Blueprint protocol — synthesised from public posts and podcasts",
            })

        # Fuzzy: check if intervention appears as a substring in any key
        for key, entry in interventions_data.items():
            if name in key or key in name:
                return _json({
                    "intervention": name,
                    "matched_as": key,
                    "bryan_johnson": entry,
                    "source": "Blueprint protocol — synthesised from public posts and podcasts",
                })

        # Not found
        available = sorted(interventions_data.keys())
        return _json({
            "intervention": name,
            "bryan_johnson": None,
            "message": f"No Bryan Johnson take found for '{name}'.",
            "available_interventions": available,
        })
    except Exception as e:
        return _json({"error": str(e), "tool": "get_bryan_johnson_take"})


# ── Cross-Intervention Query Tools ───────────────────────────────────────────


@mcp.tool()
async def sql_query(
    query: str,
    ctx: Context,
    limit: int = 50,
    include_raw: bool = False,
) -> str:
    """Run a read-only SQL query against the AGE-nt research database.

    The database has a single 'documents' table with ~11,500 documents across
    52 aging interventions from 10 source types. Use this for cross-intervention
    comparisons, aggregations, and filtering.

    TABLE: documents

    KEY COLUMNS:
      Identity: id, source_type, intervention, title, abstract, source_url
      Temporal: date_published, date_indexed
      Grouping: category, subcategory
      PubMed: pmid, doi, journal, impact_factor, peer_reviewed
      Trials: nct_id, phase, status, enrollment, sponsor,
              date_registered, date_started, date_completed
      Europe PMC: pmcid, cited_by_count, is_open_access, is_cochrane
      Semantic Scholar: paper_id, citation_count, influential_citation_count, tldr
      DrugAge: species, strain, dosage, lifespan_change_percent, significance, gender
      Grants: project_number, pi_name, organisation, total_funding, fiscal_year,
              funding_mechanism, nih_institute
      Patents: patent_id, assignee, filing_date, patent_status, patent_office
      Regulatory: approval_date, drug_class, nda_number
      Social/News: sentiment, score, comment_count, platform, subreddit, outlet
      Classification: evidence_level, study_type, organism, effect_direction

    SOURCE TYPES: pubmed, clinicaltrials, europe_pmc, semantic_scholar,
                  drugage, nih_grant, patent, regulatory, news, social

    CATEGORIES: NAD_metabolism, anti_inflammatory, autophagy_induction,
                cell_therapy, dietary_intervention, epigenetic_intervention,
                immune_rejuvenation, mTOR_inhibition, metabolic_intervention,
                mitochondrial, neuroprotection, physical_intervention,
                senolytics, sirtuin_activation, systemic_factors,
                telomere_intervention

    INDEXED (fast): intervention, source_type, date_published, evidence_level,
                    organism, nct_id, pmid, doi, category, subcategory,
                    (intervention, source_type), (intervention, date_published),
                    (category, source_type), (category, intervention)

    EXAMPLE QUERIES:
      -- Count documents per intervention
      SELECT intervention, COUNT(*) as cnt FROM documents
      GROUP BY intervention ORDER BY cnt DESC

      -- Which interventions have the most Phase 3 clinical trials?
      SELECT intervention, COUNT(*) as phase3_count
      FROM documents WHERE source_type='clinicaltrials' AND phase='PHASE3'
      GROUP BY intervention ORDER BY phase3_count DESC

      -- Average lifespan extension by species from DrugAge
      SELECT species, AVG(lifespan_change_percent) as avg_ext, COUNT(*) as n
      FROM documents WHERE source_type='drugage'
        AND lifespan_change_percent IS NOT NULL
      GROUP BY species ORDER BY avg_ext DESC

      -- Total NIH funding by intervention
      SELECT intervention, SUM(total_funding) as total, COUNT(*) as grants
      FROM documents WHERE source_type='nih_grant' AND total_funding IS NOT NULL
      GROUP BY intervention ORDER BY total DESC

      -- Most cited papers across all interventions
      SELECT intervention, title, citation_count FROM documents
      WHERE citation_count IS NOT NULL ORDER BY citation_count DESC LIMIT 20

    Args:
        query: SQL SELECT query to execute. Only SELECT and WITH (CTE) allowed.
        limit: Max rows to return (default 50, max 500). Applied if query has
               no LIMIT clause.
        include_raw: Include raw_response and source_metadata columns
                     (default False — they are large JSON blobs).
    """
    try:
        ro_db = ctx.request_context.lifespan_context["ro_db"]

        # Layer 2: validate query safety
        is_valid, error_msg = validate_sql(query)
        if not is_valid:
            return _json({"error": error_msg, "tool": "sql_query"})

        # Enforce row limit bounds
        limit = min(max(limit, 1), 500)

        # Rewrite SELECT * to exclude heavy columns unless requested
        effective_query = query
        if not include_raw:
            effective_query = rewrite_select_star(effective_query)

        # Auto-append LIMIT if not present
        truncation_possible = False
        if not has_limit_clause(effective_query):
            effective_query = f"{effective_query.rstrip(';')} LIMIT {limit}"
            truncation_possible = True

        start = time.monotonic()
        cursor = await ro_db.execute(effective_query)
        rows = await cursor.fetchall()
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        result_rows = [dict(zip(columns, row)) for row in rows]

        result = {
            "columns": columns,
            "rows": result_rows,
            "row_count": len(result_rows),
            "truncated": truncation_possible and len(result_rows) == limit,
            "execution_time_ms": elapsed_ms,
        }
        if effective_query != query:
            result["effective_query"] = effective_query

        return _json(result)
    except Exception as e:
        logger.error(f"sql_query error: {e}")
        return _json({"error": str(e), "tool": "sql_query"})


# ── Code Execution Tool ─────────────────────────────────────────────────────

_PYTHON_PREAMBLE = '''
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

PLOTS_DIR = "{plots_dir}"
DB_PATH = "{db_path}"
os.makedirs(PLOTS_DIR, exist_ok=True)

def save_plot(name=None):
    """Save current matplotlib figure. Call instead of plt.show()."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    fname = f"{{name or 'plot'}}_{{ts}}.png"
    path = os.path.join(PLOTS_DIR, fname)
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"PLOT_SAVED:{{path}}")
    return path
'''


@mcp.tool()
async def run_python(
    code: str,
    ctx: Context,
    timeout: int = 30,
) -> str:
    """Execute Python code for data analysis and visualisation.

    Runs code in a subprocess with access to pandas, numpy, matplotlib,
    seaborn, sqlite3, and the standard library.

    Pre-configured variables available in your code:
      DB_PATH   — path to the AGE-nt SQLite database (read-only)
      PLOTS_DIR — directory where plots are saved
      save_plot(name) — save current matplotlib figure (call instead of plt.show())

    Common patterns:
      # Query database with pandas
      import sqlite3, pandas as pd
      conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
      df = pd.read_sql_query(
          "SELECT intervention, COUNT(*) as cnt FROM documents GROUP BY intervention",
          conn,
      )
      print(df.to_string())

      # Create and save a plot
      df.plot(kind='bar', x='intervention', y='cnt', figsize=(12, 6))
      save_plot('intervention_counts')

    Output: Captured stdout. Use print() to return results.
    Plots: Call save_plot('name') to save figures. Paths returned in response.

    Args:
        code: Python code to execute.
        timeout: Max execution time in seconds (default 30, max 120).
    """
    try:
        timeout = min(max(timeout, 5), 120)

        plots_dir = str(PROJECT_ROOT / "data" / "plots")
        db_path = str(settings.sqlite_path)

        preamble = _PYTHON_PREAMBLE.format(plots_dir=plots_dir, db_path=db_path)
        full_code = preamble + "\n" + code

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir=str(PROJECT_ROOT)
        ) as f:
            f.write(full_code)
            script_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            # Extract plot paths from stdout
            plots: list[str] = []
            output_lines: list[str] = []
            for line in stdout_str.splitlines():
                if line.startswith("PLOT_SAVED:"):
                    plots.append(line.split(":", 1)[1])
                else:
                    output_lines.append(line)

            output = "\n".join(output_lines)
            if len(output) > 50_000:
                output = output[:50_000] + "\n... (output truncated at 50KB)"

            result: dict = {
                "success": proc.returncode == 0,
                "output": output,
                "plots": plots,
            }
            if stderr_str and proc.returncode != 0:
                result["error"] = stderr_str[-5000:]
            elif stderr_str:
                result["warnings"] = stderr_str[-2000:]

            return _json(result)

        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return _json({
                "success": False,
                "error": f"Execution timed out after {timeout} seconds",
                "output": "",
                "plots": [],
            })
        finally:
            os.unlink(script_path)

    except Exception as e:
        logger.error(f"run_python error: {e}")
        return _json({"error": str(e), "tool": "run_python"})


# ── Entry Point ──────────────────────────────────────────────────────────────


def main():
    transport = "stdio"
    if "--sse" in sys.argv:
        transport = "sse"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
