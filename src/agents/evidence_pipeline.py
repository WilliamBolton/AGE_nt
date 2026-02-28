"""
Evidence-grading LangGraph pipeline.

Orchestrates: query expansion → ingest (multiple sources) → classification (stub) →
evidence grading → trajectory → gap spotting → report generation.

Uses existing ingest agents, StorageManager, and stubs for reasoning/classify
until full modules are implemented. Replace stubs with src.reasoning.* and
src.classify.llm_classifier when available.
"""

from __future__ import annotations

import asyncio
from typing import Any

import google.genai as genai
from langgraph.graph import END, START, StateGraph
import logging

from .reasoning_stubs import evidence_grade_stub, gaps_stub, trajectory_stub
from .state import EvidencePipelineState
from ..config import settings
from ..ingest.clinical_trials import ClinicalTrialsAgent
from ..ingest.pubmed import PubMedAgent
from ..ingest.query_expander import expand_query, load_cached_expansion
from ..storage.manager import StorageManager

logger = logging.getLogger(__name__)

# Default sources for the pipeline (can be overridden per run)
DEFAULT_INGEST_SOURCES = ["pubmed", "clinicaltrials"]

# Ingest agent class by source key (subset of seed_intervention's ALL_SOURCES)
INGEST_AGENTS: dict[str, type] = {
    "pubmed": PubMedAgent,
    "clinicaltrials": ClinicalTrialsAgent,
}


def _gemini_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key or "")


# ── Node implementations ────────────────────────────────────────────────────


async def expand_node(state: EvidencePipelineState) -> EvidencePipelineState:
    """Expand search terms for the intervention via LLM (cached)."""
    intervention = state.get("intervention") or ""
    aliases = state.get("aliases") or []
    errors = list(state.get("errors") or [])

    try:
        expansion = await expand_query(intervention, aliases)
        summary = (
            f"Primary: {expansion.primary_name}; "
            f"{len(expansion.synonyms)} synonyms, {len(expansion.analogs)} analogs; "
            f"queries for: {list(expansion.queries.keys())}"
        )
        return {
            **state,
            "query_expansion_done": True,
            "query_expansion_summary": summary,
            "errors": errors,
        }
    except Exception as e:
        logger.warning(f"Query expansion failed: {e}")
        errors.append(f"Query expansion: {e}")
        return {
            **state,
            "query_expansion_done": False,
            "query_expansion_summary": "",
            "errors": errors,
        }


async def ingest_node(state: EvidencePipelineState) -> EvidencePipelineState:
    """Run ingest agents for the intervention and store documents."""
    intervention = (state.get("intervention") or "").strip().lower()
    aliases = state.get("aliases") or []
    errors = list(state.get("errors") or [])
    ingest_errors = list(state.get("ingest_errors") or [])
    sources_used: list[str] = []

    if not intervention:
        return {**state, "documents_count": 0, "documents_summary": "No intervention name.", "errors": errors}

    storage = StorageManager()
    await storage.initialize()

    # Get query expansion from cache (expand_node already ran)
    query_expansion = None
    try:
        query_expansion = load_cached_expansion(intervention)
    except Exception:
        pass

    total_added = 0
    for source_key in DEFAULT_INGEST_SOURCES:
        if source_key not in INGEST_AGENTS:
            continue
        agent_cls = INGEST_AGENTS[source_key]
        agent = agent_cls(storage=storage)
        try:
            docs = await agent.ingest(
                intervention=intervention,
                aliases=aliases,
                query_expansion=query_expansion,
                max_results=50,
            )
            if docs:
                added = await storage.save_documents(intervention, docs, aliases)
                total_added += added
                sources_used.append(agent.source_name)
        except Exception as e:
            logger.error(f"Ingest {source_key}: {e}")
            ingest_errors.append(f"{source_key}: {e}")

    docs = storage.get_documents(intervention)
    await storage.close()

    # Build a short summary for the reporter (titles, sources)
    summary_parts = [f"Total documents: {len(docs)}. Sources: {', '.join(sources_used) or 'none'}."]
    for i, d in enumerate(docs[:15]):
        summary_parts.append(f"  [{d.source_type.value}] {d.title[:80]}...")
    if len(docs) > 15:
        summary_parts.append(f"  ... and {len(docs) - 15} more.")

    return {
        **state,
        "documents_count": len(docs),
        "documents_summary": "\n".join(summary_parts),
        "sources_used": sources_used,
        "ingest_errors": ingest_errors,
        "errors": errors + [f"Ingest: {e}" for e in ingest_errors],
    }


async def classify_node(state: EvidencePipelineState) -> EvidencePipelineState:
    """Ensure documents are classified. Stub: no-op until src.classify.llm_classifier exists."""
    intervention = (state.get("intervention") or "").strip().lower()
    errors = list(state.get("errors") or [])

    if not intervention or state.get("documents_count", 0) == 0:
        return {**state, "classification_done": True, "unclassified_count": 0, "errors": errors}

    # Optional: call future classify module here, then update_classifications
    # For now we just mark as done; evidence_grade_stub uses source/publication_type proxy
    return {
        **state,
        "classification_done": True,
        "unclassified_count": 0,
        "errors": errors,
    }


async def evidence_node(state: EvidencePipelineState) -> EvidencePipelineState:
    """Compute evidence distribution and confidence. Uses stub until reasoning.evidence_grader exists."""
    intervention = (state.get("intervention") or "").strip().lower()
    errors = list(state.get("errors") or [])

    if not intervention:
        return {**state, "evidence_summary": "No intervention.", "errors": errors}

    storage = StorageManager()
    docs = storage.get_documents(intervention)
    summary_dict = evidence_grade_stub(docs)
    summary_text = (
        f"Total: {summary_dict['total']}. "
        f"By source: {summary_dict.get('by_source', {})}. "
        f"By evidence level (proxy): {summary_dict.get('by_level_proxy', {})}. "
        f"Confidence (stub): {summary_dict.get('confidence_score', 0)}. "
        f"Reasoning: {summary_dict.get('reasoning', '')}"
    )
    return {
        **state,
        "evidence_summary": summary_text,
        "errors": errors,
    }


async def trajectory_node(state: EvidencePipelineState) -> EvidencePipelineState:
    """Temporal momentum. Uses stub until reasoning.trajectory exists."""
    intervention = (state.get("intervention") or "").strip().lower()
    errors = list(state.get("errors") or [])

    if not intervention:
        return {**state, "trajectory_summary": "No intervention.", "errors": errors}

    storage = StorageManager()
    await storage.initialize()
    docs = storage.get_documents(intervention)
    timeline = await storage.get_timeline(intervention)
    await storage.close()

    traj = trajectory_stub(docs, timeline)
    summary_text = (
        f"Phase: {traj.get('phase', 'unknown')}. "
        f"Year range: {traj.get('year_range', 'N/A')}. "
        f"Recent publications: {traj.get('recent_publications', 0)}. "
        f"Reasoning: {traj.get('reasoning', '')}"
    )
    return {
        **state,
        "trajectory_summary": summary_text,
        "errors": errors,
    }


async def gaps_node(state: EvidencePipelineState) -> EvidencePipelineState:
    """Identify evidence gaps. Uses stub until reasoning.gap_spotter exists."""
    intervention = (state.get("intervention") or "").strip().lower()
    errors = list(state.get("errors") or [])

    if not intervention:
        return {**state, "gaps_summary": "No intervention.", "errors": errors}

    storage = StorageManager()
    docs = storage.get_documents(intervention)
    # Reuse evidence summary from state if we had stored structured data; else recompute
    evidence_by_source = {}
    evidence_by_level = {}
    for d in docs:
        evidence_by_source[d.source_type.value] = evidence_by_source.get(d.source_type.value, 0) + 1
    evidence_summary = {"by_source": evidence_by_source, "by_level_proxy": evidence_by_level}
    gaps_dict = gaps_stub(docs, evidence_summary)
    summary_text = (
        f"Missing: {gaps_dict.get('missing', [])}. "
        f"Warnings: {gaps_dict.get('warnings', [])}"
    )
    return {
        **state,
        "gaps_summary": summary_text,
        "errors": errors,
    }


async def reporter_node(state: EvidencePipelineState) -> EvidencePipelineState:
    """Generate final structured report and confidence score using Gemini."""
    intervention = state.get("intervention") or "Unknown"
    evidence = state.get("evidence_summary") or ""
    trajectory = state.get("trajectory_summary") or ""
    gaps = state.get("gaps_summary") or ""
    doc_summary = state.get("documents_summary") or ""

    prompt = (
        "You are a biomedical analyst specialising in ageing and longevity evidence.\n\n"
        f"Intervention: {intervention}\n\n"
        "Below are the evidence summary, trajectory summary, and gap analysis (from automated retrieval and stub grading).\n"
        "Produce a short, structured evidence report (1–2 pages) with:\n"
        "1. Executive summary (2–3 sentences)\n"
        "2. Evidence distribution (by level/source)\n"
        "3. Temporal momentum (phase, recent activity)\n"
        "4. Key gaps and caveats\n"
        "5. A single confidence score from 0 to 100 and 2–3 sentences of transparent reasoning for that score.\n\n"
        f"Evidence summary:\n{evidence}\n\n"
        f"Trajectory:\n{trajectory}\n\n"
        f"Gaps:\n{gaps}\n\n"
        f"Document list (sample):\n{doc_summary}\n\n"
        "End the report with a line: CONFIDENCE_SCORE: <number> and CONFIDENCE_REASONING: <your reasoning>."
    )

    errors = list(state.get("errors") or [])
    report = ""
    confidence_score = 0.0
    confidence_reasoning = ""

    try:
        client = _gemini_client()
        result = client.models.generate_content(
            model=settings.gemini_model or "gemini-3-flash-preview",
            contents=[prompt],
        )
        text_parts = []
        for candidate in getattr(result, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                if hasattr(part, "text"):
                    text_parts.append(part.text)
        report = "\n".join(text_parts) if text_parts else str(result)

        # Parse CONFIDENCE_SCORE and CONFIDENCE_REASONING from report if present
        for line in report.split("\n"):
            line = line.strip()
            if line.upper().startswith("CONFIDENCE_SCORE:"):
                try:
                    confidence_score = float(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.upper().startswith("CONFIDENCE_REASONING:"):
                confidence_reasoning = line.split(":", 1)[1].strip()
    except Exception as e:
        logger.error(f"Reporter node failed: {e}")
        errors.append(f"Reporter: {e}")
        report = f"Report generation failed: {e}"
        confidence_score = 0.0
        confidence_reasoning = "Error during report generation."

    return {
        **state,
        "report": report,
        "confidence_score": confidence_score,
        "confidence_reasoning": confidence_reasoning,
        "errors": errors,
    }


# ── Build the graph ─────────────────────────────────────────────────────────

def build_evidence_pipeline() -> Any:
    """Build and compile the evidence-grading LangGraph pipeline."""
    builder = StateGraph(EvidencePipelineState)

    builder.add_node("expand", expand_node)
    builder.add_node("ingest", ingest_node)
    builder.add_node("classify", classify_node)
    builder.add_node("evidence", evidence_node)
    builder.add_node("trajectory", trajectory_node)
    builder.add_node("gaps", gaps_node)
    builder.add_node("reporter", reporter_node)

    builder.add_edge(START, "expand")
    builder.add_edge("expand", "ingest")
    builder.add_edge("ingest", "classify")
    builder.add_edge("classify", "evidence")
    builder.add_edge("evidence", "trajectory")
    builder.add_edge("trajectory", "gaps")
    builder.add_edge("gaps", "reporter")
    builder.add_edge("reporter", END)

    return builder.compile()


# Compiled pipeline for use in main.py or API
evidence_pipeline = build_evidence_pipeline()
