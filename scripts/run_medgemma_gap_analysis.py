# run_medgemma_gap_analysis.py

# TO RUN FROM ROOT
#
# python scripts/run_medgemma_gap_analysis.py \
#     --intervention rapamycin \
#     --schema JSON_SCHEMA_REFERENCE.md \
#     --rubric tasks/gap_analysis_rubric.txt \
#     --out-dir outputs \
#     --device cuda \
#

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure project root is importable when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.gap_analysis import GapAnalyzer, GapAnalysisConfig
from src.tools.json_corpus_query_tool import AgentConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MedGemma + JSON query tool to produce gap analysis JSON")
    parser.add_argument(
        "--intervention",
        required=True,
        help="Intervention name used to derive corpus/stats paths (e.g. 'rapamycin', 'taurine')",
    )
    parser.add_argument("--schema", default="JSON_SCHEMA_REFERENCE.md")
    parser.add_argument("--rubric", required=True, help="Path to gap analysis rubric.txt")
    parser.add_argument(
        "--out-dir",
        default="outputs",
        help="Directory where <intervention>_gap.json and <intervention>_gap.md will be written",
    )
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--model", default="google/medgemma-1.5-4b-it")

    # knobs (query tool)
    parser.add_argument("--min-fetch-docs", type=int, default=20)
    parser.add_argument("--auto-fetch-per-search", type=int, default=3)
    parser.add_argument("--min-per-source", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=14)
    parser.add_argument("--max-new-tokens", type=int, default=900)
    parser.add_argument("--report-max-new-tokens", type=int, default=4096)
    parser.add_argument("--max-schema-chars", type=int, default=12000)
    parser.add_argument("--report-out", default=None, help="Optional Markdown analysis report path")
    parser.add_argument("--report-max-docs", type=int, default=24)
    parser.add_argument("--report-max-text-chars", type=int, default=1200)
    parser.add_argument("--no-report", action="store_true", help="Disable LLM narrative report generation")

    args = parser.parse_args()

    corpus_path = f"data/documents/{args.intervention}.json"
    stats_path = f"data/summary/{args.intervention}.json"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    context_path = out_dir / f"{args.intervention}_gap.json"

    rubric_text = Path(args.rubric).read_text(encoding="utf-8")
    report_out = args.report_out
    if not args.no_report and not report_out:
        report_out = str(out_dir / f"{args.intervention}_gap.md")

    cfg = AgentConfig(
        min_fetch_docs=args.min_fetch_docs,
        auto_fetch_per_search=args.auto_fetch_per_search,
        min_per_source=args.min_per_source,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        max_schema_chars=args.max_schema_chars,
        explore_first=True,
        default_blocklist=("social", "news"),
    )

    analyzer = GapAnalyzer(
        hf_token=args.hf_token,
        device=args.device,
        model=args.model,
        cfg=GapAnalysisConfig(
            max_new_tokens=args.max_new_tokens,
            report_max_new_tokens=args.report_max_new_tokens,
            max_schema_chars=args.max_schema_chars,
        ),
    )

    ctx = analyzer.analyze_from_paths(
        corpus_path=corpus_path,
        stats_path=stats_path,
        schema_path=args.schema,
        agent_cfg=cfg,
        rubric_text=rubric_text,
        context_path=str(context_path),
        report_out_path=report_out,
        report_max_docs=args.report_max_docs,
        report_max_text_chars=args.report_max_text_chars,
        generate_report=not args.no_report,
    )

    print(json.dumps(ctx.get("final_output", {}), indent=2, ensure_ascii=False))
    print(f"\nWrote context to: {context_path}")
    report_meta = ctx.get("analysis_report") or {}
    if report_meta.get("path"):
        print(f"Wrote analysis report to: {report_meta['path']}")


if __name__ == "__main__":
    main()
