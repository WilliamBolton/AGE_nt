"""Deterministic summary stats generator for intervention data.

Reads the main document JSON for an intervention and produces a
summary_stats.json with counts, date ranges, and source-specific
highlights. No LLM calls — pure aggregation.

Can run standalone or as the final step of the ingest pipeline.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from loguru import logger

from src.config import settings


def generate_summary(intervention: str, data_dir: Path | None = None) -> dict:
    """Generate deterministic summary stats from the documents JSON.

    Args:
        intervention: Canonical intervention name (lowercase).
        data_dir: Base data directory. Defaults to settings.data_dir.

    Returns:
        Summary stats dict, also written to data/summary/{intervention}.json.
    """
    data_dir = data_dir or settings.documents_dir.parent
    doc_path = data_dir / "documents" / f"{intervention}.json"

    if not doc_path.exists():
        logger.warning(f"No document file found at {doc_path}")
        return {}

    with open(doc_path) as f:
        envelope = json.load(f)

    docs = envelope.get("documents", [])
    if not docs:
        logger.warning(f"No documents found for '{intervention}'")
        return {}

    summary = _build_summary(intervention, envelope, docs, data_dir)

    # Write output
    out_dir = data_dir / "summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{intervention}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    logger.info(f"Summary stats written to {out_path}")

    return summary


def _build_summary(
    intervention: str,
    envelope: dict,
    docs: list[dict],
    data_dir: Path,
) -> dict:
    """Build the full summary stats dict."""
    today = date.today().isoformat()

    # -- Source counts --
    source_counts = Counter(d["source_type"] for d in docs)

    # -- Date range --
    pub_dates = _parse_dates([d.get("date_published") for d in docs])
    earliest = min(pub_dates).isoformat() if pub_dates else None
    latest = max(pub_dates).isoformat() if pub_dates else None

    # -- Year distribution --
    year_counts: dict[str, int] = {}
    for dt in pub_dates:
        yr = str(dt.year)
        year_counts[yr] = year_counts.get(yr, 0) + 1
    year_counts = dict(sorted(year_counts.items()))

    # -- Source-specific breakdowns --
    pubmed = _pubmed_stats([d for d in docs if d["source_type"] == "pubmed"])
    trials = _clinical_trials_stats([d for d in docs if d["source_type"] == "clinicaltrials"])
    drugage = _drugage_stats([d for d in docs if d["source_type"] == "drugage"])
    grants = _grant_stats([d for d in docs if d["source_type"] == "nih_grant"])
    patents = _patent_stats([d for d in docs if d["source_type"] == "patent"])
    regulatory = _regulatory_stats([d for d in docs if d["source_type"] == "regulatory"])
    news = _news_stats([d for d in docs if d["source_type"] == "news"])
    social = _social_stats([d for d in docs if d["source_type"] == "social"])
    europe_pmc = _europe_pmc_stats([d for d in docs if d["source_type"] == "europe_pmc"])
    semantic_scholar = _semantic_scholar_stats([d for d in docs if d["source_type"] == "semantic_scholar"])

    # -- Trends summary (if available) --
    trends = _trends_summary(intervention, data_dir)

    # -- Unique authors/journals across academic sources --
    academic_types = {"pubmed", "europe_pmc", "semantic_scholar", "preprint"}
    academic_docs = [d for d in docs if d["source_type"] in academic_types]
    all_authors = set()
    all_journals = set()
    for d in academic_docs:
        for a in d.get("authors", []):
            if a:
                all_authors.add(a)
        j = d.get("journal")
        if j:
            all_journals.add(j)

    return {
        "intervention": intervention,
        "aliases": envelope.get("aliases", []),
        "generated_at": today,
        "total_documents": len(docs),
        "by_source_type": dict(source_counts.most_common()),
        "date_range": {
            "earliest": earliest,
            "latest": latest,
        },
        "by_year": year_counts,
        "academic": {
            "unique_authors": len(all_authors),
            "unique_journals": len(all_journals),
            "top_journals": _top_n(
                Counter(
                    d.get("journal")
                    for d in academic_docs
                    if d.get("journal")
                ),
                10,
            ),
        },
        "pubmed": pubmed,
        "clinical_trials": trials,
        "drugage": drugage,
        "grants": grants,
        "patents": patents,
        "regulatory": regulatory,
        "news": news,
        "social": social,
        "europe_pmc": europe_pmc,
        "semantic_scholar": semantic_scholar,
        "trends": trends,
    }


# ── Source-specific stats ────────────────────────────────────────────────────


def _pubmed_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    pub_types = Counter()
    mesh_terms = Counter()
    peer_reviewed = 0
    has_doi = 0

    for d in docs:
        for pt in d.get("publication_types", []):
            pub_types[pt] += 1
        for mt in d.get("mesh_terms", []):
            mesh_terms[mt] += 1
        if d.get("peer_reviewed"):
            peer_reviewed += 1
        if d.get("doi"):
            has_doi += 1

    return {
        "count": len(docs),
        "peer_reviewed": peer_reviewed,
        "with_doi": has_doi,
        "publication_types": dict(pub_types.most_common()),
        "top_mesh_terms": _top_n(mesh_terms, 15),
    }


def _clinical_trials_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    phases = Counter(d.get("phase") or "Unknown" for d in docs)
    statuses = Counter(d.get("status") or "Unknown" for d in docs)
    enrollments = [d.get("enrollment") for d in docs if d.get("enrollment")]
    sponsors = Counter(d.get("sponsor") for d in docs if d.get("sponsor"))
    conditions = Counter()
    for d in docs:
        for c in d.get("conditions", []):
            conditions[c] += 1

    has_results = sum(1 for d in docs if d.get("results_summary"))

    return {
        "count": len(docs),
        "by_phase": dict(phases.most_common()),
        "by_status": dict(statuses.most_common()),
        "total_enrollment": sum(enrollments) if enrollments else 0,
        "median_enrollment": _median(enrollments) if enrollments else None,
        "with_results": has_results,
        "top_sponsors": _top_n(sponsors, 10),
        "top_conditions": _top_n(conditions, 10),
    }


def _drugage_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    species = Counter(d.get("species", "Unknown") for d in docs)
    changes = [d.get("lifespan_change_percent") for d in docs if d.get("lifespan_change_percent") is not None]
    significant = sum(1 for d in docs if d.get("significance") == "significant")
    genders = Counter(d.get("gender") for d in docs if d.get("gender"))

    positive = [c for c in changes if c > 0]
    negative = [c for c in changes if c < 0]

    return {
        "count": len(docs),
        "by_species": dict(species.most_common()),
        "significant_results": significant,
        "by_gender": dict(genders.most_common()),
        "lifespan_change": {
            "positive_count": len(positive),
            "negative_count": len(negative),
            "null_count": len(changes) - len(positive) - len(negative),
            "mean_change": round(sum(changes) / len(changes), 2) if changes else None,
            "max_extension": round(max(positive), 2) if positive else None,
            "max_reduction": round(min(negative), 2) if negative else None,
        },
    }


def _grant_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    fundings = [d.get("total_funding") for d in docs if d.get("total_funding")]
    mechanisms = Counter(d.get("funding_mechanism") for d in docs if d.get("funding_mechanism"))
    institutes = Counter(d.get("nih_institute") for d in docs if d.get("nih_institute"))
    orgs = Counter(d.get("organisation") for d in docs if d.get("organisation"))
    years = Counter(d.get("fiscal_year") for d in docs if d.get("fiscal_year"))

    return {
        "count": len(docs),
        "total_funding_usd": round(sum(fundings), 2) if fundings else 0,
        "mean_funding_usd": round(sum(fundings) / len(fundings), 2) if fundings else None,
        "by_mechanism": dict(mechanisms.most_common()),
        "by_institute": dict(institutes.most_common()),
        "top_organisations": _top_n(orgs, 10),
        "by_fiscal_year": dict(sorted(years.items())),
    }


def _patent_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    statuses = Counter(d.get("patent_status") for d in docs if d.get("patent_status"))
    offices = Counter(d.get("patent_office") for d in docs if d.get("patent_office"))
    assignees = Counter(d.get("assignee") for d in docs if d.get("assignee"))

    return {
        "count": len(docs),
        "by_status": dict(statuses.most_common()),
        "by_office": dict(offices.most_common()),
        "top_assignees": _top_n(assignees, 10),
    }


def _regulatory_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    indications: Counter = Counter()
    for d in docs:
        for ind in d.get("approved_indications", []):
            indications[ind] += 1

    drug_classes = Counter(d.get("drug_class") for d in docs if d.get("drug_class"))

    return {
        "count": len(docs),
        "approved_indications": dict(indications.most_common()),
        "drug_classes": dict(drug_classes.most_common()),
    }


def _news_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    sentiments = [d.get("sentiment") for d in docs if d.get("sentiment") is not None]
    claims = Counter(d.get("claims_strength") for d in docs if d.get("claims_strength"))
    cites_source = sum(1 for d in docs if d.get("cites_primary_source"))
    outlets = Counter(d.get("outlet") for d in docs if d.get("outlet"))

    return {
        "count": len(docs),
        "mean_sentiment": round(sum(sentiments) / len(sentiments), 3) if sentiments else None,
        "claims_strength": dict(claims.most_common()),
        "cites_primary_source": cites_source,
        "top_outlets": _top_n(outlets, 10),
    }


def _social_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    platforms = Counter(d.get("platform") for d in docs if d.get("platform"))
    subreddits = Counter(d.get("subreddit") for d in docs if d.get("subreddit"))
    scores = [d.get("score") for d in docs if d.get("score") is not None]
    comments = [d.get("comment_count") for d in docs if d.get("comment_count") is not None]
    sentiments = [d.get("sentiment") for d in docs if d.get("sentiment") is not None]

    return {
        "count": len(docs),
        "by_platform": dict(platforms.most_common()),
        "top_subreddits": _top_n(subreddits, 10),
        "total_score": sum(scores) if scores else 0,
        "mean_score": round(sum(scores) / len(scores), 1) if scores else None,
        "total_comments": sum(comments) if comments else 0,
        "mean_sentiment": round(sum(sentiments) / len(sentiments), 3) if sentiments else None,
    }


def _europe_pmc_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    citations = [d.get("cited_by_count") for d in docs if d.get("cited_by_count") is not None]
    open_access = sum(1 for d in docs if d.get("is_open_access"))
    preprints = sum(1 for d in docs if d.get("is_preprint"))
    cochrane = sum(1 for d in docs if d.get("is_cochrane"))

    return {
        "count": len(docs),
        "total_citations": sum(citations) if citations else 0,
        "mean_citations": round(sum(citations) / len(citations), 1) if citations else None,
        "max_citations": max(citations) if citations else None,
        "open_access": open_access,
        "preprints": preprints,
        "cochrane_reviews": cochrane,
    }


def _semantic_scholar_stats(docs: list[dict]) -> dict:
    if not docs:
        return {"count": 0}

    citations = [d.get("citation_count") for d in docs if d.get("citation_count") is not None]
    influential = [d.get("influential_citation_count") for d in docs if d.get("influential_citation_count") is not None]
    open_access = sum(1 for d in docs if d.get("is_open_access"))

    return {
        "count": len(docs),
        "total_citations": sum(citations) if citations else 0,
        "mean_citations": round(sum(citations) / len(citations), 1) if citations else None,
        "max_citations": max(citations) if citations else None,
        "total_influential_citations": sum(influential) if influential else 0,
        "open_access": open_access,
    }


# ── Cross-source data ────────────────────────────────────────────────────────


def _trends_summary(intervention: str, data_dir: Path) -> dict | None:
    """Extract key numbers from trends JSON if it exists."""
    path = data_dir / "trends" / f"{intervention}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "peak_interest": data.get("peak_interest"),
            "peak_date": data.get("peak_date"),
            "current_interest": data.get("current_interest"),
            "data_points_count": len(data.get("data_points", [])),
        }
    except Exception:
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_dates(raw: list[str | None]) -> list[date]:
    """Parse date strings, skipping None/invalid."""
    results = []
    for val in raw:
        if not val:
            continue
        try:
            results.append(date.fromisoformat(str(val)))
        except (ValueError, TypeError):
            pass
    return results


def _median(values: list[int | float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def _top_n(counter: Counter, n: int) -> dict:
    """Return top N items from a counter as a dict."""
    return dict(counter.most_common(n))
