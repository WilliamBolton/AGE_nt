from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Optional

Action = Literal["search_documents", "get_document", "finish"]

DEFAULT_SOURCE_FIELDS: dict[str, list[str]] = {
    "pubmed": ["id", "source_type", "title", "pmid", "doi", "publication_types", "date_published"],
    "clinicaltrials": [
        "id",
        "source_type",
        "title",
        "nct_id",
        "phase",
        "status",
        "enrollment",
        "date_started",
        "date_completed",
        "date_results_posted",
    ],
    "europe_pmc": ["id", "source_type", "title", "pmid", "pmcid", "doi", "date_published"],
    "nih_grant": [
        "id",
        "source_type",
        "title",
        "project_number",
        "pi_name",
        "organisation",
        "total_funding",
        "fiscal_year",
        "grant_start",
        "grant_end",
        "nih_institute",
        "date_published",
    ],
    "drugage": [
        "id",
        "source_type",
        "title",
        "species",
        "strain",
        "dosage",
        "lifespan_change_percent",
        "significance",
        "reference_pmid",
        "gender",
        "date_published",
    ],
    "regulatory": [
        "id",
        "source_type",
        "title",
        "source_url",
        "date_published",
        "approved_indications",
        "drug_class",
        "warnings_summary",
        "pharmacokinetics_summary",
        "nda_number",
    ],
    "news": [
        "id",
        "source_type",
        "title",
        "outlet",
        "author",
        "date_published",
        "cites_primary_source",
        "primary_source_doi",
        "source_url",
    ],
    "social": [
        "id",
        "source_type",
        "title",
        "platform",
        "subreddit",
        "score",
        "comment_count",
        "date_published",
        "source_url",
    ],
    "patent": [
        "id",
        "source_type",
        "title",
        "patent_id",
        "patent_office",
        "filing_date",
        "date_published",
        "source_url",
    ],
}


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def parse_json_obj(text: str) -> dict[str, Any]:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = s.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(s)):
            ch = s[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    cand = s[start : i + 1]
                    try:
                        obj = json.loads(cand)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        break
        start = s.find("{", start + 1)
    raise ValueError("No valid JSON object in model output.")


def _safe_json_parse(text: str) -> Optional[dict[str, Any]]:
    try:
        return parse_json_obj(text)
    except Exception:
        return None


def _normalize_action(raw_action: Any) -> str:
    if not isinstance(raw_action, str):
        return ""
    s = raw_action.strip().lower()
    allowed = {"search_documents", "get_document", "finish"}
    if s in allowed:
        return s
    if "|" in s:
        for p in [x.strip() for x in s.split("|") if x.strip()]:
            if p in allowed:
                return p
    for token in ("search_documents", "get_document", "finish"):
        if token in s:
            return token
    return ""


def parse_task_hints(task_text: str) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "source_type_allowlist": [],
        "source_type_blocklist": [],
        "min_fetch_docs": None,
        "auto_fetch_per_search": None,
        "min_per_source": None,
    }
    for raw in task_text.splitlines():
        line = raw.strip()
        if not line.startswith("@"):
            continue
        if line.startswith("@source_types:"):
            hints["source_type_allowlist"] = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
        elif line.startswith("@exclude_source_types:"):
            hints["source_type_blocklist"] = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
        elif line.startswith("@min_fetch_docs:"):
            val = re.sub(r"[^0-9]", "", line.split(":", 1)[1])
            hints["min_fetch_docs"] = int(val) if val else None
        elif line.startswith("@auto_fetch_per_search:"):
            val = re.sub(r"[^0-9]", "", line.split(":", 1)[1])
            hints["auto_fetch_per_search"] = int(val) if val else None
        elif line.startswith("@min_per_source:"):
            val = re.sub(r"[^0-9]", "", line.split(":", 1)[1])
            hints["min_per_source"] = int(val) if val else None
    return hints


def _matches(doc: dict[str, Any], key: str, value: Any) -> bool:
    if value is None:
        return True
    dv = doc.get(key)
    if dv is None:
        return False
    if isinstance(dv, list):
        target = str(value).lower()
        return any(str(x).lower() == target for x in dv)
    return str(dv).lower() == str(value).lower()


def build_key_index(corpus: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for doc in corpus.get("documents", []):
        st = str(doc.get("source_type", "unknown"))
        out.setdefault(st, set()).update(doc.keys())
    out["*"] = set()
    for keys in out.values():
        out["*"].update(keys)
    return out


def available_source_types(summary_stats: dict[str, Any], corpus: dict[str, Any]) -> list[str]:
    by_st = summary_stats.get("by_source_type")
    if isinstance(by_st, dict):
        pairs = [(k, v) for k, v in by_st.items() if isinstance(v, int) and v > 0]
        if pairs:
            pairs.sort(key=lambda x: x[1], reverse=True)
            return [k for k, _ in pairs]
    return sorted({str(d.get("source_type")) for d in corpus.get("documents", []) if d.get("source_type")})


def apply_source_type_constraints(
    source_types: list[str],
    *,
    allowlist: list[str],
    blocklist: list[str],
) -> list[str]:
    out = list(source_types)
    if allowlist:
        allow = {x.lower() for x in allowlist}
        out = [x for x in out if x.lower() in allow]
    if blocklist:
        block = {x.lower() for x in blocklist}
        out = [x for x in out if x.lower() not in block]
    return out


def compact_doc(doc: dict[str, Any], max_abstract_chars: int = 2500) -> dict[str, Any]:
    d = dict(doc)
    if "abstract" in d and isinstance(d["abstract"], str) and len(d["abstract"]) > max_abstract_chars:
        d["abstract"] = d["abstract"][:max_abstract_chars] + "..."
    return d


def compact_docs_for_final(docs: list[dict[str, Any]], *, max_docs: int = 60, max_text_chars: int = 1200) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in docs[:max_docs]:
        st = str(d.get("source_type", ""))
        row: dict[str, Any] = {"id": d.get("id"), "source_type": st, "title": d.get("title")}
        for k in ("date_published", "source_url"):
            if k in d:
                row[k] = d.get(k)
        if st == "clinicaltrials":
            for k in (
                "nct_id",
                "phase",
                "status",
                "enrollment",
                "date_started",
                "date_completed",
                "date_results_posted",
                "conditions",
                "results_summary",
                "primary_outcomes",
                "sponsor",
            ):
                if k in d:
                    row[k] = d.get(k)
        else:
            if "abstract" in d:
                txt = str(d.get("abstract") or "")
                row["abstract"] = (txt[:max_text_chars] + "...") if len(txt) > max_text_chars else txt
            for k in (
                "pmid",
                "doi",
                "publication_types",
                "pmcid",
                "outlet",
                "platform",
                "subreddit",
                "score",
                "comment_count",
                "patent_id",
                "patent_office",
                "filing_date",
                "approved_indications",
                "warnings_summary",
                "species",
                "strain",
                "dosage",
                "lifespan_change_percent",
                "significance",
                "reference_pmid",
            ):
                if k in d:
                    row[k] = d.get(k)
        out.append(row)
    return out


def _default_fields_for_source(source_type: str, key_index: dict[str, set[str]]) -> list[str]:
    if source_type in DEFAULT_SOURCE_FIELDS:
        return [f for f in DEFAULT_SOURCE_FIELDS[source_type] if f in key_index.get(source_type, set())]
    base = ["id", "source_type", "title", "date_published"]
    return [f for f in base if f in key_index.get(source_type, set())]


def sanitize_search_args(
    raw_args: dict[str, Any],
    *,
    source_types_allowed: list[str],
    key_index: dict[str, set[str]],
    default_source_type: str,
) -> dict[str, Any]:
    args = dict(raw_args or {})
    out: dict[str, Any] = {}
    allowed_top = {
        "source_type",
        "fields",
        "limit",
        "offset",
        "query",
        "lookup_by",
        "lookup_value",
        "publication_type_contains",
        "status",
        "phase_contains",
    }
    for k, v in args.items():
        if k in allowed_top:
            out[k] = v

    st = str(out.get("source_type", "")).strip() or default_source_type
    if source_types_allowed and st.lower() not in {x.lower() for x in source_types_allowed}:
        st = default_source_type
    out["source_type"] = st

    q = out.get("query")
    if isinstance(q, str):
        qq = q.strip()
        ql = qq.lower()
        bad = ("==", "!=", " and ", " or ", "source_type", "phase_contains", "status")
        if not qq or ql in {"null", "none", "na"} or any(tok in ql for tok in bad):
            out.pop("query", None)
        else:
            out["query"] = qq
    else:
        out.pop("query", None)

    for k in ("publication_type_contains", "status", "phase_contains"):
        v = out.get(k)
        if not isinstance(v, str) or not v.strip() or v.strip().lower() in {"null", "none", "na"}:
            out.pop(k, None)
        else:
            out[k] = v.strip()

    lookup_by = out.get("lookup_by")
    if lookup_by:
        source_keys = key_index.get(st, key_index.get("*", set()))
        identifier_keys = {"id", "pmid", "doi", "nct_id", "paper_id", "patent_id", "reference_pmid", "pmcid"}
        if lookup_by not in source_keys or lookup_by not in identifier_keys:
            out.pop("lookup_by", None)
            out.pop("lookup_value", None)

    try:
        limit = int(out.get("limit", 25))
    except Exception:
        limit = 25
    out["limit"] = max(1, min(100, limit))

    try:
        offset = int(out.get("offset", 0))
    except Exception:
        offset = 0
    out["offset"] = max(0, offset)

    src_keys = key_index.get(st, key_index.get("*", set()))
    fields = out.get("fields")
    if isinstance(fields, list):
        keep = [f for f in fields if isinstance(f, str) and f in src_keys]
    else:
        keep = []
    if "id" in src_keys and "id" not in keep:
        keep = ["id", *keep]
    if not keep:
        keep = _default_fields_for_source(st, key_index)
    out["fields"] = keep or ["id", "source_type", "title"]
    return out


def sanitize_get_args(raw_args: dict[str, Any], *, key_index: dict[str, set[str]]) -> dict[str, Any]:
    args = dict(raw_args or {})
    out: dict[str, Any] = {}
    if isinstance(args.get("doc_id"), str) and args["doc_id"].strip():
        out["doc_id"] = args["doc_id"].strip()
        return out
    lookup_by = args.get("lookup_by")
    lookup_value = args.get("lookup_value")
    if isinstance(lookup_by, str) and lookup_by in key_index.get("*", set()) and lookup_value is not None:
        out["lookup_by"] = lookup_by
        out["lookup_value"] = lookup_value
    return out


def search_documents(
    corpus: dict[str, Any],
    *,
    intervention: Optional[str] = None,
    source_type: Optional[str] = None,
    fields: Optional[list[str]] = None,
    limit: int = 25,
    offset: int = 0,
    query: Optional[str] = None,
    lookup_by: Optional[str] = None,
    lookup_value: Any = None,
    publication_type_contains: Optional[str] = None,
    status: Optional[str] = None,
    phase_contains: Optional[str] = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    docs = corpus.get("documents", [])
    if fields is None:
        fields = ["id", "source_type", "title", "date_published"]

    if intervention and str(corpus.get("intervention", "")).lower() != intervention.lower():
        return []

    if source_type:
        filters["source_type"] = source_type
    if lookup_by:
        filters[lookup_by] = lookup_value
    if status:
        filters["status"] = status

    q = (query or "").strip().lower()
    ptype = (publication_type_contains or "").strip().lower()
    phase_q = (phase_contains or "").strip().lower()

    out: list[dict[str, Any]] = []
    for d in docs:
        if not all(_matches(d, k, v) for k, v in filters.items()):
            continue
        if ptype:
            types = [str(x).lower() for x in d.get("publication_types", [])]
            if not any(ptype in t for t in types):
                continue
        if phase_q:
            phase = str(d.get("phase", "")).lower()
            if phase_q not in phase:
                continue
        if q:
            hay = f"{d.get('title', '')} {d.get('abstract', '')}".lower()
            if q not in hay:
                continue
        out.append({k: d.get(k) for k in fields})
    return out[offset : offset + limit]


def get_document(
    corpus: dict[str, Any],
    *,
    intervention: Optional[str] = None,
    doc_id: Optional[str] = None,
    lookup_by: str = "id",
    lookup_value: Any = None,
) -> Optional[dict[str, Any]]:
    if intervention and str(corpus.get("intervention", "")).lower() != intervention.lower():
        return None
    docs = corpus.get("documents", [])
    if doc_id is not None:
        lookup_by = "id"
        lookup_value = doc_id
    if lookup_value is None:
        return None
    for d in docs:
        if _matches(d, lookup_by, lookup_value):
            return d
    return None


def _count_fetched_by_source(fetched: list[dict[str, Any]]) -> dict[str, int]:
    c: dict[str, int] = {}
    for d in fetched:
        st = str(d.get("source_type") or "")
        if st:
            c[st] = c.get(st, 0) + 1
    return c


def _count_searches_by_source(selected_rows: list[dict[str, Any]]) -> dict[str, int]:
    c: dict[str, int] = {}
    for s in selected_rows:
        st = str((s.get("args") or {}).get("source_type") or "")
        if st:
            c[st] = c.get(st, 0) + 1
    return c


def choose_next_source_type(
    *,
    source_types_allowed: list[str],
    summary_stats: dict[str, Any],
    selected_rows: list[dict[str, Any]],
    fetched_documents: list[dict[str, Any]],
    explore_first: bool = True,
) -> str:
    if not source_types_allowed:
        return "pubmed"
    by_st = summary_stats.get("by_source_type")
    prevalence = {}
    if isinstance(by_st, dict):
        prevalence = {k: int(by_st.get(k) or 0) for k in source_types_allowed}
    searches = _count_searches_by_source(selected_rows)
    fetched = _count_fetched_by_source(fetched_documents)
    if explore_first:
        unseen = [st for st in source_types_allowed if searches.get(st, 0) == 0]
        if unseen:
            unseen.sort(key=lambda st: -prevalence.get(st, 0))
            return unseen[0]

    def _key(st: str) -> tuple[int, int]:
        return (fetched.get(st, 0), -prevalence.get(st, 0))

    return sorted(source_types_allowed, key=_key)[0]


@dataclass
class AgentConfig:
    min_fetch_docs: int = 20
    auto_fetch_per_search: int = 3
    min_per_source: int = 2
    explore_first: bool = True
    max_steps: int = 14
    max_new_tokens: int = 900
    max_schema_chars: int = 12000
    default_blocklist: tuple[str, ...] = ("social", "news")


class JsonCorpusQueryTool:
    """LLM-planned JSON corpus retrieval tool."""

    _PIPE = None

    def __init__(
        self,
        *,
        corpus_path: str,
        stats_path: str,
        schema_path: str,
        hf_token: Optional[str],
        device: str,
        model: str,
        cfg: AgentConfig,
    ) -> None:
        self.corpus_path = corpus_path
        self.stats_path = stats_path
        self.schema_path = schema_path
        self.hf_token = hf_token
        self.device = device
        self.model = model
        self.cfg = cfg

        self.corpus = load_json(corpus_path)
        self.stats = load_json(stats_path)
        self.schema_text = load_text(schema_path)
        if len(self.schema_text) > cfg.max_schema_chars:
            self.schema_text = self.schema_text[: cfg.max_schema_chars] + "\n[TRUNCATED]"

        self.intervention = str(self.corpus.get("intervention", "unknown"))
        self.key_index = build_key_index(self.corpus)
        all_types = available_source_types(self.stats, self.corpus)
        block = set(cfg.default_blocklist)
        self.source_types_allowed = [st for st in all_types if st not in block] or all_types or ["pubmed"]

    def llm_call(self, prompt: str) -> str:
        import torch
        from transformers import pipeline

        dev = self.device
        if dev.startswith("cuda") and not torch.cuda.is_available():
            dev = "cpu"

        if JsonCorpusQueryTool._PIPE is None:
            dtype = torch.float32 if dev.startswith("cpu") else torch.bfloat16
            JsonCorpusQueryTool._PIPE = pipeline(
                "image-text-to-text",
                model=self.model,
                dtype=dtype,
                device=dev,
                token=self.hf_token,
            )

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        out = JsonCorpusQueryTool._PIPE(
            text=messages,
            max_new_tokens=self.cfg.max_new_tokens,
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

    def planner_prompt(
        self,
        *,
        task_text: str,
        context: dict[str, Any],
        source_types_allowed: list[str],
        min_fetch_docs: int,
        min_per_source: int,
    ) -> str:
        fetched = context.get("fetched_documents", [])
        selected = context.get("selected_rows", [])
        fetched_by_source = _count_fetched_by_source(fetched)
        searches_by_source = _count_searches_by_source(selected)
        return f"""
You are a planning agent operating over a LOCAL JSON corpus (not the internet).

You have:
1) A JSON schema reference
2) Summary statistics
3) A rubric/task prompt

CRITICAL BEHAVIOUR:
- Use schema-valid fields for the selected source_type.
- Maintain coverage across allowed source_types; do not get stuck in one source_type.
- Prefer breadth-first when there are unsearched allowed source_types.
- Only use get_document when candidate IDs exist.

Hard constraints:
- Do NOT return finish unless fetched_documents_count >= {min_fetch_docs}.
- Target >= {min_per_source} fetched docs per allowed source_type where feasible.

Intervention: {self.intervention}

Rubric / Task:
{task_text}

Allowed source_types: {source_types_allowed}

Summary statistics:
{json.dumps(self.stats, ensure_ascii=False)}

Schema reference:
{self.schema_text}

Current context:
- searches_by_source_type: {json.dumps(searches_by_source, ensure_ascii=False)}
- fetched_by_source_type: {json.dumps(fetched_by_source, ensure_ascii=False)}
- candidate_doc_ids_count: {len(context.get("candidate_doc_ids", []))}
- fetched_documents_count: {len(fetched)}

Available tools:
1) search_documents(args): source_type, query, publication_type_contains, status, phase_contains, fields, limit, offset
2) get_document(args): doc_id OR lookup_by+lookup_value
3) finish(args): {{}}

Return ONLY JSON:
{{
  "action": "ONE_OF: search_documents, get_document, finish",
  "args": {{}},
  "reason": "1-2 sentences"
}}
"""

    def collect(self, *, task_text: str, context_path: Optional[str] = None) -> dict[str, Any]:
        hints = parse_task_hints(task_text)
        source_types_allowed = apply_source_type_constraints(
            self.source_types_allowed,
            allowlist=hints.get("source_type_allowlist", []) or [],
            blocklist=hints.get("source_type_blocklist", []) or [],
        )
        if not source_types_allowed:
            source_types_allowed = list(self.source_types_allowed)

        min_fetch_docs = hints.get("min_fetch_docs") or self.cfg.min_fetch_docs
        auto_fetch_per_search = hints.get("auto_fetch_per_search") or self.cfg.auto_fetch_per_search
        min_per_source = hints.get("min_per_source") or self.cfg.min_per_source

        context: dict[str, Any] = {
            "intervention": self.intervention,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": None,
            "schema_path": str(self.schema_path),
            "summary_path": str(self.stats_path),
            "task_hints": hints,
            "source_types_allowed": source_types_allowed,
            "selected_rows": [],
            "fetched_documents": [],
            "candidate_doc_ids": [],
            "history": [],
            "final_output": None,
        }
        if context_path and Path(context_path).exists():
            try:
                loaded = load_json(context_path)
                if isinstance(loaded, dict):
                    context = loaded
                    context["task_hints"] = hints
                    context["source_types_allowed"] = source_types_allowed
                    context.setdefault("selected_rows", [])
                    context.setdefault("fetched_documents", [])
                    context.setdefault("candidate_doc_ids", [])
                    context.setdefault("history", [])
                    context["schema_path"] = str(self.schema_path)
                    context["summary_path"] = str(self.stats_path)
            except Exception as e:
                context["history"].append(
                    {
                        "step": "init",
                        "action": "context_reinitialized_from_invalid_json",
                        "reason": str(e),
                    }
                )

        if context_path:
            save_json(context_path, context)

        for step in range(self.cfg.max_steps):
            prompt = self.planner_prompt(
                task_text=task_text,
                context=context,
                source_types_allowed=source_types_allowed,
                min_fetch_docs=min_fetch_docs,
                min_per_source=min_per_source,
            )
            raw = self.llm_call(prompt)
            decision = _safe_json_parse(raw) or {}
            action: Action = _normalize_action(decision.get("action", "")) or "search_documents"
            args = decision.get("args", {}) or {}
            reason = str(decision.get("reason", "")).strip()
            event: dict[str, Any] = {"step": step, "action": action, "args": args, "reason": reason}

            fetched = context.get("fetched_documents", [])
            selected = context.get("selected_rows", [])

            if action == "finish" and len(fetched) < min_fetch_docs:
                action = "search_documents"
                event["overridden_action"] = "finish_blocked_min_fetch_docs"

            scheduled_st = choose_next_source_type(
                source_types_allowed=source_types_allowed,
                summary_stats=self.stats,
                selected_rows=selected,
                fetched_documents=fetched,
                explore_first=self.cfg.explore_first,
            )

            if action == "search_documents":
                sane = sanitize_search_args(
                    args,
                    source_types_allowed=source_types_allowed,
                    key_index=self.key_index,
                    default_source_type=scheduled_st,
                )
                rows = search_documents(self.corpus, intervention=self.intervention, **sane)
                if not rows and sane.get("query"):
                    relaxed = dict(sane)
                    relaxed.pop("query", None)
                    rows = search_documents(self.corpus, intervention=self.intervention, **relaxed)
                    if rows:
                        sane = relaxed

                context["selected_rows"].append({"step": step, "args": sane, "rows": rows})
                event["rows_count"] = len(rows)
                event["effective_args"] = sane

                queue = context.get("candidate_doc_ids", [])
                fetched_ids = {d.get("id") for d in fetched}
                current_row_ids: list[str] = []
                for r in rows:
                    rid = r.get("id")
                    if rid and rid not in fetched_ids and rid not in queue:
                        queue.append(rid)
                    if isinstance(rid, str) and rid not in fetched_ids:
                        current_row_ids.append(rid)

                auto_ids: list[str] = []
                # Prioritize documents from the current search result so each source contributes.
                # This avoids starving later sources when an early-source queue is large.
                auto_target = min(auto_fetch_per_search, len(queue))
                seen_current: set[str] = set()
                preferred: list[str] = []
                for rid in current_row_ids:
                    if rid not in seen_current:
                        preferred.append(rid)
                        seen_current.add(rid)
                for _ in range(auto_target):
                    rid: Optional[str] = None
                    while preferred and rid is None:
                        cand = preferred.pop(0)
                        if cand in queue:
                            queue.remove(cand)
                            rid = cand
                    if rid is None:
                        if not queue:
                            break
                        rid = queue.pop(0)
                    doc = get_document(self.corpus, intervention=self.intervention, doc_id=rid)
                    if not doc:
                        continue
                    did = doc.get("id")
                    if did not in fetched_ids:
                        fetched.append(compact_doc(doc))
                        auto_ids.append(str(did))
                        fetched_ids.add(did)
                event["auto_fetched_doc_ids"] = auto_ids
                event["fetched_documents_count"] = len(fetched)

            elif action == "get_document":
                sane = sanitize_get_args(args, key_index=self.key_index)
                if not sane:
                    queue = context.get("candidate_doc_ids", [])
                    if queue:
                        sane = {"doc_id": queue[0]}
                doc = get_document(self.corpus, intervention=self.intervention, **sane)
                event["effective_args"] = sane
                event["fetched"] = bool(doc)
                if doc:
                    did = doc.get("id")
                    existing = {d.get("id") for d in fetched}
                    if did not in existing:
                        fetched.append(compact_doc(doc))
                    q = context.get("candidate_doc_ids", [])
                    if did in q:
                        q.remove(did)
                event["fetched_documents_count"] = len(fetched)

            else:  # finish
                context["history"].append(event)
                break

            context["history"].append(event)
            context["updated_at"] = datetime.now(UTC).isoformat()
            if context_path:
                save_json(context_path, context)
        return context

    # Backward compatibility
    def run(self, *, task_text: str, context_path: Optional[str] = None) -> dict[str, Any]:
        return self.collect(task_text=task_text, context_path=context_path)
