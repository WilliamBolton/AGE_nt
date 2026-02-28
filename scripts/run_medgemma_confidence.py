# run_medgemma_confidence.py

# TO RUN FROM ROOT

# python scripts/run_medgemma_confidence.py       \
#     --corpus data/documents/rapamycin.json      \
#     --stats data/summary/rapamycin.json         \
#     --schema JSON_SCHEMA_REFERENCE.md           \
#     --rubric tasks/confidence_rubric.txt        \ 
#     --context-out outputs/rapa_ctx.json         \
#     --device cuda                               \
#     --scoring-mode deterministic_only           \

# python scripts/run_medgemma_confidence.py       \
#     --corpus data/documents/rapamycin.json      \
#     --stats data/summary/rapamycin.json         \
#     --schema JSON_SCHEMA_REFERENCE.md           \
#     --rubric tasks/confidence_rubric_clinical_trials.txt        \ 
#     --context-out outputs/rapa_ctx_clinical_trials_only.json         \
#     --device cuda                               \
#     --scoring-mode deterministic_only           \

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure project root (`AGE_nt`) is importable when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.evidence_grader import EvidenceGrader, EvidenceGraderConfig
from src.tools.json_corpus_query_tool import AgentConfig, JsonCorpusQueryTool


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MedGemma + JSON query tool to produce confidence score JSON")
    parser.add_argument("--corpus", default="data/documents/rapamycin.json")
    parser.add_argument("--stats", default="data/summary/rapamycin.json")
    parser.add_argument("--schema", default="JSON_SCHEMA_REFERENCE.md")
    parser.add_argument("--rubric", required=True, help="Path to rubric.txt")
    parser.add_argument("--context-out", default="./agent_context.json", help="Persist agent state here (optional)")
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--model", default="google/medgemma-1.5-4b-it")

    # knobs
    parser.add_argument("--min-fetch-docs", type=int, default=20)
    parser.add_argument("--auto-fetch-per-search", type=int, default=3)
    parser.add_argument("--min-per-source", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=14)
    parser.add_argument("--max-new-tokens", type=int, default=900)
    parser.add_argument("--report-max-new-tokens", type=int, default=4096)
    parser.add_argument("--max-schema-chars", type=int, default=12000)
    parser.add_argument("--report-out", default=None, help="Optional Markdown analysis report path")
    parser.add_argument("--report-max-docs", type=int, default=20)
    parser.add_argument("--report-max-text-chars", type=int, default=1200)
    parser.add_argument("--no-report", action="store_true", help="Disable LLM narrative report generation")
    parser.add_argument(
        "--scoring-mode",
        default="deterministic_only",
        choices=("deterministic_only", "llm_then_fallback", "llm_only"),
        help="Final scoring mode",
    )

    args = parser.parse_args()
    rubric_text = Path(args.rubric).read_text(encoding="utf-8")
    report_out = args.report_out
    if not args.no_report and not report_out:
        context_path = Path(args.context_out)
        if context_path.suffix.lower() == ".json":
            report_out = str(context_path.with_suffix(".md"))
        else:
            report_out = args.context_out + ".md"

    cfg = AgentConfig(
        min_fetch_docs=args.min_fetch_docs,
        auto_fetch_per_search=args.auto_fetch_per_search,
        min_per_source=args.min_per_source,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        max_schema_chars=args.max_schema_chars,
        explore_first=True,
        # default behaviour: ignore news/social unless rubric explicitly needs it
        default_blocklist=("social", "news"),
    )

    query_tool = JsonCorpusQueryTool(
        corpus_path=args.corpus,
        stats_path=args.stats,
        schema_path=args.schema,
        hf_token=args.hf_token,
        device=args.device,
        model=args.model,
        cfg=cfg,
    )

    grader = EvidenceGrader(
        hf_token=args.hf_token,
        device=args.device,
        model=args.model,
        cfg=EvidenceGraderConfig(
            max_new_tokens=args.max_new_tokens,
            report_max_new_tokens=args.report_max_new_tokens,
            scoring_mode=args.scoring_mode,
        ),
    )

    ctx = grader.grade_with_query_tool(
        query_tool=query_tool,
        rubric_text=rubric_text,
        context_path=args.context_out,
        report_out_path=report_out,
        report_max_docs=args.report_max_docs,
        report_max_text_chars=args.report_max_text_chars,
        generate_report=not args.no_report,
    )
    print(json.dumps(ctx.get("final_output", {}), indent=2, ensure_ascii=False))
    print(f"\nWrote context to: {args.context_out}")
    report_meta = ctx.get("analysis_report") or {}
    if report_meta.get("path"):
        print(f"Wrote analysis report to: {report_meta['path']}")


if __name__ == "__main__":
    main()
