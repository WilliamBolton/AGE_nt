"""
Multi-agent LangGraph: Retriever → (Researcher Classifier | Gap Analyst | Social Media Expert) → Judge → Reporter.

The three analysts run in parallel after the Retriever; Judge and Reporter run sequentially after.
Uses existing tools: evidence_grader.py, gap_analysis.py, hype_ratio.py, intervention_resolver.
Output: structured PDF report with summaries, Judge limitations, and recommendations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.config import PROJECT_ROOT, settings
from src.tools.hype_ratio import score_social_hype
from src.tools.intervention_resolver import find_document_path, resolve_intervention_from_query
from src.tools.judge_tools import prepare_evaluation_package

from .state import ReportPipelineState

logger = logging.getLogger(__name__)


# ─── Paths (relative to project root) ────────────────────────────────────────
def _rubric_path(name: str) -> Path:
    return PROJECT_ROOT / "tasks" / name


def _schema_path() -> Path:
    return PROJECT_ROOT / "JSON_SCHEMA_REFERENCE.md"


def _output_dir() -> Path:
    d = PROJECT_ROOT / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── Retriever ──────────────────────────────────────────────────────────────
async def retriever_node(state: ReportPipelineState) -> ReportPipelineState:
    """Extract intervention name from user_query using data/interventions.json and pass to Researcher Classifier."""
    user_query = (state.get("user_query") or "").strip()
    errors = list(state.get("errors") or [])

    intervention = resolve_intervention_from_query(user_query)
    if not intervention:
        return {
            **state,
            "retriever_error": f"No matching intervention found for query: {user_query!r}. Check data/interventions.json.",
            "errors": errors + ["Retriever: no intervention matched."],
        }

    doc_path = find_document_path(intervention, PROJECT_ROOT)
    if not doc_path or not doc_path.exists():
        return {
            **state,
            "intervention": intervention,
            "retriever_error": f"No document file found for intervention: {intervention}",
            "errors": errors + [f"Retriever: no data/documents file for {intervention}."],
        }

    return {
        **state,
        "intervention": intervention,
        "retriever_error": "",
        "errors": errors,
    }


# ─── Researcher Classifier (evidence_grader, same order/logic as run_medgemma_confidence) ──
def _run_researcher_classifier_sync(intervention: str) -> dict[str, Any]:
    """Synchronous call to EvidenceGrader.grade_with_corpus (same as run_medgemma_confidence.py)."""
    from src.tools.evidence_grader import (
        EvidenceGrader,
        EvidenceGraderConfig,
        EvidenceRetrievalConfig,
    )

    doc_path = find_document_path(intervention, PROJECT_ROOT)
    stats_path = PROJECT_ROOT / "data" / "summary" / f"{intervention}.json"
    if not stats_path.exists():
        stats_path = PROJECT_ROOT / "data" / "summary" / f"{intervention.lower()}.json"
    if not doc_path or not doc_path.exists():
        return {"error": "no_corpus", "message": f"No corpus or summary for {intervention}"}

    corpus_path = str(doc_path.resolve())
    stats_path_str = str(stats_path.resolve()) if stats_path.exists() else str(stats_path)
    schema_path = str(_schema_path().resolve())
    rubric_path = _rubric_path("confidence_rubric.txt")
    if not rubric_path.exists():
        return {"error": "no_rubric", "message": "tasks/confidence_rubric.txt not found"}
    rubric_text = rubric_path.read_text(encoding="utf-8")

    out_dir = _output_dir()
    context_path = str((out_dir / f"{intervention}.json").resolve())
    report_out = str((out_dir / f"{intervention}.md").resolve())

    hf_token = os.getenv("HF_TOKEN")
    device = "cuda" if _cuda_available() else "cpu"

    grader = EvidenceGrader(
        hf_token=hf_token,
        device=device,
        model="google/medgemma-1.5-4b-it",
        cfg=EvidenceGraderConfig(
            max_new_tokens=900,
            report_max_new_tokens=4096,
            scoring_mode="deterministic_only",
        ),
    )

    ctx = grader.grade_with_corpus(
        corpus_path=corpus_path,
        stats_path=stats_path_str,
        schema_path=schema_path,
        rubric_text=rubric_text,
        retrieval_cfg=EvidenceRetrievalConfig(
            min_fetch_docs=20,
            auto_fetch_per_search=3,
            min_per_source=2,
            max_steps=14,
            max_new_tokens=900,
            max_schema_chars=12000,
            explore_first=True,
            default_blocklist=("social", "news"),
        ),
        context_path=context_path,
        report_out_path=report_out,
        report_max_docs=20,
        report_max_text_chars=1200,
        generate_report=True,
    )

    final = ctx.get("final_output", {})
    analysis = ctx.get("analysis_report") or {}
    summary_parts = [
        f"Confidence: {final.get('confidence', 'N/A')} (raw: {final.get('confidence_raw', 'N/A')}, gating_penalty: {final.get('gating_penalty', 'N/A')}).",
        f"Checklist: {json.dumps(final.get('checklist', {}))}.",
    ]
    if analysis.get("preview"):
        summary_parts.append(f"Analysis preview: {analysis['preview'][:500]}...")
    return {
        "final_output": final,
        "analysis_report": analysis,
        "summary": " ".join(summary_parts),
    }


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


async def researcher_classifier_node(state: ReportPipelineState) -> ReportPipelineState:
    """Run evidence grading (same order/logic as run_medgemma_confidence.py) and attach classification + confidence with reasoning."""
    intervention = state.get("intervention")
    errors = list(state.get("errors") or [])

    if not intervention:
        return {**state, "errors": errors + ["Researcher Classifier: no intervention."]}

    try:
        result = await asyncio.to_thread(_run_researcher_classifier_sync, intervention)
    except Exception as e:
        logger.exception("Researcher Classifier failed")
        result = {"error": str(e), "summary": f"Evidence grading failed: {e}"}
        errors.append(f"Researcher Classifier: {e}")

    if "error" in result and "final_output" not in result:
        return {
            **state,
            "researcher_classifier_output": result,
            "researcher_classifier_summary": result.get("summary", result.get("message", str(result))),
            "errors": errors,
        }

    return {
        **state,
        "researcher_classifier_output": result,
        "researcher_classifier_summary": result.get("summary", json.dumps(result.get("final_output", {}))),
        "errors": errors,
    }


# ─── Gap Analyst (run_medgemma_gap_analysis logic) ───────────────────────────
def _run_gap_analyst_sync(intervention: str) -> dict[str, Any]:
    """Synchronous call to GapAnalyzer.analyze_from_paths (same as run_medgemma_gap_analysis.py)."""
    from src.tools.gap_analysis import GapAnalyzer, GapAnalysisConfig
    from src.tools.json_corpus_query_tool import AgentConfig

    doc_path = find_document_path(intervention, PROJECT_ROOT)
    stats_path = PROJECT_ROOT / "data" / "summary" / f"{intervention}.json"
    if not stats_path.exists():
        stats_path = PROJECT_ROOT / "data" / "summary" / f"{intervention.lower()}.json"
    if not doc_path or not doc_path.exists():
        return {"error": "no_corpus", "message": f"No corpus for {intervention}"}

    corpus_path = str(doc_path.resolve())
    stats_path_str = str(stats_path.resolve()) if stats_path.exists() else str(stats_path)
    schema_path = str(_schema_path().resolve())
    rubric_path = _rubric_path("gap_analysis_rubric.txt")
    if not rubric_path.exists():
        return {"error": "no_rubric", "message": "tasks/gap_analysis_rubric.txt not found"}
    rubric_text = rubric_path.read_text(encoding="utf-8")

    out_dir = _output_dir()
    context_path = str((out_dir / f"{intervention}_gap.json").resolve())
    report_out = str((out_dir / f"{intervention}_gap.md").resolve())

    hf_token = os.getenv("HF_TOKEN")
    device = "cuda" if _cuda_available() else "cpu"
    agent_cfg = AgentConfig(
        min_fetch_docs=20,
        auto_fetch_per_search=3,
        min_per_source=2,
        max_steps=14,
        max_new_tokens=900,
        max_schema_chars=12000,
        explore_first=True,
        default_blocklist=("social", "news"),
    )

    analyzer = GapAnalyzer(
        hf_token=hf_token,
        device=device,
        model="google/medgemma-1.5-4b-it",
        cfg=GapAnalysisConfig(
            max_new_tokens=900,
            report_max_new_tokens=4096,
            max_schema_chars=12000,
        ),
    )

    ctx = analyzer.analyze_from_paths(
        corpus_path=corpus_path,
        stats_path=stats_path_str,
        schema_path=schema_path,
        rubric_text=rubric_text,
        agent_cfg=agent_cfg,
        context_path=context_path,
        report_out_path=report_out,
        report_max_docs=24,
        report_max_text_chars=1200,
        generate_report=True,
    )

    final = ctx.get("final_output", {})
    analysis = ctx.get("analysis_report") or {}
    gaps = final.get("gaps", [])
    summary_parts = [
        f"Evidence map: {final.get('evidence_map', {})}. ",
        f"Gaps: {len(gaps)} items.",
    ]
    for g in gaps[:5]:
        summary_parts.append(f" {g.get('key')}: {g.get('status')} ({g.get('severity')}).")
    if analysis.get("preview"):
        summary_parts.append(f" Report preview: {analysis['preview'][:400]}...")
    return {
        "final_output": final,
        "analysis_report": analysis,
        "summary": " ".join(summary_parts),
    }


async def gap_analyst_node(state: ReportPipelineState) -> ReportPipelineState:
    """Run gap analysis (same as run_medgemma_gap_analysis.py) and produce short missingness report."""
    intervention = state.get("intervention")
    errors = list(state.get("errors") or [])

    if not intervention:
        return {**state, "errors": errors + ["Gap Analyst: no intervention."]}

    try:
        result = await asyncio.to_thread(_run_gap_analyst_sync, intervention)
    except Exception as e:
        logger.exception("Gap Analyst failed")
        result = {"error": str(e), "summary": f"Gap analysis failed: {e}"}
        errors.append(f"Gap Analyst: {e}")

    if "error" in result and "final_output" not in result:
        return {
            **state,
            "gap_analyst_output": result,
            "gap_analyst_summary": result.get("summary", result.get("message", str(result))),
            "errors": errors,
        }

    return {
        **state,
        "gap_analyst_output": result,
        "gap_analyst_summary": result.get("summary", json.dumps(result.get("final_output", {}))),
        "errors": errors,
    }


# ─── Social Media Expert ────────────────────────────────────────────────────
async def social_media_expert_node(state: ReportPipelineState) -> ReportPipelineState:
    """Score social hype: Reddit from documents/{intervention}.json, trends from trends/{intervention}.json."""
    intervention = state.get("intervention")
    errors = list(state.get("errors") or [])

    if not intervention:
        return {**state, "errors": errors + ["Social Media Expert: no intervention."]}

    try:
        result = score_social_hype(intervention, PROJECT_ROOT)
    except Exception as e:
        logger.exception("Social Media Expert failed")
        result = {"error": str(e), "summary": str(e), "hype_score": 0}
        errors.append(f"Social Media Expert: {e}")

    summary = result.get("summary", f"Hype score: {result.get('hype_score', 0)}. {result.get('reddit_count', 0)} Reddit entries.")
    return {
        **state,
        "social_media_expert_output": result,
        "social_media_expert_summary": summary,
        "errors": errors,
    }


# ─── Analysts (parallel: Researcher Classifier | Gap Analyst | Social Media Expert) ─────
async def analysts_node(state: ReportPipelineState) -> ReportPipelineState:
    """Run Researcher Classifier, Gap Analyst, and Social Media Expert in parallel, then merge state."""
    results = await asyncio.gather(
        researcher_classifier_node(state),
        gap_analyst_node(state),
        social_media_expert_node(state),
    )
    merged: ReportPipelineState = {**state}
    for r in results:
        merged.update(r)
    # Merge errors from all three (each may have appended)
    base = list(state.get("errors") or [])
    for r in results:
        for e in r.get("errors") or []:
            if e not in base:
                base.append(e)
    merged["errors"] = base
    return merged


# ─── Judge ───────────────────────────────────────────────────────────────────
def _is_retryable_gemini_error(e: Exception) -> bool:
    """True if error is 429 / quota exhausted or other retryable."""
    msg = str(e).upper()
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "QUOTA" in msg or "RATE" in msg:
        return True
    return False


def _parse_retry_seconds(e: Exception) -> float:
    """Parse 'Please retry in Xs' from error message; default 50s."""
    import re
    msg = str(e)
    m = re.search(r"retry\s+in\s+([\d.]+)\s*s", msg, re.IGNORECASE)
    if m:
        try:
            return min(120.0, max(10.0, float(m.group(1))))
        except ValueError:
            pass
    return 50.0


def _gemini_generate(prompt: str, model: str | None = None, max_retries: int = 3) -> str:
    """Sync Gemini call for Judge and Reporter. Retries on 429 (quota) with backoff."""
    import time

    model_name = model or settings.gemini_model or "gemini-2.0-flash"
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            import google.genai as genai
            client = genai.Client(api_key=settings.gemini_api_key or os.getenv("GOOGLE_API_KEY") or "")
            result = client.models.generate_content(model=model_name, contents=[prompt])
            parts = []
            for c in getattr(result, "candidates", []) or []:
                content = getattr(c, "content", None)
                if not content:
                    continue
                for p in getattr(content, "parts", []) or []:
                    if hasattr(p, "text"):
                        parts.append(p.text)
            return "\n".join(parts) if parts else ""
        except Exception as e:
            last_error = e
            if _is_retryable_gemini_error(e) and attempt < max_retries:
                wait = _parse_retry_seconds(e)
                logger.warning("Gemini quota/rate limit (429), retrying in %.0fs (attempt %d/%d): %s", wait, attempt + 1, max_retries + 1, str(e)[:200])
                time.sleep(wait)
            else:
                break

    return f"[LLM error: {last_error}]" if last_error else "[LLM error: unknown]"


async def judge_node(state: ReportPipelineState) -> ReportPipelineState:
    """Evaluate quality of Researcher Classifier, Gap Analyst, Social Media Expert outputs. Be extremely critical."""
    package = prepare_evaluation_package(
        state.get("researcher_classifier_output") or {},
        state.get("gap_analyst_output") or {},
        state.get("social_media_expert_output") or {},
    )
    prompt = f"""You are a critical quality Judge for an evidence-reporting pipeline.

Below are the outputs of three agents:
1) Researcher Classifier (evidence confidence score and classification)
2) Gap Analyst (evidence gap analysis and missingness)
3) Social Media Expert (social hype score from Reddit and Google Trends)

Your task: produce a SHORT, EXTREMELY CRITICAL quality report. You MUST:
- Point out every weakness, missing justification, and risk of over-interpretation.
- Flag any inconsistency between confidence score and gap/missingness.
- Criticise hype vs evidence mismatch.
- Note limitations of data (e.g. corpus size, source coverage).
- Be concise but harsh: 1–2 pages of limitations and quality concerns.

Do NOT praise. Focus only on limitations and what could be wrong or misleading.

OUTPUT FORMAT: Plain text or Markdown. Start with "## Judge: Limitations and Quality Concerns".

INPUTS:
{package}
"""
    out = await asyncio.to_thread(_gemini_generate, prompt)
    return {
        **state,
        "judge_output": out or "[Judge produced no output.]",
        "errors": state.get("errors") or [],
    }


# ─── Reporter ───────────────────────────────────────────────────────────────
async def reporter_node(state: ReportPipelineState) -> ReportPipelineState:
    """Write final report: summaries (Classifier, Gap, Social), Judge limitations, recommendations. Export PDF. Thank user."""
    intervention = state.get("intervention") or "Unknown"
    s1 = state.get("researcher_classifier_summary") or ""
    s2 = state.get("gap_analyst_summary") or ""
    s3 = state.get("social_media_expert_summary") or ""
    judge = state.get("judge_output") or ""

    prompt = f"""You are writing the final evidence report for the intervention: {intervention}.

Include these sections in order:

1) EXECUTIVE SUMMARY (2–4 bullets): Summarise the key findings from:
   - Researcher Classifier: {s1[:800]}
   - Gap Analyst: {s2[:800]}
   - Social Media Expert: {s3[:800]}

2) LIMITATIONS (from the Judge): Present the Judge's critical assessment as "Limitations and caveats". Use:
   {judge[:3000]}

3) FUTURE RECOMMENDATIONS: 3–5 concise, actionable recommendations (e.g. what studies or data would strengthen the evidence, what to monitor).

4) CLOSING: Thank the user for their interest and wish them a good day and a good life. Be warm and brief.

Output ONLY the report text (no meta-commentary). Use clear headings: ## Executive Summary, ## Limitations and caveats, ## Future recommendations, ## Thank you.
"""
    report_text = await asyncio.to_thread(_gemini_generate, prompt)
    if not report_text:
        report_text = "Report generation failed. Please check inputs and try again."

    out_dir = _output_dir()
    pdf_name = f"report_{intervention.replace(' ', '_')}.pdf"
    pdf_path = out_dir / pdf_name
    written_path = ""

    try:
        written_path = await asyncio.to_thread(_write_pdf, report_text, intervention, str(pdf_path.resolve()))
    except Exception as e:
        logger.exception("PDF write failed")
        report_text += f"\n\n[PDF export failed: {e}. Report saved as text above.]"

    return {
        **state,
        "report_text": report_text,
        "pdf_path": written_path,
        "errors": state.get("errors") or [],
    }


def _write_pdf(report_text: str, intervention: str, pdf_path: str) -> str:
    """Generate a structured, user-friendly PDF from report text. Returns the path written (PDF or HTML fallback)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        html_path = pdf_path.replace(".pdf", ".html")
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Report: {intervention}</title></head><body><pre>{report_text}</pre></body></html>"""
        Path(html_path).write_text(html, encoding="utf-8")
        logger.warning("reportlab not installed. Report saved as %s (open in browser and Print to PDF).", html_path)
        return html_path

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    story = []
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )
    story.append(Paragraph(f"Evidence Report: {intervention}", title_style))
    story.append(Spacer(1, 0.2 * inch))

    for block in report_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("##"):
            first_line, _, rest = block.partition("\n")
            story.append(Paragraph(first_line.replace("##", "<b>").strip() + "</b>", styles["Heading2"]))
            if rest:
                story.append(Paragraph(rest.replace("\n", "<br/>"), styles["Normal"]))
        else:
            story.append(Paragraph(block.replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Thank you for using this report. We wish you a good day and a good life.", styles["Normal"]))
    doc.build(story)
    return pdf_path


# ─── Graph build ────────────────────────────────────────────────────────────
def build_report_pipeline():
    """Build the multi-agent report graph: Retriever → (Classifier | Gap | Social) parallel → Judge → Reporter."""
    builder = StateGraph(ReportPipelineState)

    builder.add_node("retriever", retriever_node)
    builder.add_node("analysts", analysts_node)
    builder.add_node("judge", judge_node)
    builder.add_node("reporter", reporter_node)

    builder.add_edge(START, "retriever")

    def after_retriever(state: ReportPipelineState) -> str:
        if state.get("intervention") and not state.get("retriever_error"):
            return "analysts"
        return "end"

    builder.add_conditional_edges("retriever", after_retriever, {"analysts": "analysts", "end": END})

    builder.add_edge("analysts", "judge")
    builder.add_edge("judge", "reporter")
    builder.add_edge("reporter", END)

    return builder.compile()


report_pipeline = build_report_pipeline()
