# ARCHITECTURE.md — AGE-nt Technical Reference

## Purpose of This Document

This is the single source of truth for all architectural decisions. Claude Code should refer to this when implementing any component. It consolidates our schema design, storage strategy, ingest pipeline, and reasoning module design.

---

## Core Principle

**The data layer is the product.** Reasoning modules are swappable consumers of well-structured data. Invest most effort in getting the schema and ingest right. Everything else stacks on top.

---

## 1. Document Schema Design

We use **Base + source-specific models** (not a single flexible model with raw_metadata dict). This is critical because different sources have fundamentally different temporal fields, and temporal analysis is a core differentiator of this project.

### Why Not a Single Model with raw_metadata?

A `raw_metadata: dict[str, Any]` loses type safety. Clinical trials have 4 temporal fields (registered, started, completed, results_posted). PubMed papers have 1 (published). News articles have different ones again. Typed fields mean:
- IDE autocomplete and type checking
- Clean date arithmetic without runtime parsing
- Queryable without guessing dict key names
- Self-documenting — the schema IS the documentation

### Base Document

Every document from every source shares these fields:

```python
from pydantic import BaseModel, Field
from datetime import date
from enum import Enum
from typing import Literal, Annotated
import uuid

class SourceType(str, Enum):
    PUBMED = "pubmed"
    CLINICAL_TRIALS = "clinicaltrials"
    EUROPE_PMC = "europe_pmc"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    DRUGAGE = "drugage"
    NIH_GRANT = "nih_grant"
    PATENT = "patent"
    REGULATORY = "regulatory"
    PREPRINT = "preprint"
    NEWS = "news"
    SOCIAL = "social"
    GOOGLE_TRENDS = "google_trends"

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

class BaseDocument(BaseModel):
    """Common fields shared by ALL document sources."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: SourceType
    intervention: str                    # Normalised canonical name (lowercase)
    intervention_aliases: list[str] = []
    title: str
    abstract: str                        # Or description for non-paper sources
    source_url: str

    # Universal temporal field — every source has at least this
    date_published: date
    date_indexed: date = Field(default_factory=date.today)

    # RAW API response — insurance policy, never lose data
    raw_response: dict = Field(default={}, exclude=True)

    # === FIELDS POPULATED LATER BY REASONING AGENTS, NOT AT INGEST ===
    # These are None at ingest time and filled by classification agents
    evidence_level: EvidenceLevel | None = None
    study_type: str | None = None        # "RCT", "cohort", "meta_analysis", etc.
    organism: str | None = None          # "human", "mouse", "in_vitro", etc.
    effect_direction: EffectDirection | None = None
    key_findings: list[str] = []
    summary: str | None = None           # LLM-generated summary
    hallmarks_addressed: list[AgingHallmark] = []
    sample_size: int | None = None
    endpoints: list[str] = []
```

### Source-Specific Models

Each inherits from BaseDocument and adds typed fields unique to that source.

```python
class PubMedDocument(BaseDocument):
    """A paper from PubMed."""
    source_type: Literal[SourceType.PUBMED] = SourceType.PUBMED
    pmid: str
    doi: str | None = None
    authors: list[str] = []
    journal: str | None = None
    impact_factor: float | None = None
    mesh_terms: list[str] = []
    publication_types: list[str] = []    # "Randomized Controlled Trial", "Review", etc.
    peer_reviewed: bool = True
    # PubMed gives us MeSH terms which are useful for pre-filtering
    # before LLM classification (e.g., "Randomized Controlled Trial"
    # publication type is a strong signal for evidence_level=2)


class ClinicalTrialDocument(BaseDocument):
    """A trial record from ClinicalTrials.gov."""
    source_type: Literal[SourceType.CLINICAL_TRIALS] = SourceType.CLINICAL_TRIALS
    nct_id: str
    phase: str | None = None             # "Phase 1", "Phase 1/Phase 2", "Phase 2", etc.
    status: str | None = None            # "Recruiting", "Completed", "Terminated", "Withdrawn"
    enrollment: int | None = None
    sponsor: str | None = None
    conditions: list[str] = []
    primary_outcomes: list[str] = []
    results_summary: str | None = None   # Text summary of results if posted

    # === TEMPORAL GOLDMINE ===
    # These 4 dates tell the full story of a trial's lifecycle.
    # This is why we need typed models, not raw_metadata dicts.
    date_registered: date | None = None
    date_started: date | None = None
    date_completed: date | None = None
    date_results_posted: date | None = None
    # A trial registered in 2019, started in 2020, completed 2023,
    # results posted 2024 = 4 temporal data points from one record.
    # Trajectory scoring uses these to assess pipeline velocity.


class PreprintDocument(BaseDocument):
    """A preprint from bioRxiv or medRxiv."""
    source_type: Literal[SourceType.PREPRINT] = SourceType.PREPRINT
    doi: str | None = None
    server: str = ""                     # "biorxiv" or "medrxiv"
    authors: list[str] = []
    peer_reviewed: bool = False
    date_peer_published: date | None = None  # If later published in journal
    # Preprints are leading indicators — they signal emerging momentum
    # BEFORE peer review. The gap between date_published (preprint) and
    # date_peer_published (journal) is itself a useful metric.


class NewsDocument(BaseDocument):
    """A news article or media mention."""
    source_type: Literal[SourceType.NEWS] = SourceType.NEWS
    outlet: str = ""                     # "NYT", "BBC", "STAT News", etc.
    author: str | None = None
    # Hype-tracking fields (populated at ingest for news, not deferred)
    sentiment: float | None = None       # -1 to 1
    reach_estimate: int | None = None    # Publication reach / social shares
    claims_strength: str | None = None   # "breakthrough", "promising", "incremental", "negative"
    cites_primary_source: bool = False
    primary_source_doi: str | None = None


class SocialDocument(BaseDocument):
    """A social media post (Reddit, Twitter, etc.)."""
    source_type: Literal[SourceType.SOCIAL] = SourceType.SOCIAL
    platform: str = ""                   # "reddit", "twitter", "google_trends"
    subreddit: str | None = None
    score: int | None = None             # Upvotes, likes, etc.
    comment_count: int | None = None
    sentiment: float | None = None
```

### Additional Source-Specific Models (Implemented)

Beyond PubMed, ClinicalTrials, Preprint, News, and Social (shown above), the following subclasses are also implemented:

- **EuropePMCDocument**: `europe_pmc_id`, `doi`, `authors`, `journal`, `citation_count`, `is_open_access`, `has_fulltext`, `mesh_terms`, etc.
- **SemanticScholarDocument**: `s2_paper_id`, `doi`, `authors`, `journal`, `citation_count`, `influential_citation_count`, `fields_of_study`, etc.
- **DrugAgeDocument**: `species`, `strain`, `dosage`, `lifespan_change_percent`, `significance`, `gender`, etc.
- **NIHGrantDocument**: `project_number`, `fiscal_year`, `total_cost`, `pi_names`, `organization`, `nih_institute`, etc.
- **PatentDocument**: `patent_id`, `patent_number`, `filing_date`, `grant_date`, `applicant`, `inventors`, `patent_status`, etc.
- **RegulatoryDocument**: `drug_name`, `active_ingredients`, `manufacturer`, `approval_status`, `labeling_url`, etc.

### Discriminated Union for Serialization

```python
from typing import Annotated, Union
from pydantic import Field, TypeAdapter

# Pydantic discriminated union — picks the right subclass based on source_type
# All 11 subclasses included
Document = Annotated[
    Union[
        PubMedDocument,
        ClinicalTrialDocument,
        EuropePMCDocument,
        SemanticScholarDocument,
        DrugAgeDocument,
        NIHGrantDocument,
        PatentDocument,
        RegulatoryDocument,
        PreprintDocument,
        NewsDocument,
        SocialDocument,
    ],
    Field(discriminator="source_type")
]

# Usage:
DocumentListAdapter = TypeAdapter(list[Document])

# Serialize
json_bytes = DocumentListAdapter.dump_json(documents, indent=2)

# Deserialize — automatically picks correct subclass
documents = DocumentListAdapter.validate_json(json_bytes)
# A record with source_type="clinicaltrials" becomes ClinicalTrialDocument
# with all its typed date fields, not a generic dict
```

---

## 2. Storage Strategy

### Dual Storage: JSON (primary) + SQLite (structured queries)

**JSON files** are the primary store during the hackathon. Simple, debuggable, zero setup.
**SQLite** runs alongside for structured queries (aggregations, temporal analysis).
Both are written to on every ingest. The StorageManager abstracts this.

```
data/
├── documents/
│   ├── rapamycin.json           # All docs for rapamycin
│   ├── metformin.json           # All docs for metformin
│   ├── nmn.json                 # etc.
│   └── ...
├── classifications/
│   └── {intervention}.json      # LLM classification results (written by reasoning agents)
├── age_nt.db                    # SQLite database (mirrors JSON)
└── reports/
    └── {intervention}_{timestamp}.json  # Generated reports
```

### JSON Storage

One file per intervention. Contains the full typed documents.

```python
# data/documents/rapamycin.json
{
  "intervention": "rapamycin",
  "aliases": ["sirolimus", "rapa", "rapamune"],
  "last_updated": "2025-02-27",
  "document_count": 142,
  "documents": [
    {
      "id": "a1b2c3d4-...",
      "source_type": "pubmed",
      "pmid": "35912345",
      "title": "Rapamycin extends lifespan in genetically heterogeneous mice",
      "abstract": "The Interventions Testing Program evaluated rapamycin...",
      "source_url": "https://pubmed.ncbi.nlm.nih.gov/35912345/",
      "date_published": "2023-06-15",
      "date_indexed": "2025-02-27",
      "authors": ["Harrison DE", "Strong R", "..."],
      "journal": "Nature Aging",
      "impact_factor": 17.0,
      "mesh_terms": ["Sirolimus", "Aging", "Longevity", "Mice"],
      "publication_types": ["Journal Article", "Randomized Controlled Trial"],
      "peer_reviewed": true,
      "doi": "10.1038/s43587-023-00001-x",
      "raw_response": {},

      "evidence_level": null,
      "study_type": null,
      "organism": null,
      "effect_direction": null,
      "key_findings": [],
      "summary": null,
      "hallmarks_addressed": [],
      "sample_size": null,
      "endpoints": []
    },
    {
      "id": "e5f6g7h8-...",
      "source_type": "clinicaltrials",
      "nct_id": "NCT04488601",
      "title": "Rapamycin for Immune Aging in Elderly Volunteers",
      "abstract": "A phase 2 trial investigating low-dose rapamycin...",
      "source_url": "https://clinicaltrials.gov/study/NCT04488601",
      "date_published": "2020-07-27",
      "date_indexed": "2025-02-27",
      "phase": "Phase 2",
      "status": "Completed",
      "enrollment": 150,
      "date_registered": "2020-07-27",
      "date_started": "2021-01-15",
      "date_completed": "2023-09-30",
      "date_results_posted": "2024-02-15",
      "primary_outcomes": ["Change in immune function biomarkers"],
      "sponsor": "UCLA",
      "conditions": ["Aging", "Immunosenescence"],
      "results_summary": "Treatment group showed significant improvement in...",
      "raw_response": {},

      "evidence_level": null,
      "study_type": null,
      "organism": null,
      "effect_direction": null,
      "key_findings": [],
      "summary": null,
      "hallmarks_addressed": [],
      "sample_size": null,
      "endpoints": []
    }
  ]
}
```

### SQLite Schema

Mirrors the JSON but enables SQL queries. One main table with common fields, source-specific fields stored as JSON columns.

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,          -- 'pubmed', 'clinicaltrials', etc.
    intervention TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    source_url TEXT,
    date_published DATE NOT NULL,
    date_indexed DATE NOT NULL,

    -- Source-specific (nullable, only relevant for some source types)
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

    -- Clinical trial temporal fields
    date_registered DATE,
    date_started DATE,
    date_completed DATE,
    date_results_posted DATE,

    -- Hype fields (news/social)
    sentiment REAL,
    reach_estimate INTEGER,
    claims_strength TEXT,

    -- Source-specific overflow (anything that doesn't have its own column)
    source_metadata JSON,              -- authors, mesh_terms, publication_types, etc.

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

    -- Raw API response (insurance policy)
    raw_response JSON
);

-- Indices for common query patterns
CREATE INDEX idx_intervention ON documents(intervention);
CREATE INDEX idx_source_type ON documents(source_type);
CREATE INDEX idx_date_published ON documents(date_published);
CREATE INDEX idx_evidence_level ON documents(evidence_level);
CREATE INDEX idx_organism ON documents(organism);
CREATE INDEX idx_nct_id ON documents(nct_id);
CREATE INDEX idx_pmid ON documents(pmid);

-- Compound indices for common filters
CREATE INDEX idx_intervention_source ON documents(intervention, source_type);
CREATE INDEX idx_intervention_date ON documents(intervention, date_published);
```

### StorageManager Interface

This abstracts both stores so consuming code never touches JSON or SQLite directly.

```python
class StorageManager:
    """Unified interface to JSON + SQLite storage.
    All reasoning modules and API routes use this — never raw file/db access."""

    def save_documents(self, intervention: str, docs: list[Document]) -> None:
        """Write to both JSON and SQLite."""
        ...

    def get_documents(
        self,
        intervention: str,
        source_type: SourceType | None = None,
        evidence_level: EvidenceLevel | None = None,
        organism: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Document]:
        """Query documents with filters. Uses SQLite for filtered queries,
        JSON for full intervention loads."""
        ...

    def get_timeline(self, intervention: str) -> dict:
        """Temporal aggregation: studies per evidence level per year.
        Uses SQLite for the aggregation query."""
        ...

    def get_trial_lifecycle(self, intervention: str) -> list[dict]:
        """Clinical trial temporal data: registered → started → completed → results.
        Only possible because ClinicalTrialDocument has typed date fields."""
        ...

    def update_classifications(self, doc_id: str, classifications: dict) -> None:
        """Write reasoning agent outputs back to both stores.
        Called after evidence grading, gap analysis, etc."""
        ...

    def get_all_interventions(self) -> list[str]:
        """List all interventions we have data for."""
        ...
```

### Why Both JSON and SQLite?

| Scenario | Use JSON | Use SQLite |
|----------|----------|------------|
| Debug at 3am — "what does our rapamycin data look like?" | Open file, read it | ❌ Need a SQL client |
| "How many RCTs per year across all interventions?" | ❌ Load every file, loop | `SELECT strftime('%Y', date_published), COUNT(*) ... GROUP BY` |
| Backup/share dataset | Copy the folder | Export needed |
| Schema change (add a field) | Just add it to Pydantic model | Need ALTER TABLE or migration |
| Feed an entire intervention's data to an LLM | Read file, pass it | ❌ Awkward |
| Temporal aggregation for trajectory scoring | ❌ Slow on large datasets | Fast with indices |

JSON is the human-readable source of truth and the easy interface for LLM reasoning.
SQLite is the query engine for structured analysis and aggregations.

---

## 3. Ingest Pipeline

### Principle: Scrape First, Reason Later

Ingest agents are **fast and dumb**. They hit APIs, parse responses into typed models, and store. No LLM calls at ingest time. This means:
- Ingest is fast (no waiting for LLM responses)
- No classification errors baked into stored data
- Can re-run classification with better prompts without re-scraping
- LLM costs are only incurred when someone actually requests analysis

### Ingest Flow

```
User requests: "Ingest rapamycin"
    │
    ├── Query Expander (LLM, once)
    │   └── "rapamycin" → ["rapamycin", "sirolimus", "rapamune", "mTOR inhibitor", ...]
    │
    ├── PubMed Agent
    │   ├── esearch → efetch → Parse XML → PubMedDocument objects
    │   └── Return list[PubMedDocument]
    │
    ├── ClinicalTrials Agent
    │   ├── GET /v2/studies → Parse JSON → ClinicalTrialDocument objects
    │   └── Return list[ClinicalTrialDocument]
    │
    ├── Europe PMC Agent
    │   ├── REST search API → journals, preprints, Cochrane reviews
    │   └── Return list[EuropePMCDocument]
    │
    ├── Semantic Scholar Agent
    │   ├── Graph API → citation data, influential citations
    │   └── Return list[SemanticScholarDocument]
    │
    ├── DrugAge Agent
    │   ├── Local CSV → animal lifespan data
    │   └── Return list[DrugAgeDocument]
    │
    ├── NIH Reporter Agent
    │   ├── v2 API → funded grants, NIA boost scoring
    │   └── Return list[NIHGrantDocument]
    │
    ├── Patent Agent
    │   ├── Lens.org API (fallback: Google Patents scrape)
    │   └── Return list[PatentDocument]
    │
    ├── FDA Agent
    │   ├── DailyMed API → regulatory approvals
    │   └── Return list[RegulatoryDocument]
    │
    ├── Tavily Agent
    │   ├── Tavily web search → broad web results
    │   └── Return list[NewsDocument]
    │
    └── Social Agent
        ├── Reddit/HN via Tavily → social sentiment
        └── Return list[SocialDocument]

    ↓ All documents collected (agents run concurrently in seed_all.py)

StorageManager.save_documents("rapamycin", all_docs)
    ├── Append to data/documents/rapamycin.json (dedup by source_url)
    └── INSERT OR REPLACE INTO documents ... (SQLite, dedup by id)
```

### PubMed Agent — Implementation Notes

```
Base URL: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
Rate limit: 3 req/sec without API key, 10/sec with NCBI_API_KEY

Step 1 — Search:
  GET esearch.fcgi?db=pubmed&term={query}&retmax=100&retmode=json
  Returns: list of PMIDs

Step 2 — Fetch:
  GET efetch.fcgi?db=pubmed&id={pmid_list}&rettype=xml
  Returns: XML with full article metadata

Key fields to extract from XML:
  - PMID
  - ArticleTitle
  - AbstractText
  - AuthorList → Author → LastName, ForeName
  - Journal → Title, ISOAbbreviation
  - PubDate → Year, Month, Day
  - MeSHHeadingList → MeSH terms
  - PublicationTypeList → e.g. "Randomized Controlled Trial", "Review", "Meta-Analysis"
  - ArticleIdList → DOI

Note: PublicationTypeList is extremely valuable as a pre-classification signal.
If it contains "Meta-Analysis" → strong hint for evidence_level = 1.
If it contains "Randomized Controlled Trial" → hint for evidence_level = 2.
Store these in publication_types field for use by classification agents later.
```

### ClinicalTrials.gov Agent — Implementation Notes

```
Base URL: https://clinicaltrials.gov/api/v2/studies
No authentication required.

Query:
  GET /v2/studies?query.intr={intervention}&query.cond=aging&pageSize=50
  Returns: JSON with study records

Key fields to extract:
  protocolSection.identificationModule.nctId
  protocolSection.identificationModule.officialTitle
  protocolSection.descriptionModule.briefSummary
  protocolSection.statusModule.overallStatus         → status
  protocolSection.statusModule.startDateStruct.date   → date_started
  protocolSection.statusModule.completionDateStruct.date → date_completed
  protocolSection.designModule.phases                 → phase
  protocolSection.designModule.enrollmentInfo.count   → enrollment
  protocolSection.outcomesModule.primaryOutcomes      → primary_outcomes
  protocolSection.sponsorCollaboratorsModule          → sponsor
  resultsSection (if posted)                          → results_summary

The temporal fields here are gold for trajectory scoring:
  - date_registered = when the trial was first submitted to CT.gov
  - date_started = when enrollment began
  - date_completed = when the last participant finished
  - date_results_posted = when results were made public
  
A compound with many registered-but-not-started trials tells a different
story than one with completed trials and posted results.
```

---

## 4. Classification Pipeline (Post-Ingest)

Classification runs ON DEMAND when a reasoning module needs it, or when a report is requested. Results are cached — once a document is classified, it doesn't need re-classification unless the prompt/model changes.

```
Report requested for "rapamycin"
    │
    ├── StorageManager.get_documents("rapamycin")
    │   Returns all docs, some with evidence_level=None
    │
    ├── For each unclassified document:
    │   ├── Send to Gemini API:
    │   │   System: "You are a biomedical research classifier..."
    │   │   User: title + abstract + publication_types + mesh_terms
    │   │   Response format: structured JSON
    │   │
    │   ├── Parse response into classification fields:
    │   │   evidence_level, study_type, organism, effect_direction,
    │   │   key_findings, summary, hallmarks_addressed, sample_size, endpoints
    │   │
    │   └── StorageManager.update_classifications(doc_id, results)
    │       Writes to both JSON and SQLite
    │
    └── All docs now classified → pass to reasoning modules
```

### Classification Prompt Template

```
You are a biomedical research classifier specialising in aging and longevity research.

Given the following study information, classify it according to the fields below.
Respond ONLY with valid JSON, no other text.

Study title: {title}
Abstract: {abstract}
Journal: {journal}
Publication types: {publication_types}
MeSH terms: {mesh_terms}
Source: {source_type}

Classify into:
{
  "evidence_level": 1-6 (1=systematic review/meta-analysis, 2=RCT, 3=observational/epidemiological, 4=animal in vivo, 5=cell culture in vitro, 6=computational/in silico),
  "study_type": "meta_analysis|systematic_review|RCT|cohort|case_control|cross_sectional|animal_lifespan|animal_healthspan|cell_culture|computational|review|commentary",
  "organism": "human|mouse|rat|c_elegans|drosophila|yeast|in_vitro|in_silico|multiple",
  "effect_direction": "positive|negative|null|mixed",
  "sample_size": number or null,
  "key_findings": ["finding 1", "finding 2"],
  "summary": "One paragraph summary of the study and its relevance to aging",
  "hallmarks_addressed": ["genomic_instability", "cellular_senescence", ...],
  "endpoints": ["lifespan", "healthspan", "epigenetic_clock", ...]
}
```

---

## 5. Temporal Analysis Design

Temporal analysis is a core differentiator. The schema is designed to support these temporal queries:

### Trajectory Scoring

```python
# Query: How is evidence accumulating over time for rapamycin?
timeline = storage.get_timeline("rapamycin")
# Returns:
{
  "2015": {"level_4": 12, "level_3": 2, "level_5": 5},
  "2016": {"level_4": 15, "level_3": 3, "level_2": 1, "level_5": 7},
  ...
  "2024": {"level_4": 8, "level_2": 4, "level_1": 2, "level_3": 6, "level_5": 3}
}
# This shows rapamycin climbing the evidence hierarchy over time.
# Contrast with an intervention stuck at level 4-5 for a decade.
```

### Trial Lifecycle Analysis

```python
# Query: What's the pipeline velocity for rapamycin trials?
trials = storage.get_trial_lifecycle("rapamycin")
# Returns:
[
  {
    "nct_id": "NCT04488601",
    "phase": "Phase 2",
    "date_registered": "2020-07-27",
    "date_started": "2021-01-15",
    "date_completed": "2023-09-30",
    "date_results_posted": "2024-02-15",
    "status": "Completed",
    "days_to_start": 172,        # registered → started
    "days_to_complete": 988,     # started → completed
    "days_to_results": 138,      # completed → results posted
    "total_days": 1298           # registered → results posted
  },
  ...
]
# Fast pipeline velocity + completed trials = strong translational signal
# Many registered-but-not-started trials = potential red flag
```

### Evidence Momentum Score

```python
# The trajectory scorer computes:
{
  "intervention": "rapamycin",
  "momentum_score": 0.78,          # 0-1, higher = faster evidence accumulation
  "phase": "accelerating",         # emerging | accelerating | mature | stagnant | declining
  "evidence_velocity": {
    "publications_per_year_recent": 45,   # last 2 years
    "publications_per_year_historical": 20, # 5+ years ago
    "acceleration": 2.25                    # ratio
  },
  "hierarchy_progression": {
    "highest_evidence_2020": 4,     # Was mostly animal data
    "highest_evidence_2024": 2,     # Now has RCTs
    "years_to_climb": 4
  },
  "trial_pipeline": {
    "active_trials": 5,
    "completed_with_results": 3,
    "avg_pipeline_velocity_days": 1100
  }
}
```

---

## 6. On LangGraph / Orchestration Frameworks

**Short answer: No. Don't use LangGraph. It adds complexity without value for this project.**

### Why Not

LangGraph (and similar agent orchestration frameworks like CrewAI, AutoGen) are designed for:
- Complex multi-agent conversations with branching logic
- Agents that need to dynamically decide which other agents to call
- Stateful workflows with checkpointing and human-in-the-loop

Our system is a **pipeline, not a conversation**. The flow is deterministic:

```
Ingest (fetch data) → Store → Classify (on demand) → Reason → Report
```

There are no dynamic decisions. The evidence grader doesn't need to "talk to" the gap spotter. They both independently read from the same data store and write their outputs. The report generator just collects all their outputs.

### What To Use Instead

Plain Python functions with the Gemini API client. That's it.

```python
# This is all the "orchestration" you need:

async def generate_report(intervention: str) -> Report:
    """Orchestrate all reasoning modules. No framework needed."""
    
    # 1. Ensure documents are ingested
    docs = await storage.get_documents(intervention)
    if not docs:
        docs = await ingest_all_sources(intervention)
    
    # 2. Ensure documents are classified
    unclassified = [d for d in docs if d.evidence_level is None]
    if unclassified:
        await classify_documents(unclassified)
        docs = await storage.get_documents(intervention)  # reload
    
    # 3. Run reasoning modules (these are just functions)
    evidence_grade = await evidence_grader.grade(docs)
    trajectory = await trajectory_scorer.score(docs, storage)
    gaps = await gap_spotter.analyse(docs)
    
    # 4. Combine into report
    report = await report_generator.generate(
        intervention=intervention,
        documents=docs,
        evidence_grade=evidence_grade,
        trajectory=trajectory,
        gaps=gaps,
    )
    
    return report
```

### When You WOULD Need an Orchestration Framework

- If a reasoning module needed to dynamically trigger new ingests ("I found a reference to compound X, let me go fetch data on that too")
- If you had 10+ agents with complex dependencies between them
- If you needed human-in-the-loop approval steps

None of these apply for the hackathon. If you reach stretch goals and want agents that autonomously explore related compounds, THEN consider a lightweight state machine. But even then, a simple queue/dispatcher pattern would suffice.

**Rule of thumb: If you can draw your workflow as a straight line (with maybe one branch), you don't need an orchestration framework.**

---

## 7. API Design

### FastAPI Routes

```python
# Interventions
GET  /interventions
     → List all interventions with document counts
     → Response: [{"name": "rapamycin", "aliases": [...], "doc_count": 142, "last_updated": "2025-02-27"}]

GET  /interventions/{name}/documents
     → All documents for an intervention, with filters
     → Query params: ?source_type=pubmed&evidence_level=1,2&date_from=2020-01-01&organism=human
     → Response: list[Document] (discriminated union, correct subclass per source)

GET  /interventions/{name}/timeline
     → Temporal aggregation for trajectory scoring
     → Response: {"years": {"2020": {"level_1": 0, "level_2": 1, ...}, ...}}

GET  /interventions/{name}/gaps
     → Evidence gap analysis
     → Response: {"missing": ["No RCTs", "No female cohort data"], "warnings": [...]}

# Reasoning / Reports
POST /interventions/{name}/report
     → Trigger full reasoning pipeline
     → Response: Full structured report with confidence score

POST /ingest/{name}
     → Trigger ingest for a new intervention
     → Body: {"aliases": ["sirolimus"]}  (optional)
     → Response: {"documents_ingested": 142, "sources": {"pubmed": 95, "clinicaltrials": 47}}

# Search
POST /query
     → Full-text search across all documents (stretch: semantic search)
     → Body: {"query": "mTOR immune function", "filters": {"organism": "human"}}
     → Response: list[Document]
```

---

## 8. Current Status

### Built
- **Schema**: Base + 11 source-specific subclasses, discriminated union, 12 source types
- **Storage**: JSON + SQLite dual store, StorageManager, dedup (URL-based + ID-based)
- **Ingest**: 10 agents + Google Trends + LLM query expander. All async, no LLM at scrape time.
- **API**: FastAPI with interventions, ingest, reasoning routes
- **MCP Server**: 8 tools (3 functional: list_interventions, get_intervention_stats, search_documents; 5 stubs)
- **Scripts**: seed_intervention.py, seed_all.py (batch with checkpoint/resume, concurrent agents, retry/backoff)
- **Tools**: Edison/PaperQA3 implemented; evidence_grader, trajectory, gap_spotter, hype_ratio, report_generator are stubs
- **Data**: 55 interventions with aliases and categories

### Next to build
See FUTURE_WORK.md — reasoning tools (T1-T4), wire them into MCP stubs

---

## 9. Key Reminders

- **Ingest is dumb, reasoning is smart.** Never call an LLM during ingest (query expansion is the one exception — run once per intervention, not per document).
- **JSON is readable, SQLite is queryable.** Write to both, query from whichever makes sense.
- **No orchestration framework.** Plain async functions calling the LLM API. See Section 6 for rationale.
- **Temporal fields are typed, not dict keys.** This is why we use Base + source-specific models.
- **The StorageManager is the only interface to data.** Nothing else touches files or the database directly.
- **Classification fields are nullable.** They start as None and get filled by reasoning agents.
- **Cache LLM results.** Once a document is classified, store the result in `data/classifications/`. Don't re-classify.
- **raw_response is the insurance policy.** Always store the full API response so you can re-parse later.
