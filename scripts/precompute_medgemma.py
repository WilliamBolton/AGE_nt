#!/usr/bin/env python3
"""Pre-compute MedGemma analysis outputs for all interventions.

Runs the MedGemma-powered evidence grader, gap analysis, and hype ratio
tools offline and caches results to data/analysis/{tool}_medgemma/ so
they're served instantly at runtime.

Usage:
    # Single tool, single intervention
    uv run python scripts/precompute_medgemma.py --tool evidence --intervention rapamycin

    # All tools for one intervention
    uv run python scripts/precompute_medgemma.py --tool all --intervention rapamycin

    # All tools for all interventions (overnight job)
    uv run python scripts/precompute_medgemma.py --tool all --intervention all

    # Specify GPU device and model
    uv run python scripts/precompute_medgemma.py --tool gaps --intervention metformin --device cuda:0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
ANALYSIS_DIR = DATA_DIR / "analysis"
SCHEMA_PATH = str(PROJECT_ROOT / "JSON_SCHEMA_REFERENCE.md")


def get_all_interventions() -> list[str]:
    """Get all intervention names that have document data."""
    docs_dir = DATA_DIR / "documents"
    if not docs_dir.exists():
        return []
    return sorted(
        p.stem for p in docs_dir.glob("*.json")
        if p.stat().st_size > 100  # skip empty files
    )


def output_path(tool: str, intervention: str) -> Path:
    return ANALYSIS_DIR / f"{tool}_medgemma" / f"{intervention}.json"


def already_computed(tool: str, intervention: str) -> bool:
    return output_path(tool, intervention).exists()


def save_result(tool: str, intervention: str, context: dict) -> Path:
    path = output_path(tool, intervention)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, indent=2, default=str, ensure_ascii=False))
    return path


def run_evidence(
    intervention: str,
    *,
    hf_token: str | None,
    device: str,
    model: str,
    schema_path: str,
) -> dict | None:
    """Run MedGemma evidence grading for one intervention."""
    from src.tools.evidence_grader import (
        EvidenceGrader,
        EvidenceGraderConfig,
        EvidenceRetrievalConfig,
    )

    corpus_path = f"data/documents/{intervention}.json"
    stats_path = f"data/summary/{intervention}.json"
    if not Path(corpus_path).exists() or not Path(stats_path).exists():
        print(f"  Skipping {intervention}: missing corpus or stats file")
        return None

    rubric_path = PROJECT_ROOT / "tasks" / "confidence_rubric.txt"
    if not rubric_path.exists():
        print(f"  Skipping evidence: missing {rubric_path}")
        return None
    rubric_text = rubric_path.read_text(encoding="utf-8")

    grader = EvidenceGrader(
        hf_token=hf_token,
        device=device,
        model=model,
        cfg=EvidenceGraderConfig(scoring_mode="llm_then_fallback"),
    )
    context_out = str(output_path("evidence", intervention))
    ctx = grader.grade_with_corpus(
        corpus_path=corpus_path,
        stats_path=stats_path,
        schema_path=schema_path,
        rubric_text=rubric_text,
        retrieval_cfg=EvidenceRetrievalConfig(),
        context_path=context_out,
        generate_report=False,
    )
    return ctx


def run_gaps(
    intervention: str,
    *,
    hf_token: str | None,
    device: str,
    model: str,
    schema_path: str,
) -> dict | None:
    """Run MedGemma gap analysis for one intervention."""
    from src.tools.gap_analysis import GapAnalyzer, GapAnalysisConfig
    from src.tools.json_corpus_query_tool import AgentConfig

    corpus_path = f"data/documents/{intervention}.json"
    stats_path = f"data/summary/{intervention}.json"
    if not Path(corpus_path).exists() or not Path(stats_path).exists():
        print(f"  Skipping {intervention}: missing corpus or stats file")
        return None

    rubric_path = PROJECT_ROOT / "tasks" / "gap_analysis_rubric.txt"
    if not rubric_path.exists():
        print(f"  Skipping gaps: missing {rubric_path}")
        return None
    rubric_text = rubric_path.read_text(encoding="utf-8")

    analyzer = GapAnalyzer(
        hf_token=hf_token,
        device=device,
        model=model,
        cfg=GapAnalysisConfig(),
    )
    context_out = str(output_path("gaps", intervention))
    ctx = analyzer.analyze_from_paths(
        corpus_path=corpus_path,
        stats_path=stats_path,
        schema_path=schema_path,
        agent_cfg=AgentConfig(),
        rubric_text=rubric_text,
        context_path=context_out,
        generate_report=False,
    )
    return ctx


def run_hype(
    intervention: str,
    *,
    hf_token: str | None,
    device: str,
    model: str,
    schema_path: str,
) -> dict | None:
    """Run MedGemma hype ratio analysis for one intervention."""
    from src.tools.hype_ratio import HypeRatioAnalyzer, HypeRatioConfig
    from src.tools.json_corpus_query_tool import AgentConfig

    corpus_path = f"data/documents/{intervention}.json"
    stats_path = f"data/summary/{intervention}.json"
    if not Path(corpus_path).exists() or not Path(stats_path).exists():
        print(f"  Skipping {intervention}: missing corpus or stats file")
        return None

    rubric_path = PROJECT_ROOT / "tasks" / "hype_ratio_rubric.txt"
    if not rubric_path.exists():
        print(f"  Skipping hype: missing {rubric_path}")
        return None
    rubric_text = rubric_path.read_text(encoding="utf-8")

    analyzer = HypeRatioAnalyzer(
        hf_token=hf_token,
        device=device,
        model=model,
        cfg=HypeRatioConfig(),
    )
    context_out = str(output_path("hype", intervention))
    ctx = analyzer.analyze_from_paths(
        intervention=intervention,
        corpus_path=corpus_path,
        stats_path=stats_path,
        schema_path=schema_path,
        rubric_text=rubric_text,
        agent_cfg=AgentConfig(default_blocklist=()),
        context_path=context_out,
        generate_report=False,
    )
    return ctx


TOOL_RUNNERS = {
    "evidence": run_evidence,
    "gaps": run_gaps,
    "hype": run_hype,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-compute MedGemma analysis and cache for runtime use"
    )
    parser.add_argument(
        "--tool",
        choices=["evidence", "gaps", "hype", "all"],
        required=True,
        help="Which tool to run",
    )
    parser.add_argument(
        "--intervention",
        default="all",
        help="Intervention name, or 'all' for every intervention with data",
    )
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--model", default="google/medgemma-1.5-4b-it")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-compute even if cached output exists",
    )
    args = parser.parse_args()

    # Determine interventions
    if args.intervention == "all":
        interventions = get_all_interventions()
        print(f"Found {len(interventions)} interventions with data")
    else:
        interventions = [args.intervention.lower().strip()]

    # Determine tools
    tools = list(TOOL_RUNNERS.keys()) if args.tool == "all" else [args.tool]

    total = len(interventions) * len(tools)
    done = 0
    skipped = 0
    failed = 0

    for intervention in interventions:
        for tool in tools:
            done += 1
            label = f"[{done}/{total}] {tool}/{intervention}"

            if not args.force and already_computed(tool, intervention):
                print(f"{label} — cached, skipping")
                skipped += 1
                continue

            print(f"{label} — running...")
            runner = TOOL_RUNNERS[tool]
            try:
                ctx = runner(
                    intervention,
                    hf_token=args.hf_token,
                    device=args.device,
                    model=args.model,
                    schema_path=SCHEMA_PATH,
                )
                if ctx is not None:
                    path = save_result(tool, intervention, ctx)
                    print(f"  → saved to {path}")
                else:
                    skipped += 1
            except Exception as e:
                print(f"  ✗ FAILED: {e}")
                failed += 1

    print(f"\nDone: {done} tasks, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
