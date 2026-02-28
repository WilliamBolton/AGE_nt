from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
import re
from pathlib import Path
import json
from typing import Any, Callable, Literal, Optional

try:
    from .json_corpus_query_tool import (
        AgentConfig,
        JsonCorpusQueryTool,
        compact_docs_for_final,
        parse_json_obj,
        save_json,
    )
except ImportError:
    from json_corpus_query_tool import (
        AgentConfig,
        JsonCorpusQueryTool,
        compact_docs_for_final,
        parse_json_obj,
        save_json,
    )


def _safe_json_parse(text: str) -> dict[str, Any] | None:
    try:
        return parse_json_obj(text)
    except Exception:
        return None


def _strip_thought(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^<unused\d+>thought\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(?mi)<unused\d+>\s*", "", s)
    return s.strip()


def _clean_report_markdown(text: str) -> str:
    s = _strip_thought(text)
    if s.startswith("```"):
        s = re.sub(r"^```(?:markdown|md)?\s*", "", s, flags=re.IGNORECASE).rstrip()
        if s.endswith("```"):
            s = s[:-3].rstrip()

    anchors = [
        r"(?mi)#\s+Evidence Confidence Report\b",
        r"(?mi)^\s*##\s+Executive Summary\b",
        r"(?mi)^\s*1\)\s*(?:\*\*)?\s*Executive Summary\b",
    ]
    starts: list[int] = []
    for pat in anchors:
        m = re.search(pat, s)
        if m:
            starts.append(m.start())
    if starts:
        s = s[min(starts) :].lstrip()
    return s


def _is_valid_report_markdown(text: str) -> bool:
    s = _clean_report_markdown(text).lower()
    required = (
        "executive summary",
        "score breakdown",
        "limitations",
    )
    return all(r in s for r in required)


def build_evidence_pack(
    *,
    corpus: dict[str, Any],
    final_output: dict[str, Any],
    extra_doc_ids: Optional[list[str]] = None,
    max_docs: int = 20,
    max_text_chars: int = 1200,
) -> dict[str, Any]:
    by_id = {
        d.get("id"): d
        for d in (corpus.get("documents", []) or [])
        if isinstance(d, dict) and isinstance(d.get("id"), str)
    }

    doc_ids: list[str] = []
    for td in (final_output.get("top_docs") or []):
        did = td.get("id")
        if isinstance(did, str) and did in by_id:
            doc_ids.append(did)
    if extra_doc_ids:
        for did in extra_doc_ids:
            if isinstance(did, str) and did in by_id:
                doc_ids.append(did)

    seen: set[str] = set()
    ordered: list[str] = []
    for did in doc_ids:
        if did not in seen:
            ordered.append(did)
            seen.add(did)

    docs_out: list[dict[str, Any]] = []
    for did in ordered[:max_docs]:
        d = dict(by_id[did])
        for k in ("abstract", "brief_summary", "detailed_description", "results_summary"):
            if k in d and isinstance(d[k], str) and len(d[k]) > max_text_chars:
                d[k] = d[k][:max_text_chars] + "..."
        docs_out.append(d)

    return {
        "intervention": corpus.get("intervention"),
        "doc_count_in_pack": len(docs_out),
        "documents": docs_out,
    }


def build_llm_report_prompt(
    *,
    rubric_text: str,
    final_output: dict[str, Any],
    evidence_pack: dict[str, Any],
) -> str:
    return f"""
You are writing an audit-style analysis report for an evidence confidence score.

CRITICAL CONSTRAINTS
- You MUST use ONLY the provided evidence_pack documents and the provided final_output numbers.
- Do NOT use outside knowledge.
- Every factual claim about a study/trial must cite a document by its id and use fields present in evidence_pack.
- If you cannot find something in evidence_pack, say it is missing from the scraped record.
- Do NOT change any numbers in final_output.

INPUTS

RUBRIC:
{rubric_text}

FINAL OUTPUT (ground truth numbers):
{json.dumps(final_output, ensure_ascii=False)}

EVIDENCE PACK:
{json.dumps(evidence_pack, ensure_ascii=False)}

TASK
Write a report explaining why the score is what it is.

REQUIRED REPORT SECTIONS (Markdown)
Start EXACTLY with this heading:
# Evidence Confidence Report

1) Executive summary (3-6 bullets)
2) Score breakdown
3) Evidence quality and relevance diagnosis
4) Top influential documents (5-10 items)
5) Limitations of this run
6) What would raise/lower the score (actionable)

STYLE
- Be concise and specific.
- Use inline citations like (doc: <id>).
- Output Markdown only.
"""


def _text_blob(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in (
        "title",
        "abstract",
        "results_summary",
        "primary_outcomes",
        "publication_types",
        "mesh_terms",
        "conditions",
        "phase",
        "status",
        "approved_indications",
        "warnings_summary",
    ):
        v = doc.get(k)
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v if x is not None))
        elif v is not None:
            parts.append(str(v))
    return " ".join(parts).lower()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _infer_level_design(doc: dict[str, Any], text: str) -> tuple[int, str, bool]:
    """
    Evidence hierarchy aligned to confidence_score.py:
      1 = Systematic reviews & meta-analyses
      2 = Randomised controlled trials (RCTs), including phase trials
      3 = Observational / epidemiological studies (cohort, registry, case-control)
      4 = Animal model studies (in vivo)
      5 = Cell culture / in vitro studies
      6 = In silico / computational predictions
    """
    st = str(doc.get("source_type") or "").lower()
    pub_types = " ".join(str(x).lower() for x in (doc.get("publication_types") or []))
    phase = str(doc.get("phase") or "").lower()

    if st == "clinicaltrials":
        # Per rubric, phase trials are tier 2.
        return 2, "clinical_trial_registry", True

    if st == "drugage":
        return 4, "drugage_database", False

    # PubMed-like evidence typing from publication metadata/content.
    if _contains_any(text + " " + pub_types, ("meta-analysis", "meta analysis", "systematic review")):
        return 1, "meta_analysis", True
    if _contains_any(
        text + " " + pub_types,
        ("randomized", "randomised", "clinical trial", "double-blind", "placebo", "phase i", "phase ii", "phase iii", "phase iv"),
    ):
        return 2, "rct", True
    if _contains_any(text, ("cohort", "observational", "registry", "case-control", "epidemiolog")):
        return 3, "observational_human", True
    if _contains_any(text, ("mouse", "mice", "murine", "rat", "dogs", "animal model", "in vivo")):
        return 4, "animal_in_vivo", False
    if _contains_any(text, ("in vitro", "cell line", "organoid", "cell culture")):
        return 5, "in_vitro", False
    if _contains_any(text, ("in silico", "computational", "docking", "machine learning")):
        return 6, "in_silico", False

    # Non-primary-efficacy evidence sources are treated as lowest tier.
    if st == "regulatory":
        return 6, "regulatory_label", True
    if st in {"nih_grant"}:
        return 6, "grant_record", False
    if st == "patent":
        return 6, "patent", False
    if st in {"news", "social"}:
        return 6, "news_social", False

    return (3, "observational_human", True) if _contains_any(text, ("human", "patients", "older adults")) else (6, "other", False)


def _infer_relevance(text: str) -> int:
    direct = (
        "aging",
        "ageing",
        "healthspan",
        "longevity",
        "geroscience",
        "immunosenescence",
        "older adults",
        "age-related",
    )
    indirect = (
        "senescence",
        "frailty",
        "infection",
        "functional",
        "lifespan",
        "morbidity",
    )
    if _contains_any(text, direct):
        return 2
    if _contains_any(text, indirect):
        return 1
    return 0


def _infer_quality(doc: dict[str, Any], text: str, level: int) -> tuple[int, int, int, int, int]:
    methods = 2 if _contains_any(text, ("randomized", "double-blind", "placebo", "meta-analysis", "systematic review")) else 1 if _contains_any(text, ("trial", "cohort", "observational", "registry", "review")) else 0
    bias = 2 if _contains_any(text, ("randomized", "blinded", "placebo", "meta-analysis", "confound")) else 1 if _contains_any(text, ("cohort", "observational", "control")) else 0

    n = None
    enroll = doc.get("enrollment")
    if isinstance(enroll, (int, float)):
        n = int(enroll)
    if n is None:
        m = re.search(r"\bn\s*=\s*(\d+)\b", text)
        if m:
            n = int(m.group(1))
    if level == 1 and n is None:
        sample = 2
    elif n is None:
        sample = 1
    elif n >= 200:
        sample = 2
    elif n >= 50:
        sample = 1
    else:
        sample = 0

    has_results = bool(doc.get("results_summary")) or _contains_any(text, ("results", "findings", "outcome"))
    reporting = 2 if has_results and len(text) > 300 else 1 if len(text) > 80 else 0
    info = 2 if (len(text) > 200 and (_contains_any(text, ("phase", "status", "methods", "randomized")) or level in {1, 2})) else 1 if len(text) > 60 else 0
    return methods, bias, sample, reporting, info


def _infer_endpoint_grade(text: str) -> int:
    if _contains_any(text, ("mortality", "survival", "death", "disability-free", "overall survival")):
        return 3
    if _contains_any(text, ("infection", "hospitalization", "frailty", "functional", "clinical endpoint", "adverse event")):
        return 2
    if _contains_any(text, ("biomarker", "gene expression", "clock", "marker", "ifn-induced")):
        return 1
    return 0


def _infer_direction_strength(text: str) -> tuple[int, int]:
    pos = _contains_any(
        text,
        (
            "improved",
            "beneficial",
            "reduced",
            "decrease",
            "extended lifespan",
            "well tolerated",
            "increase survival",
            "significant reduction",
        ),
    )
    neg = _contains_any(
        text,
        (
            "did not",
            "no significant",
            "worse",
            "harm",
            "toxicity",
            "increased adverse",
            "not reduce",
            "failed",
        ),
    )
    if pos and not neg:
        direction = 1
    elif neg and not pos:
        direction = -1
    else:
        direction = 0

    strong = _contains_any(text, ("statistically significant", "phase 3", "meta-analysis", "systematic review"))
    moderate = _contains_any(text, ("phase 2", "trial", "observational", "cohort"))
    strength = 2 if strong else 1 if moderate else 0
    return direction, strength


def _compute_doc_weight(
    *,
    level: int,
    relevance: int,
    q_scores: tuple[int, int, int, int, int],
    endpoint_grade: int,
    effect_direction: int,
    effect_strength: int,
) -> float:
    w_level = {1: 1.00, 2: 0.85, 3: 0.55, 4: 0.25, 5: 0.12, 6: 0.06}[level]
    m_rel = {0: 0.0, 1: 0.6, 2: 1.0}[relevance]
    q_mean = sum(q_scores) / 5.0
    m_quality = 0.45 + 0.275 * q_mean
    m_endpoint = {0: 0.3, 1: 0.6, 2: 0.85, 3: 1.0}[endpoint_grade]
    m_direction = {1: 1.0, 0: 0.85, -1: 0.65}[effect_direction]
    m_strength = {0: 0.85, 1: 1.0, 2: 1.1}[effect_strength]
    return w_level * m_rel * m_quality * m_endpoint * m_direction * m_strength


def _deterministic_rubric_score(
    *,
    fetched_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    caps = {1: 30.0, 2: 30.0, 3: 15.0, 4: 12.0, 5: 8.0, 6: 5.0}
    taus = {1: 1.0, 2: 2.0, 3: 3.0, 4: 5.0, 5: 7.0, 6: 8.0}
    sums = {i: 0.0 for i in range(1, 7)}
    counts = {i: 0 for i in range(1, 7)}
    graded: list[dict[str, Any]] = []

    for d in fetched_documents:
        text = _text_blob(d)
        level, design, human_flag = _infer_level_design(d, text)
        relevance = _infer_relevance(text)
        q = _infer_quality(d, text, level)
        endpoint = _infer_endpoint_grade(text)
        direction, strength = _infer_direction_strength(text)
        dw = _compute_doc_weight(
            level=level,
            relevance=relevance,
            q_scores=q,
            endpoint_grade=endpoint,
            effect_direction=direction,
            effect_strength=strength,
        )
        sums[level] += dw
        counts[level] += 1
        graded.append(
            {
                "id": d.get("id"),
                "source_type": d.get("source_type"),
                "title": d.get("title") or "",
                "level": level,
                "design_label": design,
                "human_flag": human_flag,
                "relevance": relevance,
                "endpoint_grade": endpoint,
                "effect_direction": direction,
                "doc_weight": round(dw, 6),
                "reporting_quality": q[3],
                "text": text,
            }
        )

    contributions = {
        i: caps[i] * (1 - math.exp(-(sums[i] / taus[i]))) if sums[i] > 0 else 0.0 for i in range(1, 7)
    }
    raw_conf = sum(contributions.values())

    any_human = any(g["level"] in {1, 2, 3} and g["relevance"] > 0 for g in graded)
    any_rct = any(g["level"] == 2 and g["relevance"] > 0 for g in graded)
    any_human_endpoints = any(g["level"] in {1, 2, 3} and g["endpoint_grade"] >= 2 for g in graded)
    any_human_safety = any(
        g["level"] in {1, 2, 3}
        and g["reporting_quality"] >= 1
        and _contains_any(g["text"], ("safety", "adverse event", "tolerability", "well tolerated", "warnings"))
        for g in graded
    )

    penalty = 1.0
    if not any_human:
        penalty *= 0.35
    elif not any_rct:
        penalty *= 0.75
    if any_rct and not any_human_endpoints:
        penalty *= 0.85
    if not any_human_safety:
        penalty *= 0.90

    final_conf = raw_conf * penalty

    top_docs = sorted(graded, key=lambda x: x["doc_weight"], reverse=True)[:8]
    top_docs_out = [
        {
            "id": t["id"],
            "source_type": t["source_type"],
            "title": t["title"],
            "level": t["level"],
            "doc_weight": round(float(t["doc_weight"]), 4),
            "relevance": t["relevance"],
            "endpoint_grade": t["endpoint_grade"],
            "effect_direction": t["effect_direction"],
            "why_influential": "High weighted contribution under rubric multipliers.",
        }
        for t in top_docs
    ]

    return {
        "confidence": round(float(final_conf), 2),
        "confidence_raw": round(float(raw_conf), 2),
        "gating_penalty": round(float(penalty), 4),
        "checklist": {
            "any_human_evidence": bool(any_human),
            "any_rct": bool(any_rct),
            "any_human_endpoints": bool(any_human_endpoints),
            "any_human_safety": bool(any_human_safety),
        },
        "tier_contributions": {str(i): round(float(contributions[i]), 2) for i in range(1, 7)},
        "selected_counts_by_level": {str(i): int(counts[i]) for i in range(1, 7)},
        "top_docs": top_docs_out,
        "notes": [
            "deterministic_rubric_score_v1",
            f"documents_scored={len(fetched_documents)}",
        ],
    }


@dataclass
class EvidenceGraderConfig:
    max_new_tokens: int = 900
    report_max_new_tokens: int = 1800
    max_schema_chars: int = 5000
    max_docs_for_final: int = 60
    scoring_mode: Literal["deterministic_only", "llm_then_fallback", "llm_only"] = "deterministic_only"


@dataclass
class EvidenceRetrievalConfig:
    min_fetch_docs: int = 20
    auto_fetch_per_search: int = 3
    min_per_source: int = 2
    max_steps: int = 14
    max_new_tokens: int = 900
    max_schema_chars: int = 12000
    explore_first: bool = True
    default_blocklist: tuple[str, ...] = ("social", "news")

    def to_agent_config(self) -> AgentConfig:
        return AgentConfig(
            min_fetch_docs=self.min_fetch_docs,
            auto_fetch_per_search=self.auto_fetch_per_search,
            min_per_source=self.min_per_source,
            max_steps=self.max_steps,
            max_new_tokens=self.max_new_tokens,
            max_schema_chars=self.max_schema_chars,
            explore_first=self.explore_first,
            default_blocklist=self.default_blocklist,
        )


class EvidenceGrader:
    """Final grading component (separate from retrieval/query tool)."""

    _PIPE = None

    def __init__(
        self,
        *,
        hf_token: Optional[str],
        device: str,
        model: str,
        cfg: EvidenceGraderConfig | None = None,
    ) -> None:
        self.hf_token = hf_token
        self.device = device
        self.model = model
        self.cfg = cfg or EvidenceGraderConfig()

    def llm_call(self, prompt: str, *, max_new_tokens: Optional[int] = None) -> str:
        import torch
        from transformers import pipeline

        dev = self.device
        if dev.startswith("cuda") and not torch.cuda.is_available():
            dev = "cpu"

        if EvidenceGrader._PIPE is None:
            dtype = torch.float32 if dev.startswith("cpu") else torch.bfloat16
            EvidenceGrader._PIPE = pipeline(
                "image-text-to-text",
                model=self.model,
                dtype=dtype,
                device=dev,
                token=self.hf_token,
            )

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        out = EvidenceGrader._PIPE(
            text=messages,
            max_new_tokens=max_new_tokens or self.cfg.max_new_tokens,
            do_sample=False,
            temperature=0.0,
            top_p=1.0,
        )
        first = out[0] if isinstance(out, list) and out else out
        if isinstance(first, dict):
            gen = first.get("generated_text")
            if isinstance(gen, list) and gen and isinstance(gen[-1], dict):
                return str(gen[-1].get("content", ""))
            if isinstance(gen, str):
                return gen
            if "text" in first:
                return str(first["text"])
        return str(out)

    def _final_prompt(
        self,
        *,
        intervention: str,
        rubric_text: str,
        schema_text: str,
        summary_stats: dict[str, Any],
        fetched_evidence: list[dict[str, Any]],
    ) -> str:
        return f"""
You are computing the final confidence score from evidence in a LOCAL JSON corpus.

Intervention: {intervention}

Rubric / Task:
{rubric_text}

Schema reference:
{schema_text[: self.cfg.max_schema_chars]}

Summary statistics:
{summary_stats}

Fetched evidence:
{fetched_evidence}

Rules:
- Aggregate across all fetched documents; do not score from a single document.
- The returned confidence must reflect both evidence quality and evidence quantity.
- More high-tier, high-quality evidence should increase confidence.
- Return ONLY a valid JSON object (no markdown, no reasoning preamble, no <unused94>thought).
- First character must be '{{' and last character must be '}}'.
"""

    def _call_llm_json_with_retry(self, prompt: str) -> tuple[dict[str, Any] | None, str]:
        raw = self.llm_call(prompt)
        obj = _safe_json_parse(raw)
        if obj is not None:
            return obj, raw

        retry_prompt = (
            prompt
            + "\n\nCRITICAL: Return JSON only. No preamble. No analysis text. Start with '{' and end with '}'."
        )
        raw_retry = self.llm_call(retry_prompt, max_new_tokens=min(self.cfg.max_new_tokens, 450))
        obj_retry = _safe_json_parse(raw_retry)
        if obj_retry is not None:
            return obj_retry, raw_retry

        repair_prompt = f"""
You are a JSON repair tool.
Convert the text below into ONE valid JSON object.
Do not include markdown.

TEXT:
{raw_retry[:7000]}
"""
        raw_repair = self.llm_call(repair_prompt, max_new_tokens=420)
        obj_repair = _safe_json_parse(raw_repair)
        if obj_repair is not None:
            return obj_repair, raw_repair
        return None, raw_repair

    def _call_llm_report_with_retry(
        self,
        llm_call_fn: Callable[[str], str],
        prompt: str,
        *,
        max_retries: int = 3,
    ) -> str:
        raw = llm_call_fn(prompt)
        out = _clean_report_markdown(raw)
        if out and _is_valid_report_markdown(out):
            return out
        last = raw
        for _ in range(max_retries):
            raw = llm_call_fn(
                prompt
                + "\n\nIMPORTANT: Output ONLY the final report markdown. Do not include plan/execution/thought. "
                + "Do not include constraint checklists, sandbox notes, or strategy text. "
                + "Start with '# Evidence Confidence Report'."
            )
            out = _clean_report_markdown(raw)
            last = raw
            if out and _is_valid_report_markdown(out):
                return out
        return _clean_report_markdown(last)

    def grade(
        self,
        *,
        intervention: str,
        rubric_text: str,
        schema_text: str,
        summary_stats: dict[str, Any],
        fetched_documents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fetched_evidence = compact_docs_for_final(
            fetched_documents,
            max_docs=self.cfg.max_docs_for_final,
        )

        if self.cfg.scoring_mode == "deterministic_only":
            return _deterministic_rubric_score(fetched_documents=fetched_evidence)

        prompt = self._final_prompt(
            intervention=intervention,
            rubric_text=rubric_text,
            schema_text=schema_text,
            summary_stats=summary_stats,
            fetched_evidence=fetched_evidence,
        )
        obj, raw = self._call_llm_json_with_retry(prompt)
        if obj is None:
            if self.cfg.scoring_mode == "llm_only":
                return {"error": "final_output_not_json", "raw_preview": raw[:1200]}
            fallback = _deterministic_rubric_score(fetched_documents=fetched_evidence)
            fallback["notes"].append(f"raw_preview={raw[:280]}")
            return fallback
        return obj

    def grade_with_query_tool(
        self,
        *,
        query_tool: JsonCorpusQueryTool,
        rubric_text: str,
        context_path: Optional[str] = None,
        report_out_path: Optional[str] = None,
        report_extra_doc_ids: Optional[list[str]] = None,
        report_max_docs: int = 20,
        report_max_text_chars: int = 1200,
        generate_report: bool = True,
    ) -> dict[str, Any]:
        return self._grade_from_query_tool_context(
            query_tool=query_tool,
            rubric_text=rubric_text,
            context_path=context_path,
            report_out_path=report_out_path,
            report_extra_doc_ids=report_extra_doc_ids,
            report_max_docs=report_max_docs,
            report_max_text_chars=report_max_text_chars,
            generate_report=generate_report,
        )

    def grade_with_corpus(
        self,
        *,
        corpus_path: str,
        stats_path: str,
        schema_path: str,
        rubric_text: str,
        retrieval_cfg: EvidenceRetrievalConfig | None = None,
        context_path: Optional[str] = None,
        report_out_path: Optional[str] = None,
        report_extra_doc_ids: Optional[list[str]] = None,
        report_max_docs: int = 20,
        report_max_text_chars: int = 1200,
        generate_report: bool = True,
    ) -> dict[str, Any]:
        query_tool = JsonCorpusQueryTool(
            corpus_path=corpus_path,
            stats_path=stats_path,
            schema_path=schema_path,
            hf_token=self.hf_token,
            device=self.device,
            model=self.model,
            cfg=(retrieval_cfg or EvidenceRetrievalConfig()).to_agent_config(),
        )
        return self._grade_from_query_tool_context(
            query_tool=query_tool,
            rubric_text=rubric_text,
            context_path=context_path,
            report_out_path=report_out_path,
            report_extra_doc_ids=report_extra_doc_ids,
            report_max_docs=report_max_docs,
            report_max_text_chars=report_max_text_chars,
            generate_report=generate_report,
        )

    def _grade_from_query_tool_context(
        self,
        *,
        query_tool: JsonCorpusQueryTool,
        rubric_text: str,
        context_path: Optional[str] = None,
        report_out_path: Optional[str] = None,
        report_extra_doc_ids: Optional[list[str]] = None,
        report_max_docs: int = 20,
        report_max_text_chars: int = 1200,
        generate_report: bool = True,
    ) -> dict[str, Any]:
        context = query_tool.collect(task_text=rubric_text, context_path=context_path)
        final_output = self.grade(
            intervention=query_tool.intervention,
            rubric_text=rubric_text,
            schema_text=query_tool.schema_text,
            summary_stats=query_tool.stats,
            fetched_documents=context.get("fetched_documents", []),
        )
        context["final_output"] = final_output
        if generate_report:
            extra_ids = list(report_extra_doc_ids or [])
            if not extra_ids:
                for d in context.get("fetched_documents", [])[:10]:
                    did = d.get("id")
                    if isinstance(did, str):
                        extra_ids.append(did)
            evidence_pack = build_evidence_pack(
                corpus=query_tool.corpus,
                final_output=final_output,
                extra_doc_ids=extra_ids,
                max_docs=report_max_docs,
                max_text_chars=report_max_text_chars,
            )
            prompt = build_llm_report_prompt(
                rubric_text=rubric_text,
                final_output=final_output,
                evidence_pack=evidence_pack,
            )
            report_md = self._call_llm_report_with_retry(
                lambda p: self.llm_call(p, max_new_tokens=self.cfg.report_max_new_tokens),
                prompt,
            )
            context["analysis_report"] = {
                "generated": bool(report_md.strip()),
                "doc_count_in_pack": evidence_pack.get("doc_count_in_pack", 0),
                "preview": report_md[:1000],
            }
            if report_out_path:
                out_path = Path(report_out_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(report_md, encoding="utf-8")
                context["analysis_report"]["path"] = str(out_path)

        context["updated_at"] = datetime.now(UTC).isoformat()
        context.setdefault("history", []).append({"step": "final", "action": "final_output_written"})
        if context_path:
            save_json(context_path, context)
        return context
