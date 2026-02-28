"""Run from repo root:  python -m src.main   or   python src/main.py
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
import asyncio


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
    # Run the full evidence pipeline (ingest + reasoning stubs + report)
    await run_evidence_pipeline()

    # Uncomment to run the simple bio pipeline instead:
    # await run_bio_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
