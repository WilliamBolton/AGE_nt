
# run_medgemma_hype_ratio.py
#
# Minimal run:
#   python scripts/run_medgemma_hype_ratio.py \
#       --intervention rapamycin \
#       --rubric tasks/hype_ratio_rubric.txt \
#       --out-dir outputs
#
# With precomputed confidence context:
#   python scripts/run_medgemma_hype_ratio.py \
#       --intervention rapamycin \
#       --rubric tasks/hype_ratio_rubric.txt \
#       --confidence-context outputs/rapamycin.json \
#       --out-dir outputs
#
# Compute confidence inline for calibration:
#   python scripts/run_medgemma_hype_ratio.py \
#       --intervention rapamycin \
#       --rubric tasks/hype_ratio_rubric.txt \
#       --confidence-rubric tasks/confidence_rubric.txt \
#       --out-dir outputs
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

from src.tools.hype_ratio import HypeRatioAnalyzer, HypeRatioConfig
from src.tools.json_corpus_query_tool import AgentConfig
from src.tools.evidence_grader import EvidenceGrader, EvidenceGraderConfig, EvidenceRetrievalConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run hype analysis with optional confidence calibration (precomputed or computed)."
    )
    parser.add_argument("--intervention", required=True, help="Intervention name (e.g. 'rapamycin')")
    parser.add_argument("--schema", default="JSON_SCHEMA_REFERENCE.md")
    parser.add_argument("--rubric", required=True, help="Path to hype_ratio_rubric.txt")
    parser.add_argument("--out-dir", default="outputs", help="Directory where outputs will be written")

    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--model", default="google/medgemma-1.5-4b-it")

    # query knobs (optional)
    parser.add_argument("--min-fetch-docs", type=int, default=40)
    parser.add_argument("--auto-fetch-per-search", type=int, default=4)
    parser.add_argument("--min-per-source", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-new-tokens", type=int, default=900)
    parser.add_argument("--report-max-new-tokens", type=int, default=4096)
    parser.add_argument("--max-schema-chars", type=int, default=12000)

    parser.add_argument("--no-report", action="store_true", help="Disable narrative report generation")
    parser.add_argument("--report-out", default=None, help="Optional Markdown report path")
    parser.add_argument("--context-out", default=None, help="Optional JSON context path")
    parser.add_argument("--report-max-docs", type=int, default=24)
    parser.add_argument("--report-max-text-chars", type=int, default=1200)
    parser.add_argument(
        "--confidence-context",
        default=None,
        help="Path to precomputed confidence JSON (expects final_output.confidence or confidence).",
    )
    parser.add_argument(
        "--confidence-rubric",
        default=None,
        help="If set and --confidence-context not provided, compute confidence score with this rubric path.",
    )
    parser.add_argument(
        "--confidence-context-out",
        default=None,
        help="Where to save computed confidence context when --confidence-rubric is used.",
    )
    parser.add_argument(
        "--confidence-scoring-mode",
        default="deterministic_only",
        choices=("deterministic_only", "llm_then_fallback", "llm_only"),
        help="Scoring mode for computed confidence runs.",
    )

    args = parser.parse_args()

    # Derive paths from intervention
    corpus_path = f"data/documents/{args.intervention}.json"
    stats_path = f"data/summary/{args.intervention}.json"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    context_path = args.context_out
    if not context_path:
        context_path = str(out_dir / f"{args.intervention}_hype_ratio.json")

    report_out = args.report_out
    if (not args.no_report) and not report_out:
        report_out = str(out_dir / f"{args.intervention}_hype_ratio.md")

    rubric_text = Path(args.rubric).read_text(encoding="utf-8")

    agent_cfg = AgentConfig(
        min_fetch_docs=args.min_fetch_docs,
        auto_fetch_per_search=args.auto_fetch_per_search,
        min_per_source=args.min_per_source,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        max_schema_chars=args.max_schema_chars,
        explore_first=True,
        default_blocklist=(),  # allow social/news if rubric requests them
    )

    analyzer = HypeRatioAnalyzer(
        hf_token=args.hf_token,
        device=args.device,
        model=args.model,
        cfg=HypeRatioConfig(
            max_new_tokens=args.max_new_tokens,
            report_max_new_tokens=args.report_max_new_tokens,
            max_schema_chars=args.max_schema_chars,
        ),
    )

    confidence_context: dict | None = None
    confidence_source = "not_provided"
    if args.confidence_context:
        confidence_context = json.loads(Path(args.confidence_context).read_text(encoding="utf-8"))
        confidence_source = f"precomputed:{args.confidence_context}"
    elif args.confidence_rubric:
        confidence_rubric_text = Path(args.confidence_rubric).read_text(encoding="utf-8")
        confidence_context_out = args.confidence_context_out
        if not confidence_context_out:
            confidence_context_out = str(out_dir / f"{args.intervention}_confidence_for_hype.json")

        grader = EvidenceGrader(
            hf_token=args.hf_token,
            device=args.device,
            model=args.model,
            cfg=EvidenceGraderConfig(
                max_new_tokens=args.max_new_tokens,
                report_max_new_tokens=args.report_max_new_tokens,
                scoring_mode=args.confidence_scoring_mode,
            ),
        )
        confidence_context = grader.grade_with_corpus(
            corpus_path=corpus_path,
            stats_path=stats_path,
            schema_path=args.schema,
            rubric_text=confidence_rubric_text,
            retrieval_cfg=EvidenceRetrievalConfig(
                min_fetch_docs=20,
                auto_fetch_per_search=3,
                min_per_source=2,
                max_steps=max(10, args.max_steps),
                max_new_tokens=args.max_new_tokens,
                max_schema_chars=args.max_schema_chars,
                explore_first=True,
                default_blocklist=("social", "news"),
            ),
            context_path=confidence_context_out,
            generate_report=False,
        )
        confidence_source = f"computed:{args.confidence_rubric}"

    context = analyzer.analyze_from_paths(
        intervention=args.intervention,
        corpus_path=corpus_path,
        stats_path=stats_path,
        schema_path=args.schema,
        rubric_text=rubric_text,
        agent_cfg=agent_cfg,
        context_path=context_path,
        report_out_path=None if args.no_report else report_out,
        generate_report=not args.no_report,
        report_max_docs=args.report_max_docs,
        report_max_text_chars=args.report_max_text_chars,
        confidence_context=confidence_context,
        confidence_source=confidence_source,
    )

    print("Hype-to-evidence ratio output:")
    fo = context.get("final_output", {})
    print(f"  hype_score_0to100: {fo.get('hype_score_0to100')}")
    print(f"  hype_to_evidence_ratio: {fo.get('hype_to_evidence_ratio')}")
    print(f"  hype_share_0to1: {fo.get('hype_share_0to1')}")
    print(f"  hype_dominance_score_0to100: {fo.get('hype_dominance_score_0to100')}")
    print(f"  confidence_source: {fo.get('confidence_source')}")
    print(f"  confidence_score_0to100: {fo.get('confidence_score_0to100')}")
    print(f"  overhype_risk_0to100: {fo.get('overhype_risk_0to100')}")
    print(f"  alignment_label: {fo.get('alignment_label')}")
    print(f"  interpretation: {fo.get('interpretation')}")
    print(f"  counts_by_source_type: {fo.get('counts_by_source_type')}")
    print(f"  evidence_breakdown: {fo.get('evidence_breakdown')}")
    print(f"  wrote context: {context_path}")
    if not args.no_report:
        print(f"  wrote report: {report_out}")


if __name__ == "__main__":
    main()
