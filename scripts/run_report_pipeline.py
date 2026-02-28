#!/usr/bin/env python3
"""
Run the multi-agent report pipeline with a user query.

Examples (from repo root):

  # Human-readable output, default query "rapamycin for longevity"
  python scripts/run_report_pipeline.py

  # Human-readable output with your query
  python scripts/run_report_pipeline.py metformin
  python scripts/run_report_pipeline.py "rapamycin for longevity"

  # JSON to stdout
  python scripts/run_report_pipeline.py --json metformin

  # JSON to a file
  python scripts/run_report_pipeline.py -o outputs/pipeline/first_run.json metformin

Requires: data/interventions.json, data/documents/<intervention>.json,
optional data/trends/<intervention>.json, tasks/confidence_rubric.txt, tasks/gap_analysis_rubric.txt.
MedGemma (evidence_grader, gap_analysis) optional if HF_TOKEN and GPU available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.report_graph import report_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-agent report pipeline (Retriever → Classifier → Gap → Social → Judge → Reporter)")
    parser.add_argument("query", nargs="?", default="rapamycin for longevity", help="User query (e.g. intervention name or question)")
    parser.add_argument("--json", action="store_true", help="Print final state as JSON to stdout")
    parser.add_argument("-o", "--output", metavar="FILE", help="Write JSON result to FILE (creates parent dirs if needed)")
    args = parser.parse_args()

    async def run() -> dict:
        initial = {"user_query": args.query.strip(), "errors": []}
        return await report_pipeline.ainvoke(initial)

    result = asyncio.run(run())

    out = {k: v for k, v in result.items() if k != "messages"}
    json_str = json.dumps(out, indent=2, default=str)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        print("Wrote JSON to", out_path, file=sys.stderr)
        if not args.json:
            # Still print a short summary to stdout
            if result.get("retriever_error"):
                print("Error:", result["retriever_error"])
                sys.exit(1)
            print("Intervention:", result.get("intervention"))
            print("PDF:", result.get("pdf_path", ""))
        return

    if args.json:
        print(json_str)
        return

    if result.get("retriever_error"):
        print("Error:", result["retriever_error"])
        sys.exit(1)
    print("Intervention:", result.get("intervention"))
    print("\n--- Researcher Classifier ---\n", result.get("researcher_classifier_summary", "")[:600])
    print("\n--- Gap Analyst ---\n", result.get("gap_analyst_summary", "")[:600])
    print("\n--- Social Media Expert ---\n", result.get("social_media_expert_summary", "")[:600])
    print("\n--- Judge (Limitations) ---\n", (result.get("judge_output") or "")[:1000])
    print("\n--- Report ---\n", (result.get("report_text") or "")[:1500])
    print("\nPDF:", result.get("pdf_path", ""))


if __name__ == "__main__":
    main()
