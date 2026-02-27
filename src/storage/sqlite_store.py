"""Async SQLite storage for structured document queries.

Mirrors the JSON store but enables SQL queries: filtering, aggregation,
temporal analysis. Uses aiosqlite for async support.
"""

from __future__ import annotations

import json
from datetime import date

import aiosqlite
from loguru import logger

from src.config import settings
from src.schema.document import (
    Document,
    DocumentListAdapter,
    SourceType,
)

CREATE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    intervention TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    source_url TEXT UNIQUE,
    date_published DATE NOT NULL,
    date_indexed DATE NOT NULL,

    -- Source-specific (nullable)
    pmid TEXT,
    nct_id TEXT,
    doi TEXT,
    journal TEXT,
    impact_factor REAL,
    phase TEXT,
    status TEXT,
    enrollment INTEGER,
    sponsor TEXT,
    peer_reviewed BOOLEAN,
    server TEXT,
    platform TEXT,
    subreddit TEXT,
    outlet TEXT,

    -- Clinical trial temporal fields
    date_registered DATE,
    date_started DATE,
    date_completed DATE,
    date_results_posted DATE,

    -- Preprint
    date_peer_published DATE,

    -- Hype fields (news/social)
    sentiment REAL,
    reach_estimate INTEGER,
    claims_strength TEXT,
    score INTEGER,
    comment_count INTEGER,

    -- Europe PMC
    pmcid TEXT,
    cited_by_count INTEGER,
    is_open_access BOOLEAN,
    is_preprint BOOLEAN,
    is_cochrane BOOLEAN,
    preprint_server TEXT,

    -- Semantic Scholar
    paper_id TEXT,
    citation_count INTEGER,
    influential_citation_count INTEGER,
    tldr TEXT,

    -- DrugAge
    species TEXT,
    strain TEXT,
    dosage TEXT,
    dosage_unit TEXT,
    administration_route TEXT,
    lifespan_change_percent REAL,
    significance TEXT,
    reference_pmid TEXT,
    gender TEXT,

    -- NIH Grant
    project_number TEXT,
    pi_name TEXT,
    organisation TEXT,
    total_funding REAL,
    fiscal_year INTEGER,
    grant_start DATE,
    grant_end DATE,
    funding_mechanism TEXT,
    nih_institute TEXT,

    -- Patent
    patent_id TEXT,
    assignee TEXT,
    filing_date DATE,
    grant_date DATE,
    patent_status TEXT,
    patent_office TEXT,
    claims_count INTEGER,

    -- Regulatory
    approval_date DATE,
    drug_class TEXT,
    nda_number TEXT,

    -- Overflow: lists and source-specific extras
    source_metadata JSON,

    -- Classification fields (NULL at ingest, filled by reasoning agents)
    evidence_level INTEGER,
    study_type TEXT,
    organism TEXT,
    effect_direction TEXT,
    key_findings JSON,
    summary TEXT,
    hallmarks_addressed JSON,
    sample_size INTEGER,
    endpoints JSON,

    -- Raw API response
    raw_response JSON
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_intervention ON documents(intervention)",
    "CREATE INDEX IF NOT EXISTS idx_source_type ON documents(source_type)",
    "CREATE INDEX IF NOT EXISTS idx_date_published ON documents(date_published)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_level ON documents(evidence_level)",
    "CREATE INDEX IF NOT EXISTS idx_organism ON documents(organism)",
    "CREATE INDEX IF NOT EXISTS idx_nct_id ON documents(nct_id)",
    "CREATE INDEX IF NOT EXISTS idx_pmid ON documents(pmid)",
    "CREATE INDEX IF NOT EXISTS idx_intervention_source ON documents(intervention, source_type)",
    "CREATE INDEX IF NOT EXISTS idx_intervention_date ON documents(intervention, date_published)",
    "CREATE INDEX IF NOT EXISTS idx_doi ON documents(doi)",
    "CREATE INDEX IF NOT EXISTS idx_project_number ON documents(project_number)",
]


def _doc_to_row(doc: Document) -> dict:
    """Convert a typed Document to a flat dict for SQL insertion."""
    # Start with base fields
    row: dict = {
        "id": doc.id,
        "source_type": doc.source_type.value,
        "intervention": doc.intervention,
        "title": doc.title,
        "abstract": doc.abstract,
        "source_url": doc.source_url,
        "date_published": doc.date_published.isoformat(),
        "date_indexed": doc.date_indexed.isoformat(),
        # Classification (nullable)
        "evidence_level": doc.evidence_level.value if doc.evidence_level else None,
        "study_type": doc.study_type,
        "organism": doc.organism,
        "effect_direction": doc.effect_direction.value if doc.effect_direction else None,
        "key_findings": json.dumps(doc.key_findings),
        "summary": doc.summary,
        "hallmarks_addressed": json.dumps([h.value for h in doc.hallmarks_addressed]),
        "sample_size": doc.sample_size,
        "endpoints": json.dumps(doc.endpoints),
        "raw_response": json.dumps(doc.raw_response),
    }

    # Source-specific metadata (lists, etc.)
    source_meta: dict = {
        "intervention_aliases": doc.intervention_aliases,
    }

    # Source-specific scalar fields
    if doc.source_type == SourceType.PUBMED:
        row["pmid"] = doc.pmid  # type: ignore[attr-defined]
        row["doi"] = doc.doi  # type: ignore[attr-defined]
        row["journal"] = doc.journal  # type: ignore[attr-defined]
        row["impact_factor"] = doc.impact_factor  # type: ignore[attr-defined]
        row["peer_reviewed"] = doc.peer_reviewed  # type: ignore[attr-defined]
        source_meta["authors"] = doc.authors  # type: ignore[attr-defined]
        source_meta["mesh_terms"] = doc.mesh_terms  # type: ignore[attr-defined]
        source_meta["publication_types"] = doc.publication_types  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.CLINICAL_TRIALS:
        row["nct_id"] = doc.nct_id  # type: ignore[attr-defined]
        row["phase"] = doc.phase  # type: ignore[attr-defined]
        row["status"] = doc.status  # type: ignore[attr-defined]
        row["enrollment"] = doc.enrollment  # type: ignore[attr-defined]
        row["sponsor"] = doc.sponsor  # type: ignore[attr-defined]
        row["date_registered"] = _date_iso(doc.date_registered)  # type: ignore[attr-defined]
        row["date_started"] = _date_iso(doc.date_started)  # type: ignore[attr-defined]
        row["date_completed"] = _date_iso(doc.date_completed)  # type: ignore[attr-defined]
        row["date_results_posted"] = _date_iso(doc.date_results_posted)  # type: ignore[attr-defined]
        source_meta["conditions"] = doc.conditions  # type: ignore[attr-defined]
        source_meta["primary_outcomes"] = doc.primary_outcomes  # type: ignore[attr-defined]
        source_meta["results_summary"] = doc.results_summary  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.PREPRINT:
        row["doi"] = doc.doi  # type: ignore[attr-defined]
        row["server"] = doc.server  # type: ignore[attr-defined]
        row["peer_reviewed"] = doc.peer_reviewed  # type: ignore[attr-defined]
        row["date_peer_published"] = _date_iso(doc.date_peer_published)  # type: ignore[attr-defined]
        source_meta["authors"] = doc.authors  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.NEWS:
        row["outlet"] = doc.outlet  # type: ignore[attr-defined]
        row["sentiment"] = doc.sentiment  # type: ignore[attr-defined]
        row["reach_estimate"] = doc.reach_estimate  # type: ignore[attr-defined]
        row["claims_strength"] = doc.claims_strength  # type: ignore[attr-defined]
        source_meta["author"] = getattr(doc, "author", None)
        source_meta["cites_primary_source"] = getattr(doc, "cites_primary_source", False)
        source_meta["primary_source_doi"] = getattr(doc, "primary_source_doi", None)

    elif doc.source_type == SourceType.SOCIAL:
        row["platform"] = doc.platform  # type: ignore[attr-defined]
        row["subreddit"] = doc.subreddit  # type: ignore[attr-defined]
        row["score"] = doc.score  # type: ignore[attr-defined]
        row["comment_count"] = doc.comment_count  # type: ignore[attr-defined]
        row["sentiment"] = doc.sentiment  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.EUROPE_PMC:
        row["pmid"] = doc.pmid  # type: ignore[attr-defined]
        row["pmcid"] = doc.pmcid  # type: ignore[attr-defined]
        row["doi"] = doc.doi  # type: ignore[attr-defined]
        row["journal"] = doc.journal  # type: ignore[attr-defined]
        row["cited_by_count"] = doc.cited_by_count  # type: ignore[attr-defined]
        row["is_open_access"] = doc.is_open_access  # type: ignore[attr-defined]
        row["peer_reviewed"] = doc.peer_reviewed  # type: ignore[attr-defined]
        row["is_preprint"] = doc.is_preprint  # type: ignore[attr-defined]
        row["is_cochrane"] = doc.is_cochrane  # type: ignore[attr-defined]
        row["preprint_server"] = doc.preprint_server  # type: ignore[attr-defined]
        source_meta["authors"] = doc.authors  # type: ignore[attr-defined]
        source_meta["publication_types"] = doc.publication_types  # type: ignore[attr-defined]
        source_meta["mesh_terms"] = doc.mesh_terms  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.SEMANTIC_SCHOLAR:
        row["paper_id"] = doc.paper_id  # type: ignore[attr-defined]
        row["doi"] = doc.doi  # type: ignore[attr-defined]
        row["journal"] = doc.journal  # type: ignore[attr-defined]
        row["citation_count"] = doc.citation_count  # type: ignore[attr-defined]
        row["influential_citation_count"] = doc.influential_citation_count  # type: ignore[attr-defined]
        row["tldr"] = doc.tldr  # type: ignore[attr-defined]
        row["is_open_access"] = doc.is_open_access  # type: ignore[attr-defined]
        source_meta["authors"] = doc.authors  # type: ignore[attr-defined]
        source_meta["publication_types"] = doc.publication_types  # type: ignore[attr-defined]
        source_meta["year"] = doc.year  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.DRUGAGE:
        row["species"] = doc.species  # type: ignore[attr-defined]
        row["strain"] = doc.strain  # type: ignore[attr-defined]
        row["dosage"] = doc.dosage  # type: ignore[attr-defined]
        row["dosage_unit"] = doc.dosage_unit  # type: ignore[attr-defined]
        row["administration_route"] = doc.administration_route  # type: ignore[attr-defined]
        row["lifespan_change_percent"] = doc.lifespan_change_percent  # type: ignore[attr-defined]
        row["significance"] = doc.significance  # type: ignore[attr-defined]
        row["reference_pmid"] = doc.reference_pmid  # type: ignore[attr-defined]
        row["gender"] = doc.gender  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.NIH_GRANT:
        row["project_number"] = doc.project_number  # type: ignore[attr-defined]
        row["pi_name"] = doc.pi_name  # type: ignore[attr-defined]
        row["organisation"] = doc.organisation  # type: ignore[attr-defined]
        row["total_funding"] = doc.total_funding  # type: ignore[attr-defined]
        row["fiscal_year"] = doc.fiscal_year  # type: ignore[attr-defined]
        row["grant_start"] = _date_iso(doc.grant_start)  # type: ignore[attr-defined]
        row["grant_end"] = _date_iso(doc.grant_end)  # type: ignore[attr-defined]
        row["funding_mechanism"] = doc.funding_mechanism  # type: ignore[attr-defined]
        row["nih_institute"] = doc.nih_institute  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.PATENT:
        row["patent_id"] = doc.patent_id  # type: ignore[attr-defined]
        row["assignee"] = doc.assignee  # type: ignore[attr-defined]
        row["filing_date"] = _date_iso(doc.filing_date)  # type: ignore[attr-defined]
        row["grant_date"] = _date_iso(doc.grant_date)  # type: ignore[attr-defined]
        row["patent_status"] = doc.patent_status  # type: ignore[attr-defined]
        row["patent_office"] = doc.patent_office  # type: ignore[attr-defined]
        row["claims_count"] = doc.claims_count  # type: ignore[attr-defined]
        source_meta["inventors"] = doc.inventors  # type: ignore[attr-defined]

    elif doc.source_type == SourceType.REGULATORY:
        row["approval_date"] = _date_iso(doc.approval_date)  # type: ignore[attr-defined]
        row["drug_class"] = doc.drug_class  # type: ignore[attr-defined]
        row["nda_number"] = doc.nda_number  # type: ignore[attr-defined]
        source_meta["approved_indications"] = doc.approved_indications  # type: ignore[attr-defined]
        source_meta["warnings_summary"] = doc.warnings_summary  # type: ignore[attr-defined]
        source_meta["pharmacokinetics_summary"] = doc.pharmacokinetics_summary  # type: ignore[attr-defined]

    row["source_metadata"] = json.dumps(source_meta)
    return row


def _date_iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


class SQLiteStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(settings.sqlite_path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create connection and ensure tables + indexes exist."""
        from pathlib import Path

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(CREATE_DOCUMENTS_TABLE)
        for idx_sql in CREATE_INDEXES:
            await self._db.execute(idx_sql)
        await self._db.commit()
        logger.info(f"SQLite initialized at {self.db_path}")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def insert_document(self, doc: Document) -> None:
        """Insert or replace a single document."""
        assert self._db is not None
        row = _doc_to_row(doc)
        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row.keys())
        sql = f"INSERT OR REPLACE INTO documents ({cols}) VALUES ({placeholders})"
        await self._db.execute(sql, row)
        await self._db.commit()

    async def insert_documents(self, docs: list[Document]) -> None:
        """Batch insert documents."""
        assert self._db is not None
        if not docs:
            return
        for doc in docs:
            row = _doc_to_row(doc)
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f":{k}" for k in row.keys())
            sql = f"INSERT OR REPLACE INTO documents ({cols}) VALUES ({placeholders})"
            await self._db.execute(sql, row)
        await self._db.commit()

    async def document_exists(self, source_url: str) -> bool:
        """Check if a document with this source_url already exists."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT 1 FROM documents WHERE source_url = ? LIMIT 1", (source_url,)
        )
        return await cursor.fetchone() is not None

    async def query_documents(
        self,
        intervention: str | None = None,
        source_type: str | None = None,
        evidence_levels: list[int] | None = None,
        organism: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query documents with flexible filtering. Returns raw dicts."""
        assert self._db is not None
        conditions: list[str] = []
        params: list = []

        if intervention:
            conditions.append("intervention = ?")
            params.append(intervention.lower())
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if evidence_levels:
            placeholders = ",".join("?" * len(evidence_levels))
            conditions.append(f"evidence_level IN ({placeholders})")
            params.extend(evidence_levels)
        if organism:
            conditions.append("organism = ?")
            params.append(organism)
        if date_from:
            conditions.append("date_published >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date_published <= ?")
            params.append(date_to)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM documents WHERE {where} ORDER BY date_published DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_interventions(self) -> list[str]:
        """Return distinct intervention names."""
        assert self._db is not None
        cursor = await self._db.execute("SELECT DISTINCT intervention FROM documents ORDER BY intervention")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def count_documents(self, intervention: str | None = None) -> int:
        assert self._db is not None
        if intervention:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM documents WHERE intervention = ?", (intervention.lower(),)
            )
        else:
            cursor = await self._db.execute("SELECT COUNT(*) FROM documents")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_timeline(self, intervention: str) -> dict:
        """Temporal aggregation: count of studies per year, grouped by evidence level."""
        assert self._db is not None
        cursor = await self._db.execute(
            """
            SELECT strftime('%Y', date_published) as year,
                   evidence_level,
                   COUNT(*) as count
            FROM documents
            WHERE intervention = ?
            GROUP BY year, evidence_level
            ORDER BY year
            """,
            (intervention.lower(),),
        )
        rows = await cursor.fetchall()
        timeline: dict = {}
        for row in rows:
            year = row[0]
            level = row[1]
            count = row[2]
            if year not in timeline:
                timeline[year] = {}
            level_key = f"level_{level}" if level else "unclassified"
            timeline[year][level_key] = count
        return timeline

    async def update_classifications(self, doc_id: str, classifications: dict) -> None:
        """Write reasoning agent outputs back to a document."""
        assert self._db is not None
        allowed = {
            "evidence_level", "study_type", "organism", "effect_direction",
            "key_findings", "summary", "hallmarks_addressed", "sample_size", "endpoints",
        }
        updates = {k: v for k, v in classifications.items() if k in allowed}
        if not updates:
            return
        # Serialize lists to JSON
        for k in ("key_findings", "hallmarks_addressed", "endpoints"):
            if k in updates and isinstance(updates[k], list):
                updates[k] = json.dumps(updates[k])

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["doc_id"] = doc_id
        await self._db.execute(
            f"UPDATE documents SET {set_clause} WHERE id = :doc_id", updates
        )
        await self._db.commit()
