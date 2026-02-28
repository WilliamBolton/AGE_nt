"""Run from repo root:  python -m src.main   or   python src/main.py

Interactive mode: you will be prompted for a query (e.g. intervention name). Run again or exit.
"""
import sys
from pathlib import Path

# Ensure project root is on path so "src" can be imported
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.config import *  # noqa: F401, F403
from src.agents.agent import bio_pipeline
from src.agents.evidence_pipeline import evidence_pipeline
from src.agents.report_graph import report_pipeline
import asyncio


async def run_report_pipeline_once(user_query: str):
    """Run the report pipeline for one query and print results."""
    initial = {"user_query": user_query.strip(), "errors": []}
    result = await report_pipeline.ainvoke(initial)
    if result.get("retriever_error"):
        print("Retriever:", result["retriever_error"])
        return result
    print("Intervention:", result.get("intervention"))
    print("\n--- Researcher Classifier ---")
    print((result.get("researcher_classifier_summary") or "")[:500], "..." if len(result.get("researcher_classifier_summary") or "") > 500 else "")
    print("\n--- Gap Analyst ---")
    print((result.get("gap_analyst_summary") or "")[:500], "..." if len(result.get("gap_analyst_summary") or "") > 500 else "")
    print("\n--- Social Media Expert ---")
    print((result.get("social_media_expert_summary") or "")[:500], "..." if len(result.get("social_media_expert_summary") or "") > 500 else "")
    print("\n--- Judge (limitations) ---")
    print((result.get("judge_output") or "")[:800], "..." if len(result.get("judge_output") or "") > 800 else "")
    print("\n--- Report (excerpt) ---")
    print((result.get("report_text") or "")[:800], "..." if len(result.get("report_text") or "") > 800 else "")
    print("\nPDF path:", result.get("pdf_path", ""))
    if result.get("errors"):
        print("Errors:", result["errors"])
    return result


async def run_report_pipeline():
    """Multi-agent report: Retriever → (Classifier | Gap | Social) → Judge → Reporter (PDF). One fixed query."""
    print("--- Multi-Agent Report Pipeline ---\n")
    await run_report_pipeline_once("rapamycin for longevity")


def _prompt(prompt: str, default: str = "") -> str:
    """Read a line from stdin; return default if empty."""
    try:
        line = input(prompt).strip()
        return line if line else default
    except (EOFError, KeyboardInterrupt):
        return ""


async def run_report_pipeline_interactive():
    """Interactive loop: prompt for query, run pipeline, show results, repeat or exit."""
    print("--- Multi-Agent Report Pipeline (interactive) ---")
    print("Enter an intervention or question (e.g. metformin, rapamycin for longevity).")
    print("Leave empty or Ctrl+C to exit.\n")

    while True:
        query = _prompt("Query> ", default="")
        if not query:
            print("Bye.")
            break
        print()
        await run_report_pipeline_once(query)
        print()


async def run_bio_pipeline():
    """Original simple pipeline: PubMed search → Gemini summary."""
    print("--- LangGraph BioPipeline (PubMed → Analyst)\n")
    user_query = "metformin for aging intervention"
    result = await bio_pipeline.ainvoke({"query": user_query})
    print("Raw findings:\n", result.get("raw_findings", ""))
    print("\nAnalysis:\n", result.get("analysis", ""))


async def run_evidence_pipeline():
    """Full evidence pipeline: expand → ingest → classify → grade → trajectory → gaps → report."""
    print("--- LangGraph Evidence Pipeline (intervention → report)\n")
    initial = {
        "intervention": "rapamycin",
        "aliases": ["sirolimus", "rapa"],
    }
    result = await evidence_pipeline.ainvoke(initial)
    print("Documents:", result.get("documents_count", 0))
    print("Sources:", result.get("sources_used", []))
    print("\nEvidence summary:", result.get("evidence_summary", "")[:500], "...")
    print("\nTrajectory:", result.get("trajectory_summary", "")[:300], "...")
    print("\nGaps:", result.get("gaps_summary", "")[:300], "...")
    print("\n--- REPORT ---\n", result.get("report", ""))
    print("\n--- CONFIDENCE ---")
    print("Score:", result.get("confidence_score"))
    print("Reasoning:", result.get("confidence_reasoning", ""))


async def main():
    # Interactive: prompt for query, run report pipeline, repeat or exit (no command-line)
    # await run_report_pipeline_interactive()
    await run_report_pipeline()

    # One-shot with fixed query (no prompts):
    # await run_report_pipeline()

    # Other pipelines:
    # await run_evidence_pipeline()
    # await run_bio_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
