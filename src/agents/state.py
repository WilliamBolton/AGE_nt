"""State schema for the evidence-grading LangGraph pipeline.

All nodes read/write this shared state. The pipeline produces a structured
evidence report with a transparent confidence score.
"""

from __future__ import annotations

from typing import TypedDict


class EvidencePipelineState(TypedDict, total=False):
    """Shared state for the agentic evidence-grading pipeline."""

    # Input
    intervention: str
    aliases: list[str]

    # Query expansion (LLM-generated search terms)
    query_expansion_done: bool
    query_expansion_summary: str

    # Ingest
    documents_count: int
    documents_summary: str  # Short summary for the reporter (e.g. top titles/sources)
    sources_used: list[str]
    ingest_errors: list[str]

    # Classification (evidence_level, study_type, organism, etc.)
    classification_done: bool
    unclassified_count: int

    # Reasoning outputs (stub or real modules)
    evidence_summary: str  # Level counts, weights, composite score
    trajectory_summary: str  # Temporal momentum, phase
    gaps_summary: str  # Missing evidence types, warnings

    # Final report
    report: str  # Human-readable structured report
    confidence_score: float  # 0–100, calibrated
    confidence_reasoning: str  # Transparent explanation

    # Errors (non-fatal) collected along the pipeline
    errors: list[str]
