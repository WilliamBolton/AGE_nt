"""SQL query safety layer for the AGE-nt MCP server.

Provides query validation, SELECT * rewriting, and LIMIT detection
for the sql_query MCP tool. Keeps safety logic testable independently.
"""

from __future__ import annotations

import re

from loguru import logger

# ── Heavy columns to exclude from SELECT * by default ────────────────────────

HEAVY_COLUMNS = {"raw_response", "source_metadata"}

# All columns in the documents table (from CREATE TABLE in sqlite_store.py).
# Used for rewriting SELECT * → explicit column list.
ALL_COLUMNS = [
    "id", "source_type", "intervention", "title", "abstract", "source_url",
    "date_published", "date_indexed",
    # Source-specific
    "pmid", "nct_id", "doi", "journal", "impact_factor", "phase", "status",
    "enrollment", "sponsor", "peer_reviewed", "server", "platform", "subreddit",
    "outlet",
    # Clinical trial temporal
    "date_registered", "date_started", "date_completed", "date_results_posted",
    # Preprint
    "date_peer_published",
    # Hype
    "sentiment", "reach_estimate", "claims_strength", "score", "comment_count",
    # Europe PMC
    "pmcid", "cited_by_count", "is_open_access", "is_preprint", "is_cochrane",
    "preprint_server",
    # Semantic Scholar
    "paper_id", "citation_count", "influential_citation_count", "tldr",
    # DrugAge
    "species", "strain", "dosage", "dosage_unit", "administration_route",
    "lifespan_change_percent", "significance", "reference_pmid", "gender",
    # NIH Grant
    "project_number", "pi_name", "organisation", "total_funding", "fiscal_year",
    "grant_start", "grant_end", "funding_mechanism", "nih_institute",
    # Patent
    "patent_id", "assignee", "filing_date", "grant_date", "patent_status",
    "patent_office", "claims_count",
    # Regulatory
    "approval_date", "drug_class", "nda_number",
    # Overflow
    "source_metadata",
    # Classification
    "evidence_level", "study_type", "organism", "effect_direction",
    "key_findings", "summary", "hallmarks_addressed", "sample_size", "endpoints",
    # Category
    "category", "subcategory",
    # Raw
    "raw_response",
]

SAFE_COLUMNS = [c for c in ALL_COLUMNS if c not in HEAVY_COLUMNS]


# ── SQL validation ────────────────────────────────────────────────────────────

_BLOCKED_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|DETACH|"
    r"LOAD_EXTENSION|SAVEPOINT|RELEASE|REINDEX|VACUUM|REPLACE|"
    r"BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)

_COMMENT_PATTERN = re.compile(r"--.*?$|/\*.*?\*/", re.MULTILINE | re.DOTALL)


def validate_sql(sql: str) -> tuple[bool, str]:
    """Validate that a SQL query is safe to execute (read-only).

    Returns (is_valid, error_message). error_message is empty if valid.
    """
    # Strip comments first (prevents hiding keywords in comments)
    cleaned = _COMMENT_PATTERN.sub(" ", sql).strip()

    if not cleaned:
        return False, "Empty query"

    # Must start with SELECT or WITH (for CTEs)
    first_word = cleaned.split()[0].upper()
    if first_word not in ("SELECT", "WITH"):
        return False, f"Only SELECT queries are allowed. Got: {first_word}"

    # Check for blocked keywords
    match = _BLOCKED_PATTERNS.search(cleaned)
    if match:
        return False, f"Blocked SQL keyword: {match.group()}"

    # Block semicolons inside the query (prevent multi-statement injection).
    # Allow a single trailing semicolon.
    stripped = cleaned.rstrip(";").strip()
    if ";" in stripped:
        return False, "Multiple statements not allowed"

    return True, ""


# ── SELECT * rewriting ────────────────────────────────────────────────────────

_SELECT_STAR_PATTERN = re.compile(
    r"\bSELECT\s+\*\s+FROM\b", re.IGNORECASE
)


def rewrite_select_star(sql: str) -> str:
    """Rewrite ``SELECT * FROM`` to exclude heavy columns.

    Only handles the simple top-level case. If the pattern doesn't match
    cleanly (subqueries, aliases), returns the original query unchanged.
    """
    if _SELECT_STAR_PATTERN.search(sql):
        cols = ", ".join(SAFE_COLUMNS)
        rewritten = _SELECT_STAR_PATTERN.sub(f"SELECT {cols} FROM", sql, count=1)
        logger.debug("Rewrote SELECT * to exclude heavy columns")
        return rewritten
    return sql


# ── LIMIT detection ───────────────────────────────────────────────────────────

_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)


def has_limit_clause(sql: str) -> bool:
    """Check if the query already contains a LIMIT clause."""
    return bool(_LIMIT_PATTERN.search(sql))
