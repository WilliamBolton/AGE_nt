
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Optional

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
        r"(?mi)#\s+Hype-to-Evidence Ratio Report\b",
        r"(?mi)^\s*##\s+Executive Summary\b",
        r"(?mi)^\s*1\)\s*(?:\*\*)?\s*Executive Summary\b",
    ]
    starts: list[int] = []
    for pat in anchors:
        m = re.search(pat, s)
        if m:
            starts.append(m.start())
    if starts:
        s = s[min(starts):].lstrip()
    return s


def _is_valid_report_markdown(text: str) -> bool:
    s = _clean_report_markdown(text).lower()
    required = ("executive summary", "ratio", "confidence", "limitations")
    return all(r in s for r in required)


def _text_blob(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in (
        "title",
        "abstract",
        "brief_summary",
        "results_summary",
        "publication_types",
        "mesh_terms",
        "conditions",
        "phase",
        "status",
        "approved_indications",
        "warnings_summary",
        "platform",
        "subreddit",
        "outlet",
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
    Evidence hierarchy:
      1 = Systematic reviews & meta-analyses
      2 = Randomised controlled trials (RCTs), including phase trials
      3 = Observational / epidemiological studies
      4 = Animal model studies (in vivo)
      5 = Cell culture / in vitro studies
      6 = In silico / computational predictions

    Returns (level, label, is_human_evidence_candidate)
    """
    pub_types = " ".join(str(x).lower() for x in (doc.get("publication_types") or []) if x is not None)
    mesh = " ".join(str(x).lower() for x in (doc.get("mesh_terms") or []) if x is not None)
    title = str(doc.get("title") or "").lower()
    header = f"{title} {pub_types} {mesh}"

    # Level 1
    if any(k in header for k in ("meta-analysis", "systematic review", "cochrane")):
        return 1, "meta_or_systematic", True

    # Level 2 (pub types and trial markers)
    if any(k in header for k in ("randomized controlled trial", "randomised controlled trial", "clinical trial", "phase i", "phase ii", "phase iii", "phase iv")):
        return 2, "clinical_trial", True
    if "randomiz" in header and ("trial" in header or "placebo" in header or "double-blind" in header):
        return 2, "clinical_trial_inferred", True

    # Level 3
    if any(k in header for k in ("cohort", "case-control", "observational", "epidemiolog", "registry", "population-based", "cross-sectional")):
        return 3, "observational", True
    if "humans" in mesh or "human" in header:
        return 3, "human_unspecified", True

    # Level 4/5/6
    if any(k in header for k in ("mice", "mouse", "rats", "rat", "drosophila", "zebrafish", "c. elegans", "caenorhabditis")):
        return 4, "animal_in_vivo", False
    if any(k in header for k in ("in vitro", "cell line", "cell culture", "organoid", "primary cells")):
        return 5, "in_vitro", False
    if any(k in header for k in ("in silico", "computational", "network pharmacology", "molecular docking", "machine learning", "deep learning")):
        return 6, "in_silico", False

    # Fallback by source_type
    st = str(doc.get("source_type") or "").lower()
    if st == "clinicaltrials":
        return 2, "clinical_trial_registry", True
    if st in ("pubmed", "europe_pmc", "regulatory"):
        return 3, "biomed_unspecified", True
    return 6, "unknown", False


def _is_social(doc: dict[str, Any]) -> bool:
    return str(doc.get("source_type") or "").lower() == "social"


def _is_news(doc: dict[str, Any]) -> bool:
    return str(doc.get("source_type") or "").lower() == "news"


def _is_evidence_source(doc: dict[str, Any]) -> bool:
    return str(doc.get("source_type") or "").lower() in ("pubmed", "europe_pmc", "clinicaltrials", "regulatory")


def _social_engagement_mass(doc: dict[str, Any]) -> float:
    """
    Use light engagement weighting if fields exist; otherwise 1.0.
    """
    score = doc.get("score")
    comments = doc.get("comment_count")
    mass = 1.0
    try:
        if isinstance(score, (int, float)) and score > 0:
            mass += math.log1p(float(score))
        if isinstance(comments, (int, float)) and comments > 0:
            mass += 0.5 * math.log1p(float(comments))
    except Exception:
        pass
    return mass


def _news_mass(doc: dict[str, Any]) -> float:
    """
    News mass: 1.0 baseline; optionally downweight if it cites a primary source.
    """
    mass = 1.0
    cites = doc.get("cites_primary_source")
    if isinstance(cites, bool) and cites:
        mass *= 0.85
    return mass


def _clamp_0_100(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


def _compute_hype_score_0to100(*, hype_mass: float, evidence_mass: float, ratio: float, hype_share: float) -> dict[str, Any]:
    """
    Robust hype score:
    - ratio and share dominate
    - low total volume dampens certainty
    """
    ratio_component = _clamp_0_100(100.0 * (ratio / (1.0 + ratio)))
    share_component = _clamp_0_100(100.0 * hype_share)
    volume_component = _clamp_0_100(100.0 * (1.0 - math.exp(-((hype_mass + evidence_mass) / 35.0))))
    hype_score = _clamp_0_100((0.45 * ratio_component) + (0.45 * share_component) + (0.10 * volume_component))
    return {
        "hype_score_0to100": round(hype_score, 1),
        "hype_score_components": {
            "ratio_component_0to100": round(ratio_component, 1),
            "share_component_0to100": round(share_component, 1),
            "volume_component_0to100": round(volume_component, 1),
        },
    }


def _extract_confidence_score(confidence_context: Optional[dict[str, Any]]) -> tuple[Optional[float], str]:
    if not isinstance(confidence_context, dict):
        return None, "not_provided"

    final_output = confidence_context.get("final_output")
    if isinstance(final_output, dict):
        val = final_output.get("confidence")
        if isinstance(val, (int, float)):
            return _clamp_0_100(float(val)), "final_output.confidence"
        if isinstance(val, str):
            try:
                return _clamp_0_100(float(val)), "final_output.confidence"
            except Exception:
                pass

    val = confidence_context.get("confidence")
    if isinstance(val, (int, float)):
        return _clamp_0_100(float(val)), "confidence"
    if isinstance(val, str):
        try:
            return _clamp_0_100(float(val)), "confidence"
        except Exception:
            pass
    return None, "missing"


def _assess_hype_vs_confidence(*, hype_score_0to100: float, confidence_score_0to100: Optional[float]) -> dict[str, Any]:
    if confidence_score_0to100 is None:
        return {
            "confidence_score_0to100": None,
            "hype_confidence_gap": None,
            "overhype_risk_0to100": None,
            "underhype_signal_0to100": None,
            "alignment_label": "confidence_unavailable",
            "interpretation": "Confidence score not available; overhype assessment unavailable.",
        }

    conf = _clamp_0_100(confidence_score_0to100)
    gap = float(hype_score_0to100) - conf
    overhype_risk = _clamp_0_100((max(0.0, gap) * 2.5) + (max(0.0, 55.0 - conf) * 0.8))
    underhype_signal = _clamp_0_100((max(0.0, -gap) * 2.2) + (max(0.0, conf - 60.0) * 0.4))

    if overhype_risk >= 70:
        label = "likely_overhyped"
        interp = "Hype substantially exceeds confidence and evidence quality is not keeping pace."
    elif overhype_risk >= 45:
        label = "possible_overhype"
        interp = "Hype is ahead of confidence; monitor for evidence catching up."
    elif underhype_signal >= 60:
        label = "possibly_underhyped"
        interp = "Confidence appears stronger than current hype; intervention may be under-recognized."
    elif abs(gap) <= 10:
        label = "hype_matches_confidence"
        interp = "Hype level is broadly aligned with confidence."
    elif gap > 10:
        label = "hype_ahead_of_confidence"
        interp = "Hype is somewhat ahead of confidence."
    else:
        label = "confidence_ahead_of_hype"
        interp = "Confidence is somewhat ahead of hype."

    return {
        "confidence_score_0to100": round(conf, 1),
        "hype_confidence_gap": round(gap, 1),
        "overhype_risk_0to100": round(overhype_risk, 1),
        "underhype_signal_0to100": round(underhype_signal, 1),
        "alignment_label": label,
        "interpretation": interp,
    }


def build_evidence_pack(
    *,
    corpus: dict[str, Any],
    final_output: dict[str, Any],
    extra_doc_ids: Optional[list[str]] = None,
    max_docs: int = 24,
    max_text_chars: int = 1200,
) -> dict[str, Any]:
    by_id = {
        d.get("id"): d
        for d in (corpus.get("documents", []) or [])
        if isinstance(d, dict) and isinstance(d.get("id"), str)
    }

    doc_ids: list[str] = []
    for did in (final_output.get("top_hype_doc_ids") or []):
        if isinstance(did, str) and did in by_id:
            doc_ids.append(did)
    for did in (final_output.get("top_evidence_doc_ids") or []):
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
You are writing an audit-style analysis report for a hype-to-evidence ratio.

CRITICAL CONSTRAINTS
- You MUST use ONLY the provided evidence_pack documents and the provided final_output numbers.
- Do NOT use outside knowledge.
- Every factual claim about a document must cite a document by its id and use fields present in evidence_pack.
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
Write a report that explains the hype score and hype-to-evidence ratio, then interpret them against confidence.

REQUIRED REPORT SECTIONS (Markdown)
Start EXACTLY with this heading:
# Hype-to-Evidence Ratio Report

1) Executive summary (3-6 bullets)
2) Hype score + ratio and interpretation
3) Source breakdown (social/news vs clinical/human evidence)
4) Top hype examples (3-6 items)
5) Top evidence examples (3-6 items)
6) Confidence alignment and overhype/underhype call
7) Limitations of this run
8) What would reduce hype risk / improve evidence (actionable)

STYLE
- Be concise and specific.
- Use inline citations like (doc: <id>).
- Output Markdown only.
"""


def _deterministic_hype_ratio(
    fetched_documents: list[dict[str, Any]],
    *,
    confidence_score_0to100: Optional[float] = None,
    confidence_source: str = "not_provided",
) -> dict[str, Any]:
    """
    Deterministic, fast analysis from fetched docs.
    """
    by_source: dict[str, int] = {}
    for d in fetched_documents:
        st = str(d.get("source_type") or "unknown")
        by_source[st] = by_source.get(st, 0) + 1

    hype_mass = 0.0
    evidence_mass = 0.0
    hype_docs: list[tuple[float, str]] = []
    evidence_docs: list[tuple[float, str]] = []

    evidence_levels: dict[int, int] = {i: 0 for i in range(1, 7)}
    evidence_human_level_1_3 = 0
    evidence_rct_like = 0
    evidence_meta_like = 0
    evidence_observational = 0

    for d in fetched_documents:
        did = d.get("id")
        if not isinstance(did, str):
            continue
        st = str(d.get("source_type") or "").lower()

        text = _text_blob(d)
        lvl, label, is_human_cand = _infer_level_design(d, text)
        evidence_levels[lvl] = evidence_levels.get(lvl, 0) + 1

        if _is_social(d):
            m = _social_engagement_mass(d)
            hype_mass += m
            hype_docs.append((m, did))
            continue
        if _is_news(d):
            m = _news_mass(d)
            hype_mass += m
            hype_docs.append((m, did))
            continue

        # evidence sources
        if _is_evidence_source(d):
            m = 1.0
            # Slightly upweight concrete human evidence candidates
            if is_human_cand and lvl in (1, 2, 3):
                m = 1.25
            # downweight registry entries with no results posted if present
            if st == "clinicaltrials":
                posted = d.get("date_results_posted")
                status = str(d.get("status") or "").lower()
                if (not posted) and ("completed" in status or "terminated" in status):
                    m *= 0.8
            evidence_mass += m
            evidence_docs.append((m, did))

            if lvl in (1, 2, 3):
                evidence_human_level_1_3 += 1
            if lvl == 2:
                evidence_rct_like += 1
            if lvl == 1:
                evidence_meta_like += 1
            if lvl == 3:
                evidence_observational += 1

    # Compute ratio
    # Use +1 smoothing to avoid div-by-zero while still flagging extreme cases.
    ratio = (hype_mass + 1.0) / (evidence_mass + 1.0)
    hype_share = hype_mass / (hype_mass + evidence_mass + 1e-9)
    hype_dominance_score = 100.0 * hype_share
    hype_score = _compute_hype_score_0to100(
        hype_mass=hype_mass,
        evidence_mass=evidence_mass,
        ratio=ratio,
        hype_share=hype_share,
    )
    confidence_assessment = _assess_hype_vs_confidence(
        hype_score_0to100=float(hype_score["hype_score_0to100"]),
        confidence_score_0to100=confidence_score_0to100,
    )

    # top examples
    hype_docs.sort(key=lambda x: x[0], reverse=True)
    evidence_docs.sort(key=lambda x: x[0], reverse=True)

    return {
        "counts_by_source_type": by_source,
        "hype_mass": round(hype_mass, 3),
        "evidence_mass": round(evidence_mass, 3),
        "hype_to_evidence_ratio": round(ratio, 3),
        "hype_share_0to1": round(hype_share, 4),
        "hype_dominance_score_0to100": round(hype_dominance_score, 1),
        "hype_score_0to100": hype_score["hype_score_0to100"],
        "hype_score_components": hype_score["hype_score_components"],
        "confidence_source": confidence_source,
        "confidence_score_0to100": confidence_assessment["confidence_score_0to100"],
        "hype_confidence_gap": confidence_assessment["hype_confidence_gap"],
        "overhype_risk_0to100": confidence_assessment["overhype_risk_0to100"],
        "underhype_signal_0to100": confidence_assessment["underhype_signal_0to100"],
        "alignment_label": confidence_assessment["alignment_label"],
        "interpretation": confidence_assessment["interpretation"],
        "evidence_breakdown": {
            "level_counts": evidence_levels,
            "human_level_1_3_count": evidence_human_level_1_3,
            "meta_like_count": evidence_meta_like,
            "rct_like_count": evidence_rct_like,
            "observational_like_count": evidence_observational,
        },
        "top_hype_doc_ids": [did for _, did in hype_docs[:8]],
        "top_evidence_doc_ids": [did for _, did in evidence_docs[:8]],
        "notes": [
            "hype sources = source_type social/news with optional engagement weighting",
            "evidence sources = pubmed/europe_pmc/clinicaltrials/regulatory; clinicaltrials completed-without-results are downweighted",
            "hype_score_0to100 combines ratio, share, and volume components",
        ],
    }


@dataclass
class HypeRatioConfig:
    max_new_tokens: int = 900
    report_max_new_tokens: int = 1800
    max_schema_chars: int = 5000
    max_docs_for_final: int = 80


class HypeRatioAnalyzer:
    """Compute hype-to-evidence ratio using the same iterative JSON corpus query tool."""

    _PIPE = None

    def __init__(
        self,
        *,
        hf_token: Optional[str] = None,
        device: str = "cuda",
        model: str = "google/medgemma-1.5-4b-it",
        cfg: Optional[HypeRatioConfig] = None,
    ) -> None:
        self.hf_token = hf_token
        self.device = device
        self.model = model
        self.cfg = cfg or HypeRatioConfig()

    def _ensure_pipe(self) -> None:
        if HypeRatioAnalyzer._PIPE is not None:
            return
        try:
            import torch
            from transformers import pipeline
        except Exception as e:
            raise RuntimeError("transformers/torch are required to run MedGemma") from e

        dtype = torch.float32 if self.device.startswith("cpu") else torch.bfloat16
        HypeRatioAnalyzer._PIPE = pipeline(
            "image-text-to-text",
            model=self.model,
            dtype=dtype,
            device=self.device,
            token=self.hf_token,
        )

    def llm_call(self, prompt: str, *, max_new_tokens: Optional[int] = None) -> str:
        self._ensure_pipe()
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        out = HypeRatioAnalyzer._PIPE(
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
                + "Start with '# Hype-to-Evidence Ratio Report'."
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
        confidence_context: Optional[dict[str, Any]] = None,
        confidence_source: str = "not_provided",
    ) -> dict[str, Any]:
        _ = intervention
        _ = rubric_text
        _ = schema_text
        _ = summary_stats
        confidence_score, extracted_from = _extract_confidence_score(confidence_context)
        if confidence_source == "not_provided" and extracted_from != "not_provided":
            confidence_source = extracted_from
        fetched_evidence = compact_docs_for_final(
            fetched_documents,
            max_docs=self.cfg.max_docs_for_final,
        )
        return _deterministic_hype_ratio(
            fetched_documents=fetched_evidence,
            confidence_score_0to100=confidence_score,
            confidence_source=confidence_source,
        )

    def analyze_from_paths(
        self,
        *,
        intervention: str,
        corpus_path: str,
        stats_path: str,
        schema_path: str,
        rubric_text: str,
        agent_cfg: AgentConfig,
        context_path: Optional[str] = None,
        report_out_path: Optional[str] = None,
        generate_report: bool = True,
        report_max_docs: int = 24,
        report_max_text_chars: int = 1200,
        confidence_context: Optional[dict[str, Any]] = None,
        confidence_source: str = "not_provided",
    ) -> dict[str, Any]:
        query_tool = JsonCorpusQueryTool(
            corpus_path=corpus_path,
            stats_path=stats_path,
            schema_path=schema_path,
            hf_token=self.hf_token,
            device=self.device,
            model=self.model,
            cfg=agent_cfg,
        )
        return self.analyze_with_query_tool(
            query_tool=query_tool,
            rubric_text=rubric_text,
            context_path=context_path,
            report_out_path=report_out_path,
            generate_report=generate_report,
            report_max_docs=report_max_docs,
            report_max_text_chars=report_max_text_chars,
            confidence_context=confidence_context,
            confidence_source=confidence_source,
        )

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
        confidence_context: Optional[dict[str, Any]] = None,
        confidence_source: str = "not_provided",
    ) -> dict[str, Any]:
        context = query_tool.collect(task_text=rubric_text, context_path=context_path)
        final_output = self.analyze(
            intervention=query_tool.intervention,
            rubric_text=rubric_text,
            schema_text=query_tool.schema_text,
            summary_stats=query_tool.stats,
            fetched_documents=context.get("fetched_documents", []),
            confidence_context=confidence_context,
            confidence_source=confidence_source,
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
