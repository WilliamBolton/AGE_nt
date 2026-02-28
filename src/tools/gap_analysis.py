from __future__ import annotations

"""gap_analysis.py

Gap analysis tool for the LOCAL JSON corpus.

This is intentionally parallel to `evidence_grader.py`:
  - same JsonCorpusQueryTool orchestration (collect fetched documents)
  - deterministic-only gap evaluation (fast, no per-doc LLM grading)
  - optional MedGemma markdown report generation (audit style)

It produces a structured gap report:
  - which parts of the evidence hierarchy are present/missing
  - where the clinical translation gaps are (endpoints, duration, older adults, results reporting)
  - a concrete "what would close the gap" recommendation list
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
import re
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
        r"(?mi)#\s+Evidence Gap Analysis Report\b",
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
        "evidence map",
        "gap table",
        "what would close the gaps",
    )
    return all(r in s for r in required)


def build_evidence_pack(
    *,
    corpus: dict[str, Any],
    final_output: dict[str, Any],
    extra_doc_ids: Optional[list[str]] = None,
    max_docs: int = 24,
    max_text_chars: int = 1200,
) -> dict[str, Any]:
    """Build a small evidence pack to support the narrative markdown report."""
    by_id = {
        d.get("id"): d
        for d in (corpus.get("documents", []) or [])
        if isinstance(d, dict) and isinstance(d.get("id"), str)
    }

    doc_ids: list[str] = []
    for td in (final_output.get("exemplars") or []):
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
        for k in ("abstract", "brief_summary", "detailed_description", "results_summary", "warnings_summary"):
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
You are writing an audit-style report for an evidence gap analysis.

CRITICAL CONSTRAINTS
- You MUST use ONLY the provided evidence_pack documents and the provided final_output.
- Do NOT use outside knowledge.
- Every factual claim about a study/trial must cite a document by its id and use fields present in evidence_pack.
- If you cannot find something in evidence_pack, say it is missing from the scraped record.
- Do NOT change any values in final_output.

INPUTS

RUBRIC:
{rubric_text}

FINAL OUTPUT (ground truth):
{json.dumps(final_output, ensure_ascii=False)}

EVIDENCE PACK:
{json.dumps(evidence_pack, ensure_ascii=False)}

TASK
Write a report explaining the evidence gaps and what would close them.

REQUIRED REPORT SECTIONS (Markdown)
Start EXACTLY with this heading:
# Evidence Gap Analysis Report

1) Executive summary (3-6 bullets)
2) Evidence map (what is present across the hierarchy)
3) Gap table (Satisfied / Partial / Missing / Unknown)
4) Key exemplar documents (5-10 items)
5) Limitations of this run
6) What would close the gaps (actionable study designs / data needed)

STYLE
- Be concise and specific.
- Use inline citations like (doc: <id>).
- Output Markdown only.
"""


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _text_blob(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in (
        "title",
        "abstract",
        "brief_summary",
        "detailed_description",
        "results_summary",
        "primary_outcomes",
        "secondary_outcomes",
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


def _infer_level_design(doc: dict[str, Any], text: str) -> tuple[int, str, bool]:
    """Same hierarchy as confidence scoring.

    NOTE: This is intentionally heuristic; the goal is gap analysis, not perfect classification.
    """
    st = str(doc.get("source_type") or "").lower()
    pub_types = " ".join(str(x).lower() for x in (doc.get("publication_types") or []))

    if st == "clinicaltrials":
        # Registry entries still count as "human interventional evidence exists", but may not be RCTs.
        allocation = str(doc.get("allocation") or "").lower()
        study_type = str(doc.get("study_type") or "").lower()
        if "interventional" in study_type and "random" in allocation:
            return 2, "clinical_trial_registry_rct", True
        if "interventional" in study_type:
            return 3, "clinical_trial_registry_nonrandom", True
        return 3, "clinical_trial_registry_observational", True

    if st == "drugage":
        return 4, "drugage_database", False

    if _contains_any(text + " " + pub_types, ("meta-analysis", "meta analysis", "systematic review", "cochrane")):
        return 1, "meta_analysis", True
    if _contains_any(
        text + " " + pub_types,
        (
            "randomized",
            "randomised",
            "double-blind",
            "placebo",
            "clinical trial",
            "phase i",
            "phase ii",
            "phase iii",
            "phase iv",
        ),
    ):
        return 2, "rct", True
    if _contains_any(text, ("cohort", "observational", "registry", "case-control", "epidemiolog")):
        return 3, "observational_human", True
    if _contains_any(text, ("mouse", "mice", "murine", "rat", "drosophila", "zebrafish", "c. elegans", "in vivo")):
        return 4, "animal_in_vivo", False
    if _contains_any(text, ("in vitro", "cell line", "organoid", "cell culture")):
        return 5, "in_vitro", False
    if _contains_any(text, ("in silico", "computational", "docking", "machine learning")):
        return 6, "in_silico", False

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
        "frailty",
    )
    indirect = (
        "senescence",
        "infection",
        "functional",
        "lifespan",
        "morbidity",
        "epigenetic",
        "clock",
    )
    if _contains_any(text, direct):
        return 2
    if _contains_any(text, indirect):
        return 1
    return 0


def _infer_endpoint_grade(text: str) -> int:
    if _contains_any(text, ("mortality", "survival", "death", "disability-free", "overall survival")):
        return 3
    if _contains_any(text, ("infection", "hospital", "frailty", "gait", "grip", "functional", "clinical endpoint")):
        return 2
    if _contains_any(text, ("biomarker", "gene expression", "clock", "marker", "ifn")):
        return 1
    return 0


def _infer_has_safety(text: str, doc: dict[str, Any]) -> Optional[bool]:
    """Return True/False/None if unknown."""
    st = str(doc.get("source_type") or "").lower()
    if st == "regulatory":
        ws = str(doc.get("warnings_summary") or "").strip()
        return bool(ws) if ws else None
    if _contains_any(text, ("adverse event", "ae", "safety", "tolerability", "well tolerated", "warnings")):
        return True
    # If doc is very short and contains none of the terms, treat as unknown.
    if len(text) < 120:
        return None
    return False


def _infer_duration_band(doc: dict[str, Any], text: str) -> str:
    """Best-effort duration band.

    Uses clinicaltrials dates if present; else looks for common patterns in text.
    """
    # clinicaltrials: if date_started/date_completed exist, we can approximate.
    st = str(doc.get("source_type") or "").lower()
    if st == "clinicaltrials":
        ds = str(doc.get("date_started") or "")
        dc = str(doc.get("date_completed") or "")
        if ds and dc and re.match(r"\d{4}-\d{2}-\d{2}", ds) and re.match(r"\d{4}-\d{2}-\d{2}", dc):
            try:
                start = datetime.fromisoformat(ds.replace("Z", ""))
                end = datetime.fromisoformat(dc.replace("Z", ""))
                days = max(0, (end - start).days)
                if days < 28:
                    return "acute"
                if days < 84:
                    return "short"
                if days < 365:
                    return "medium"
                return "long"
            except Exception:
                pass
        # fall back to unknown
        return "unclear"

    # PubMed-ish: scan for durations like "12 weeks", "1 year", "6 months".
    m = re.search(r"\b(\d+)\s*(day|days|week|weeks|month|months|year|years)\b", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("day"):
            days = n
        elif unit.startswith("week"):
            days = 7 * n
        elif unit.startswith("month"):
            days = 30 * n
        else:
            days = 365 * n
        if days < 28:
            return "acute"
        if days < 84:
            return "short"
        if days < 365:
            return "medium"
        return "long"
    return "unclear"


def _infer_older_adults(text: str, doc: dict[str, Any]) -> Optional[bool]:
    if _contains_any(text, ("older adults", "elderly", "aged ", "age 65", ">=65", "over 65")):
        return True
    # Clinical trials sometimes include "aged" in eligibility; may not be present.
    if len(text) < 150:
        return None
    return False


def _infer_results_available(doc: dict[str, Any], text: str) -> Optional[bool]:
    st = str(doc.get("source_type") or "").lower()
    if st == "clinicaltrials":
        if doc.get("date_results_posted"):
            return True
        # if completed but no results date, treat as "missing" rather than unknown
        status = str(doc.get("status") or "").lower()
        if "completed" in status:
            return False
        return None
    # PubMed/europe_pmc: assume published paper has results if abstract length is decent.
    if "abstract" in doc and isinstance(doc.get("abstract"), str):
        return True if len(str(doc.get("abstract") or "")) > 200 else None
    return None


def _gap_status(*, satisfied: bool, partial: bool, unknown: bool) -> str:
    if satisfied:
        return "Satisfied"
    if partial:
        return "Partial"
    if unknown:
        return "Unknown"
    return "Missing"


def _deterministic_gap_analysis(*, fetched_documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Run deterministic gap analysis over fetched evidence."""
    docs = compact_docs_for_final(fetched_documents, max_docs=120)

    graded: list[dict[str, Any]] = []
    counts_by_level = {i: 0 for i in range(1, 7)}
    for d in docs:
        text = _text_blob(d)
        level, design, human_flag = _infer_level_design(d, text)
        relevance = _infer_relevance(text)
        endpoint = _infer_endpoint_grade(text)
        safety = _infer_has_safety(text, d)
        duration = _infer_duration_band(d, text)
        older = _infer_older_adults(text, d)
        results = _infer_results_available(d, text)

        counts_by_level[level] += 1
        graded.append(
            {
                "id": d.get("id"),
                "source_type": d.get("source_type"),
                "title": d.get("title") or "",
                "level": level,
                "design_label": design,
                "human_flag": bool(human_flag),
                "relevance": relevance,
                "endpoint_grade": endpoint,
                "duration_band": duration,
                "older_adults": older,
                "safety_reported": safety,
                "results_available": results,
                "text": text,
            }
        )

    # Convenience subsets
    human = [g for g in graded if g["level"] in {1, 2, 3} and g["relevance"] > 0]
    rcts = [g for g in graded if g["level"] == 2 and g["relevance"] > 0]
    human_direct = [g for g in human if g["endpoint_grade"] >= 2]

    # Gaps
    gaps: list[dict[str, Any]] = []

    def add_gap(key: str, title: str, status: str, severity: str, why: str, evidence_ids: list[str], close: str) -> None:
        gaps.append(
            {
                "key": key,
                "title": title,
                "status": status,
                "severity": severity,
                "why_it_matters": why,
                "evidence_ids": evidence_ids[:8],
                "how_to_close": close,
            }
        )

    # G1 human evidence
    add_gap(
        "G1_human_evidence",
        "Any human evidence relevant to ageing/healthspan",
        _gap_status(satisfied=bool(human), partial=False, unknown=False),
        "High",
        "Without human evidence, claims remain preclinical.",
        [g["id"] for g in human if isinstance(g.get("id"), str)],
        "At least one well-described human study (interventional or observational) with ageing/healthspan-relevant outcomes.",
    )

    # G2 randomised evidence
    # 'Partial' if there are human studies but no RCTs.
    add_gap(
        "G2_randomised_evidence",
        "Randomised controlled trial evidence",
        _gap_status(satisfied=bool(rcts), partial=bool(human) and not bool(rcts), unknown=False),
        "High",
        "Randomisation reduces bias and strengthens causal claims.",
        [g["id"] for g in rcts if isinstance(g.get("id"), str)],
        "At least one adequately powered RCT in a relevant population with pre-specified ageing/healthspan endpoints.",
    )

    # G3 human meaningful endpoints
    # 'Partial' if only surrogate biomarkers exist
    has_human_surrogates = any(g["endpoint_grade"] == 1 for g in human)
    add_gap(
        "G3_human_endpoints",
        "Clinically meaningful endpoints in humans",
        _gap_status(satisfied=bool(human_direct), partial=bool(human) and has_human_surrogates and not bool(human_direct), unknown=bool(human) and not human_direct and not has_human_surrogates),
        "High",
        "Functional/clinical outcomes are harder to over-interpret than biomarkers.",
        [g["id"] for g in human_direct if isinstance(g.get("id"), str)],
        "Human studies measuring validated functional/clinical proxies (e.g., infections, frailty, gait speed) or hard endpoints.",
    )

    # G4 replication
    add_gap(
        "G4_replication",
        "Replication across independent human studies",
        _gap_status(satisfied=len(rcts) >= 2 or (len(human) >= 2 and any(g["level"] == 1 for g in human)), partial=len(human) == 1, unknown=False),
        "Medium",
        "Replication reduces the chance that findings are spurious or context-specific.",
        [g["id"] for g in human[:6] if isinstance(g.get("id"), str)],
        "Multiple independent human studies (ideally multi-site) with consistent direction on key endpoints.",
    )

    # G5 older adults
    older_true = [g for g in human if g["older_adults"] is True]
    older_unknown = any(g["older_adults"] is None for g in human)
    add_gap(
        "G5_older_adults",
        "Evidence in older adults / ageing-target populations",
        _gap_status(satisfied=bool(older_true), partial=bool(human) and not bool(older_true) and not older_unknown, unknown=older_unknown),
        "High",
        "Anti-ageing claims should be supported in older/adult ageing-relevant populations.",
        [g["id"] for g in older_true if isinstance(g.get("id"), str)],
        "Trials/cohorts explicitly enrolling older adults (e.g., ≥65) or measuring ageing phenotypes.",
    )

    # S1 safety
    safety_true = [g for g in human if g["safety_reported"] is True]
    safety_unknown = any(g["safety_reported"] is None for g in human)
    add_gap(
        "S1_human_safety",
        "Human safety / tolerability reporting",
        _gap_status(satisfied=bool(safety_true), partial=bool(human) and not bool(safety_true) and not safety_unknown, unknown=safety_unknown),
        "High",
        "Even if efficacy is promising, poor safety evidence limits real-world use.",
        [g["id"] for g in safety_true if isinstance(g.get("id"), str)],
        "Human studies or regulatory summaries reporting adverse events, tolerability and key risks.",
    )

    # S2 duration (chronic use)
    longish = [g for g in human if g["duration_band"] in {"medium", "long"}]
    duration_unknown = any(g["duration_band"] == "unclear" for g in human)
    add_gap(
        "S2_duration",
        "Adequate duration for chronic use",
        _gap_status(satisfied=bool(longish), partial=bool(human) and not bool(longish) and not duration_unknown, unknown=duration_unknown),
        "Medium",
        "Short trials may miss delayed harms/benefits and do not reflect long-term use.",
        [g["id"] for g in longish if isinstance(g.get("id"), str)],
        "Longer-duration human studies (months to years) with follow-up.",
    )

    # D1 publication / results gap for trials
    trials = [g for g in graded if g["source_type"] == "clinicaltrials" and g["relevance"] > 0]
    completed_no_results = [g for g in trials if g["results_available"] is False]
    results_unknown = any(g["results_available"] is None for g in trials)
    add_gap(
        "D1_results_posted",
        "Registered trials with results posted / publications linked",
        _gap_status(satisfied=bool(trials) and not bool(completed_no_results), partial=bool(completed_no_results), unknown=results_unknown),
        "High",
        "Unreported completed trials can bias the evidence base (publication/reporting bias).",
        [g["id"] for g in completed_no_results if isinstance(g.get("id"), str)],
        "Ensure completed trials post results and/or link peer-reviewed publications (NCT→paper linkage).",
    )

    # Preclinical strength (helpful, lower severity)
    animal = [g for g in graded if g["level"] == 4 and g["relevance"] > 0]
    add_gap(
        "P1_animal_in_vivo",
        "Robust in vivo (animal) evidence",
        _gap_status(satisfied=len(animal) >= 2, partial=len(animal) == 1, unknown=False),
        "Low",
        "Strong in vivo evidence improves biological plausibility and prioritisation.",
        [g["id"] for g in animal if isinstance(g.get("id"), str)],
        "Multiple independent animal studies showing healthspan/lifespan benefits with appropriate controls.",
    )

    # Exemplars: pick up to 10 docs to show in report (prefer human, then animal)
    exemplars = []
    for pool in (human_direct, rcts, human, animal, graded):
        for g in pool:
            if not isinstance(g.get("id"), str):
                continue
            if g["id"] in {e["id"] for e in exemplars}:
                continue
            exemplars.append(
                {
                    "id": g["id"],
                    "source_type": g.get("source_type"),
                    "title": g.get("title"),
                    "level": g.get("level"),
                    "relevance": g.get("relevance"),
                    "endpoint_grade": g.get("endpoint_grade"),
                    "duration_band": g.get("duration_band"),
                    "older_adults": g.get("older_adults"),
                    "safety_reported": g.get("safety_reported"),
                    "results_available": g.get("results_available"),
                }
            )
            if len(exemplars) >= 10:
                break
        if len(exemplars) >= 10:
            break

    return {
        "gap_analysis_version": "deterministic_gap_v1",
        "evidence_map": {
            "counts_by_level": {str(i): int(counts_by_level[i]) for i in range(1, 7)},
            "human_docs_count": len(human),
            "rct_docs_count": len(rcts),
            "human_direct_endpoints_count": len(human_direct),
        },
        "gaps": gaps,
        "exemplars": exemplars,
        "notes": [f"documents_scanned={len(docs)}"],
    }


@dataclass
class GapAnalysisConfig:
    max_new_tokens: int = 900
    report_max_new_tokens: int = 1800
    max_schema_chars: int = 5000
    max_docs_for_final: int = 120
    analysis_mode: Literal["deterministic_only"] = "deterministic_only"


class GapAnalyzer:
    """Final gap analysis component (separate from retrieval/query tool)."""

    _PIPE = None

    def __init__(
        self,
        *,
        hf_token: Optional[str],
        device: str,
        model: str,
        cfg: GapAnalysisConfig | None = None,
    ) -> None:
        self.hf_token = hf_token
        self.device = device
        self.model = model
        self.cfg = cfg or GapAnalysisConfig()

    def llm_call(self, prompt: str, *, max_new_tokens: Optional[int] = None) -> str:
        import torch
        from transformers import pipeline

        dev = self.device
        if dev.startswith("cuda") and not torch.cuda.is_available():
            dev = "cpu"

        if GapAnalyzer._PIPE is None:
            dtype = torch.float32 if dev.startswith("cpu") else torch.bfloat16
            GapAnalyzer._PIPE = pipeline(
                "image-text-to-text",
                model=self.model,
                dtype=dtype,
                device=dev,
                token=self.hf_token,
            )

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        out = GapAnalyzer._PIPE(
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
                + "Start with '# Evidence Gap Analysis Report'."
            )
            out = _clean_report_markdown(raw)
            last = raw
            if out and _is_valid_report_markdown(out):
                return out
        return _clean_report_markdown(last)

    def analyze(
        self,
        *,
        intervention: str,
        rubric_text: str,
        schema_text: str,
        summary_stats: dict[str, Any],
        fetched_documents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Deterministic-only for now (fast and reliable).
        _ = schema_text  # reserved (kept for parity)
        _ = summary_stats
        _ = rubric_text
        return _deterministic_gap_analysis(fetched_documents=fetched_documents)

    def analyze_with_query_tool(
        self,
        *,
        query_tool: JsonCorpusQueryTool,
        rubric_text: str,
        context_path: Optional[str] = None,
        report_out_path: Optional[str] = None,
        report_extra_doc_ids: Optional[list[str]] = None,
        report_max_docs: int = 24,
        report_max_text_chars: int = 1200,
        generate_report: bool = True,
    ) -> dict[str, Any]:
        context = query_tool.collect(task_text=rubric_text, context_path=context_path)
        final_output = self.analyze(
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

    def analyze_from_paths(
        self,
        *,
        corpus_path: str,
        stats_path: str,
        schema_path: str,
        rubric_text: str,
        agent_cfg: AgentConfig | None = None,
        context_path: Optional[str] = None,
        report_out_path: Optional[str] = None,
        report_extra_doc_ids: Optional[list[str]] = None,
        report_max_docs: int = 24,
        report_max_text_chars: int = 1200,
        generate_report: bool = True,
    ) -> dict[str, Any]:
        """Convenience entrypoint.

        New workflow: the tool owns retrieval.
        This method constructs the JsonCorpusQueryTool internally, runs collection,
        then runs deterministic gap analysis (and optional narrative report).
        """

        qtool = JsonCorpusQueryTool(
            corpus_path=corpus_path,
            stats_path=stats_path,
            schema_path=schema_path,
            hf_token=self.hf_token,
            device=self.device,
            model=self.model,
            cfg=agent_cfg or AgentConfig(),
        )
        return self.analyze_with_query_tool(
            query_tool=qtool,
            rubric_text=rubric_text,
            context_path=context_path,
            report_out_path=report_out_path,
            report_extra_doc_ids=report_extra_doc_ids,
            report_max_docs=report_max_docs,
            report_max_text_chars=report_max_text_chars,
            generate_report=generate_report,
        )
