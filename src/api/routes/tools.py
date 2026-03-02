"""Dynamic tool discovery and execution endpoints.

Wraps whatever tools exist in src/tools/, caching results to
data/analysis/{tool_name}/{intervention}.json on first run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from src.api.dependencies import get_storage
from src.config import PROJECT_ROOT
from src.storage.manager import StorageManager

router = APIRouter(prefix="/tools", tags=["tools"])


# ── Tool discovery ───────────────────────────────────────────────────────────

# Maps tool name → (function, description, param names)
_ToolEntry = tuple[Callable, str, list[str]]


def _fetch_docs_as_dicts(intervention: str, storage: StorageManager) -> list[dict]:
    """Load documents for an intervention and convert to plain dicts."""
    docs = storage.get_documents(intervention)
    return [d.model_dump() if hasattr(d, "model_dump") else d for d in docs]


def discover_tools() -> dict[str, _ToolEntry]:
    """Import available tool functions from src/tools/.

    Returns a dict mapping tool name to (function, description, params).
    Only includes tools that are actually implemented (importable + callable).

    Teammate tools use class-based MedGemma interfaces; we wrap their
    deterministic (no-GPU) fallback functions so the API works anywhere.
    """
    tools: dict[str, _ToolEntry] = {}

    # Evidence grader — MedGemma precomputed → deterministic fallback
    try:
        from src.tools.evidence_grader import _deterministic_rubric_score

        def _run_evidence(intervention: str, storage: StorageManager) -> dict:
            medgemma = _read_medgemma_cache("evidence", intervention)
            if medgemma is not None:
                medgemma["_source"] = "medgemma_precomputed"
                return medgemma
            docs = _fetch_docs_as_dicts(intervention, storage)
            result = _deterministic_rubric_score(fetched_documents=docs)
            result["_source"] = "deterministic"
            return result

        tools["evidence"] = (
            _run_evidence,
            "Grade the evidence base for an intervention. Returns evidence level distribution, composite score, and confidence.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Trajectory scorer — already has the right (intervention, storage) signature
    try:
        from src.tools.trajectory import score_trajectory

        tools["trajectory"] = (
            score_trajectory,
            "Score research momentum and trajectory for an intervention. Returns momentum score, phase, and trend.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Gap analysis — MedGemma precomputed → deterministic fallback
    try:
        from src.tools.gap_analysis import _deterministic_gap_analysis

        def _run_gaps(intervention: str, storage: StorageManager) -> dict:
            medgemma = _read_medgemma_cache("gaps", intervention)
            if medgemma is not None:
                medgemma["_source"] = "medgemma_precomputed"
                return medgemma
            docs = _fetch_docs_as_dicts(intervention, storage)
            result = _deterministic_gap_analysis(fetched_documents=docs)
            result["_source"] = "deterministic"
            return result

        tools["gaps"] = (
            _run_gaps,
            "Identify missing evidence types for an intervention. Returns completeness score and gap list.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Hype ratio — MedGemma precomputed → deterministic fallback
    try:
        from src.tools.hype_ratio import _deterministic_hype_ratio

        def _run_hype(intervention: str, storage: StorageManager) -> dict:
            medgemma = _read_medgemma_cache("hype", intervention)
            if medgemma is not None:
                medgemma["_source"] = "medgemma_precomputed"
                return medgemma
            docs = _fetch_docs_as_dicts(intervention, storage)
            result = _deterministic_hype_ratio(docs)
            result["_source"] = "deterministic"
            return result

        tools["hype"] = (
            _run_hype,
            "Compute evidence-to-hype ratio for an intervention. Returns evidence score, hype score, and verdict.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Bryan Johnson takes — no StorageManager needed, reads from static JSON
    try:
        from src.tools.bryan_johnson import get_bryan_johnson_take

        def _run_bj(intervention: str, storage: StorageManager) -> dict:
            return get_bryan_johnson_take(intervention)

        tools["bryan_johnson"] = (
            _run_bj,
            "Get Bryan Johnson's stance, quotes, and protocol status for an intervention. Returns verified quotes with source URLs.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Ingest check — check if data exists for an intervention
    try:
        from src.tools.ingest_tool import check_intervention_data

        tools["check_data"] = (
            check_intervention_data,
            "Check what data exists for an intervention. Shows document count, source breakdown, and whether ingest is needed. Always run this before suggesting data collection.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Report generator — assembles all sub-tools into one report
    try:
        from src.tools.report_generator import generate_full_report

        tools["report"] = (
            generate_full_report,
            "Generate a full evidence report for an intervention. Combines all available tools.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Summary statistics — wraps generate_summary()
    try:
        from src.tools.stats_tool import get_stats

        tools["stats"] = (
            get_stats,
            "Get summary statistics for an intervention including document counts, source types, date ranges, and detailed breakdowns.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    return tools


def get_tool_definitions() -> list[dict]:
    """Get Gemini-compatible function declarations for all available tools.

    Used by the chat agent to dynamically build its tool list.
    """
    tools = discover_tools()
    definitions = []

    for name, (_, description, params) in tools.items():
        definitions.append({
            "name": f"get_{name}",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    p: {"type": "string", "description": f"The {p} to analyse"}
                    for p in params
                },
                "required": params,
            },
        })

    # Tools with non-standard signatures (no intervention param, async, etc.)
    definitions.extend([
        {
            "name": "list_interventions",
            "description": "List all available interventions with document counts.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "search_documents",
            "description": "Search across all documents by text query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text"},
                    "intervention": {"type": "string", "description": "Optional: limit to specific intervention"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "run_ingest",
            "description": "Run the data sourcing pipeline for an intervention. Collects evidence from PubMed, ClinicalTrials.gov, Europe PMC, DrugAge, NIH grants, patents, FDA, news, and social media. Takes 1-3 minutes. Automatically skips if data already exists unless force=true. Only use this when check_data shows no data exists, or the user explicitly asks to re-collect data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intervention": {"type": "string", "description": "The intervention name to collect data for"},
                    "force": {"type": "string", "description": "Set to 'true' to force re-ingest even if data exists. Default: false."},
                },
                "required": ["intervention"],
            },
        },
        {
            "name": "ask_edison",
            "description": (
                "Deep literature synthesis via PaperQA3/Edison Scientific. "
                "Submits a research question and returns a cited answer. "
                "SLOW: takes 1-3 minutes per query. Only use for deep synthesis "
                "questions that cannot be answered by other tools (e.g., "
                "'What do NIA ITP studies show about rapamycin dosing?'). "
                "Do NOT use for simple stats, counts, or evidence scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The research question to submit to Edison"},
                    "job_type": {
                        "type": "string",
                        "description": "Edison job type. Default: 'literature'.",
                        "enum": ["literature", "literature_high", "precedent", "analysis", "molecules"],
                    },
                },
                "required": ["query"],
            },
        },
    ])

    return definitions


# ── Cache helpers ────────────────────────────────────────────────────────────

def _cache_path(tool_name: str, intervention: str) -> Path:
    return PROJECT_ROOT / "data" / "analysis" / tool_name / f"{intervention}.json"


def _read_cache(tool_name: str, intervention: str) -> dict | None:
    path = _cache_path(tool_name, intervention)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _read_medgemma_cache(tool_name: str, intervention: str) -> dict | None:
    """Check for pre-computed MedGemma results.

    MedGemma outputs are stored at data/analysis/{tool}_medgemma/{intervention}.json
    and may contain a 'final_output' key wrapping the structured result.
    """
    path = PROJECT_ROOT / "data" / "analysis" / f"{tool_name}_medgemma" / f"{intervention}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("final_output", data)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _write_cache(tool_name: str, intervention: str, data: dict) -> None:
    path = _cache_path(tool_name, intervention)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_tools() -> dict:
    """List all available tools."""
    tools = discover_tools()
    return {
        "tools": [
            {"name": name, "description": desc}
            for name, (_, desc, _) in tools.items()
        ],
        "count": len(tools),
    }


@router.get("/landscape/scores")
async def landscape_scores(
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Return evidence confidence scores for all interventions.

    Used by the Landscape Explorer to plot real data. Runs the deterministic
    evidence scorer for each intervention (fast, no LLM). Results are cached.
    """
    interventions = await storage.get_interventions()
    tools = discover_tools()
    evidence_fn = tools.get("evidence")
    results = []

    for name in interventions:
        docs = storage.get_documents(name)
        entry: dict = {"name": name, "document_count": len(docs), "confidence": 0}

        # Source diversity: count unique source types
        source_types = set()
        for d in docs:
            st = d.source_type.value if hasattr(d.source_type, "value") else str(d.source_type)
            source_types.add(st)
        entry["source_types"] = len(source_types)

        # Evidence confidence score
        cached = _read_cache("evidence", name)
        if cached is not None:
            entry["confidence"] = cached.get("confidence", 0)
        elif evidence_fn is not None:
            try:
                fn, _, _ = evidence_fn
                result = fn(name, storage)
                result_dict = result.model_dump() if hasattr(result, "model_dump") else result
                _write_cache("evidence", name, result_dict)
                entry["confidence"] = result_dict.get("confidence", 0)
            except Exception as e:
                logger.debug(f"Evidence score failed for {name}: {e}")

        results.append(entry)

    return {"interventions": results, "count": len(results)}


@router.get("/{tool_name}/{intervention}")
async def run_tool(
    tool_name: str,
    intervention: str,
    force: bool = False,
    storage: StorageManager = Depends(get_storage),
) -> dict:
    """Run a tool for an intervention.

    Returns cached output if available (unless force=True).
    Otherwise runs the tool and caches the result.
    """
    # Check cache first
    if not force:
        cached = _read_cache(tool_name, intervention)
        if cached is not None:
            logger.debug(f"Cache hit: {tool_name}/{intervention}")
            return cached

    # Discover tools
    tools = discover_tools()
    if tool_name not in tools:
        available = list(tools.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found. Available: {available}",
        )

    # Validate intervention exists
    interventions = await storage.get_interventions()
    if intervention.lower() not in interventions:
        raise HTTPException(status_code=404, detail=f"Intervention '{intervention}' not found")

    # Run the tool
    fn, _, _ = tools[tool_name]
    try:
        result = fn(intervention.lower(), storage)
        result_dict = result.model_dump() if hasattr(result, "model_dump") else result
    except Exception as e:
        logger.error(f"Tool {tool_name} failed for {intervention}: {e}")
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {e}")

    # Cache
    _write_cache(tool_name, intervention.lower(), result_dict)
    logger.info(f"Cached tool output: {tool_name}/{intervention}")

    return result_dict
