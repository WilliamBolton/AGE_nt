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

    # Evidence grader — deterministic rubric scoring (no MedGemma needed)
    try:
        from src.tools.evidence_grader import _deterministic_rubric_score

        def _run_evidence(intervention: str, storage: StorageManager) -> dict:
            docs = _fetch_docs_as_dicts(intervention, storage)
            return _deterministic_rubric_score(fetched_documents=docs)

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

    # Gap analysis — deterministic gap analysis (no MedGemma needed)
    try:
        from src.tools.gap_analysis import _deterministic_gap_analysis

        def _run_gaps(intervention: str, storage: StorageManager) -> dict:
            docs = _fetch_docs_as_dicts(intervention, storage)
            return _deterministic_gap_analysis(fetched_documents=docs)

        tools["gaps"] = (
            _run_gaps,
            "Identify missing evidence types for an intervention. Returns completeness score and gap list.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Hype ratio — deterministic hype analysis (no MedGemma needed)
    try:
        from src.tools.hype_ratio import _deterministic_hype_ratio

        def _run_hype(intervention: str, storage: StorageManager) -> dict:
            docs = _fetch_docs_as_dicts(intervention, storage)
            return _deterministic_hype_ratio(docs)

        tools["hype"] = (
            _run_hype,
            "Compute evidence-to-hype ratio for an intervention. Returns evidence score, hype score, and verdict.",
            ["intervention"],
        )
    except (ImportError, AttributeError):
        pass

    # Report generator
    try:
        from src.tools.report_generator import generate_full_report

        tools["report"] = (
            generate_full_report,
            "Generate a full evidence report for an intervention. Combines all available tools.",
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

    # Always include stats and list — these don't need tool implementations
    definitions.extend([
        {
            "name": "get_stats",
            "description": "Get summary statistics for an intervention including document counts, source types, date ranges, and detailed breakdowns.",
            "parameters": {
                "type": "object",
                "properties": {"intervention": {"type": "string", "description": "The intervention name"}},
                "required": ["intervention"],
            },
        },
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
