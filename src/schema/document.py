from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


# ── Enums ────────────────────────────────────────────────────────────────────


class SourceType(str, Enum):
    PUBMED = "pubmed"
    CLINICAL_TRIALS = "clinicaltrials"
    PREPRINT = "preprint"
    NEWS = "news"
    SOCIAL = "social"
    EUROPE_PMC = "europe_pmc"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    DRUGAGE = "drugage"
    NIH_GRANT = "nih_grant"
    GOOGLE_TRENDS = "google_trends"
    PATENT = "patent"
    REGULATORY = "regulatory"


class EvidenceLevel(int, Enum):
    """Evidence hierarchy for aging interventions.
    Classified by reasoning agents AFTER ingest, not at scrape time."""

    SYSTEMATIC_REVIEW = 1
    RCT = 2
    OBSERVATIONAL = 3
    ANIMAL = 4
    IN_VITRO = 5
    IN_SILICO = 6


class EffectDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NULL = "null"
    MIXED = "mixed"


class AgingHallmark(str, Enum):
    GENOMIC_INSTABILITY = "genomic_instability"
    TELOMERE_ATTRITION = "telomere_attrition"
    EPIGENETIC_ALTERATIONS = "epigenetic_alterations"
    LOSS_OF_PROTEOSTASIS = "loss_of_proteostasis"
    DISABLED_MACROAUTOPHAGY = "disabled_macroautophagy"
    DEREGULATED_NUTRIENT_SENSING = "deregulated_nutrient_sensing"
    MITOCHONDRIAL_DYSFUNCTION = "mitochondrial_dysfunction"
    CELLULAR_SENESCENCE = "cellular_senescence"
    STEM_CELL_EXHAUSTION = "stem_cell_exhaustion"
    ALTERED_INTERCELLULAR_COMMUNICATION = "altered_intercellular_communication"
    CHRONIC_INFLAMMATION = "chronic_inflammation"
    DYSBIOSIS = "dysbiosis"


# ── Base Document ────────────────────────────────────────────────────────────


class BaseDocument(BaseModel):
    """Common fields shared by ALL document sources."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: SourceType
    intervention: str  # Normalised canonical name (lowercase)
    intervention_aliases: list[str] = Field(default_factory=list)
    title: str
    abstract: str  # Or description for non-paper sources
    source_url: str

    # Universal temporal field
    date_published: date
    date_indexed: date = Field(default_factory=date.today)

    # RAW API response — insurance policy, never lose data
    raw_response: dict = Field(default_factory=dict, exclude=True)

    # === FIELDS POPULATED LATER BY REASONING AGENTS, NOT AT INGEST ===
    # Excluded from JSON serialization — stored separately in data/classifications/
    # Still accessible as attributes (used by SQLite _doc_to_row)
    evidence_level: EvidenceLevel | None = Field(default=None, exclude=True)
    study_type: str | None = Field(default=None, exclude=True)
    organism: str | None = Field(default=None, exclude=True)
    effect_direction: EffectDirection | None = Field(default=None, exclude=True)
    key_findings: list[str] = Field(default_factory=list, exclude=True)
    summary: str | None = Field(default=None, exclude=True)
    hallmarks_addressed: list[AgingHallmark] = Field(default_factory=list, exclude=True)
    sample_size: int | None = Field(default=None, exclude=True)
    endpoints: list[str] = Field(default_factory=list, exclude=True)


# ── Source-Specific Models ───────────────────────────────────────────────────


class PubMedDocument(BaseDocument):
    """A paper from PubMed."""

    source_type: Literal[SourceType.PUBMED] = SourceType.PUBMED
    pmid: str
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    impact_factor: float | None = None
    mesh_terms: list[str] = Field(default_factory=list)
    publication_types: list[str] = Field(default_factory=list)
    peer_reviewed: bool = True


class ClinicalTrialDocument(BaseDocument):
    """A trial record from ClinicalTrials.gov."""

    source_type: Literal[SourceType.CLINICAL_TRIALS] = SourceType.CLINICAL_TRIALS
    nct_id: str
    phase: str | None = None
    status: str | None = None
    enrollment: int | None = None
    sponsor: str | None = None
    conditions: list[str] = Field(default_factory=list)
    primary_outcomes: list[str] = Field(default_factory=list)
    results_summary: str | None = None

    # Temporal goldmine — 4 dates tell the full lifecycle of a trial
    date_registered: date | None = None
    date_started: date | None = None
    date_completed: date | None = None
    date_results_posted: date | None = None


class PreprintDocument(BaseDocument):
    """A preprint from bioRxiv or medRxiv."""

    source_type: Literal[SourceType.PREPRINT] = SourceType.PREPRINT
    doi: str | None = None
    server: str = ""  # "biorxiv" or "medrxiv"
    authors: list[str] = Field(default_factory=list)
    peer_reviewed: bool = False
    date_peer_published: date | None = None


class NewsDocument(BaseDocument):
    """A news article or media mention."""

    source_type: Literal[SourceType.NEWS] = SourceType.NEWS
    outlet: str = ""
    author: str | None = None
    sentiment: float | None = None
    reach_estimate: int | None = None
    claims_strength: str | None = None
    cites_primary_source: bool = False
    primary_source_doi: str | None = None


class SocialDocument(BaseDocument):
    """A social media post (Reddit, Twitter, etc.)."""

    source_type: Literal[SourceType.SOCIAL] = SourceType.SOCIAL
    platform: str = ""
    subreddit: str | None = None
    score: int | None = None
    comment_count: int | None = None
    sentiment: float | None = None


class EuropePMCDocument(BaseDocument):
    """A paper from Europe PMC (journals, preprints, Cochrane reviews)."""

    source_type: Literal[SourceType.EUROPE_PMC] = SourceType.EUROPE_PMC
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    cited_by_count: int | None = None
    is_open_access: bool = False
    peer_reviewed: bool = True
    is_preprint: bool = False
    is_cochrane: bool = False
    preprint_server: str | None = None  # "bioRxiv", "medRxiv" if is_preprint
    publication_types: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)


class SemanticScholarDocument(BaseDocument):
    """A paper from Semantic Scholar."""

    source_type: Literal[SourceType.SEMANTIC_SCHOLAR] = SourceType.SEMANTIC_SCHOLAR
    paper_id: str  # Semantic Scholar paper ID
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = None
    citation_count: int | None = None
    influential_citation_count: int | None = None
    tldr: str | None = None  # Auto-generated summary from S2
    publication_types: list[str] = Field(default_factory=list)
    is_open_access: bool = False


class DrugAgeDocument(BaseDocument):
    """A lifespan study record from the DrugAge database."""

    source_type: Literal[SourceType.DRUGAGE] = SourceType.DRUGAGE
    species: str
    strain: str | None = None
    dosage: str | None = None
    dosage_unit: str | None = None
    administration_route: str | None = None
    lifespan_change_percent: float | None = None  # +15.0 means 15% extension
    significance: str | None = None  # "significant", "not significant"
    reference_pmid: str | None = None
    gender: str | None = None  # "male", "female", "both", "mixed"


class GrantDocument(BaseDocument):
    """An NIH-funded research grant from NIH Reporter."""

    source_type: Literal[SourceType.NIH_GRANT] = SourceType.NIH_GRANT
    project_number: str
    pi_name: str | None = None
    organisation: str | None = None
    total_funding: float | None = None
    fiscal_year: int | None = None
    grant_start: date | None = None
    grant_end: date | None = None
    funding_mechanism: str | None = None  # "R01", "R21", "U01", etc.
    nih_institute: str | None = None  # "NIA", "NCI", etc.


class PatentDocument(BaseDocument):
    """A patent filing related to an intervention."""

    source_type: Literal[SourceType.PATENT] = SourceType.PATENT
    patent_id: str
    assignee: str | None = None
    inventors: list[str] = Field(default_factory=list)
    filing_date: date | None = None
    grant_date: date | None = None
    patent_status: str | None = None  # "granted", "pending", "expired"
    patent_office: str | None = None  # "USPTO", "EPO", "WIPO"
    claims_count: int | None = None


class RegulatoryDocument(BaseDocument):
    """An FDA/regulatory record for an approved drug."""

    source_type: Literal[SourceType.REGULATORY] = SourceType.REGULATORY
    approved_indications: list[str] = Field(default_factory=list)
    approval_date: date | None = None
    drug_class: str | None = None
    warnings_summary: str | None = None
    pharmacokinetics_summary: str | None = None
    nda_number: str | None = None  # FDA application number


# ── Google Trends (not a document — time series data) ────────────────────────


class TrendsData(BaseModel):
    """Google Trends interest data for an intervention. NOT a document."""

    intervention: str
    fetched_at: datetime
    timeframe: str  # "today 5-y"
    data_points: list[dict] = Field(default_factory=list)  # [{"date": "2024-01", "interest": 75}]
    related_queries: list[str] = Field(default_factory=list)
    peak_interest: int = 0
    peak_date: str = ""
    current_interest: int = 0


# ── Discriminated Union ──────────────────────────────────────────────────────

Document = Annotated[
    Union[
        PubMedDocument,
        ClinicalTrialDocument,
        PreprintDocument,
        NewsDocument,
        SocialDocument,
        EuropePMCDocument,
        SemanticScholarDocument,
        DrugAgeDocument,
        GrantDocument,
        PatentDocument,
        RegulatoryDocument,
    ],
    Field(discriminator="source_type"),
]

DocumentListAdapter = TypeAdapter(list[Document])
