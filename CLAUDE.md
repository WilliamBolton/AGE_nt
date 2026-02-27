# CLAUDE.md — Longevity Evidence Grading Agent

**IMPORTANT: Read ARCHITECTURE.md before implementing anything.** It contains the full schema definitions, storage strategy, ingest pipeline design, and the rationale for every architectural decision. This file is the quick-start overview; ARCHITECTURE.md is the detailed reference.

## Project Overview

This is **LongevityLens** — an agentic system that scrapes, standardises, and reasons over scientific evidence for aging interventions. The core insight: the **data layer is the product**. Reasoning modules (evidence grading, trajectory scoring, gap analysis, hype ratio) are swappable consumers of a unified, temporally-indexed document store.

## Architecture

```
Sources (PubMed, ClinicalTrials.gov, News, Social)
    ↓
Ingest Agents (one per source, LLM-assisted classification)
    ↓
Unified Document Schema (every item normalised to same format)
    ↓
Storage (ChromaDB vectors + SQLite structured metadata)
    ↓
FastAPI (query, filter, aggregate, trigger reasoning)
    ↓
Reasoning Modules (Evidence Grader, Trajectory Scorer, Gap Spotter, Hype Ratio)
    ↓
Frontends (Streamlit demo, future: React apps)
```

## Tech Stack

- **Language:** Python 3.11+
- **API Framework:** FastAPI + uvicorn
- **Database:** JSON files (primary, human-readable) + SQLite (structured queries). No ChromaDB for now — see FUTURE_WORK.md
- **LLM:** Google Gemini API (orchestration, classification) + MedGemma via Lyceum GPU (medical reasoning)
- **Ingest:** httpx for API calls, BeautifulSoup for HTML parsing
- **Frontend:** Streamlit (hackathon demo)
- **Containerisation:** Docker + docker-compose (for deployment)

## Project Structure

```
longevity-lens/
├── CLAUDE.md                    # This file
├── FUTURE_WORK.md               # Stretch goals and roadmap
├── README.md                    # Project readme
├── pyproject.toml               # Dependencies (use uv or pip)
├── .env.example                 # API keys template
├── docker-compose.yml           # Local + deploy
├── Dockerfile
│
├── src/
│   ├── __init__.py
│   ├── config.py                # Settings, API keys, env vars
│   │
│   ├── schema/
│   │   ├── __init__.py
│   │   └── document.py          # Pydantic models for unified doc schema
│   │
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract base ingest agent
│   │   ├── pubmed.py            # PubMed E-utilities agent
│   │   ├── clinical_trials.py   # ClinicalTrials.gov v2 API agent
│   │   ├── preprints.py         # bioRxiv/medRxiv API agent (stretch)
│   │   ├── news.py              # News/media scraping agent (stretch)
│   │   └── social.py            # Reddit/Google Trends agent (stretch)
│   │
│   ├── classify/
│   │   ├── __init__.py
│   │   └── llm_classifier.py    # LLM-based evidence level classification at ingest
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── json_store.py        # JSON file storage (primary, human-readable)
│   │   ├── sqlite_store.py      # SQLite structured metadata store
│   │   └── manager.py           # Unified storage interface (writes to both)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entry
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── interventions.py # /interventions endpoints
│   │   │   ├── search.py        # /query semantic search
│   │   │   └── reports.py       # /report reasoning trigger
│   │   └── dependencies.py      # Shared deps (db connections etc)
│   │
│   ├── reasoning/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract reasoning module
│   │   ├── evidence_grader.py   # Classify + score evidence distribution
│   │   ├── trajectory.py        # Temporal momentum scoring
│   │   ├── gap_spotter.py       # Missing evidence identification
│   │   ├── hype_ratio.py        # Evidence vs media hype (stretch)
│   │   └── report_generator.py  # Orchestrates all modules → structured report
│   │
│   └── frontend/
│       └── app.py               # Streamlit demo app
│
├── scripts/
│   ├── seed_intervention.py     # CLI: ingest all sources for one intervention
│   └── seed_all.py              # CLI: ingest for all example interventions
│
├── tests/
│   ├── test_schema.py
│   ├── test_ingest_pubmed.py
│   └── test_evidence_grader.py
│
└── data/
    ├── interventions.json       # Canonical list of interventions + aliases
    └── chroma_db/               # ChromaDB persistent storage (gitignored)
```

## Unified Document Schema

This is the most critical design decision. EVERY scraped item gets normalised into this schema. Defined in `src/schema/document.py` as Pydantic models.

```python
class SourceType(str, Enum):
    PUBMED = "pubmed"
    CLINICAL_TRIALS = "clinicaltrials"
    PREPRINT = "preprint"
    NEWS = "news"
    SOCIAL = "social"
    PATENT = "patent"

class EvidenceLevel(int, Enum):
    SYSTEMATIC_REVIEW = 1        # Systematic reviews & meta-analyses
    RCT = 2                      # Randomised controlled trials
    OBSERVATIONAL = 3            # Observational / epidemiological
    ANIMAL = 4                   # Animal model studies (in vivo)
    IN_VITRO = 5                 # Cell culture / in vitro
    IN_SILICO = 6                # Computational predictions

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

class UnifiedDocument(BaseModel):
    id: str                          # UUID
    source_type: SourceType
    evidence_level: EvidenceLevel    # Classified by LLM at ingest
    intervention: str                # Normalised canonical name
    intervention_aliases: list[str]
    organism: str                    # human, mouse, rat, c_elegans, in_vitro, in_silico
    study_type: str                  # RCT, cohort, meta_analysis, animal_lifespan, etc.
    peer_reviewed: bool

    # Temporal — critical for trajectory scoring
    date_published: date
    date_indexed: date               # When we ingested it
    date_trial_registered: date | None
    date_trial_completed: date | None

    # Content
    title: str
    abstract: str
    summary: str                     # LLM-generated at ingest
    key_findings: list[str]          # LLM-extracted
    effect_direction: EffectDirection
    sample_size: int | None
    endpoints: list[str]

    # Hype tracking (news/social only)
    sentiment: float | None          # -1 to 1
    reach_estimate: int | None
    claims_strength: str | None      # breakthrough, promising, incremental, negative

    # Provenance
    source_url: str
    doi: str | None
    authors: list[str]
    journal: str | None
    impact_factor: float | None

    # Aging-specific
    hallmarks_addressed: list[AgingHallmark]
    aging_biomarkers_measured: list[str]
```

## API Endpoints

```
GET  /interventions                              → List all indexed interventions
GET  /interventions/{name}/documents             → All docs, filterable by:
                                                     ?source_type=pubmed
                                                     ?evidence_level=1,2
                                                     ?date_from=2020-01-01
                                                     ?organism=human
GET  /interventions/{name}/timeline              → Temporal aggregation (studies per level per year)
GET  /interventions/{name}/gaps                  → Gap analysis results
GET  /interventions/{name}/hype                  → News/social sentiment over time
POST /interventions/{name}/report                → Trigger full reasoning pipeline → structured JSON report
POST /query                                      → Semantic search across all docs
POST /ingest                                     → Trigger ingest for a new intervention
```

## Key Implementation Notes

### Ingest Agents

Each agent in `src/ingest/` must:
1. Accept an intervention name + aliases
2. Query its source API/scraper
3. For each result, call the LLM classifier (`src/classify/llm_classifier.py`) to fill: `evidence_level`, `study_type`, `organism`, `effect_direction`, `key_findings`, `hallmarks_addressed`, `summary`
4. Return a list of `UnifiedDocument` objects
5. Handle rate limits and pagination

### PubMed Agent (PRIORITY — build first)
- Use NCBI E-utilities: `esearch.fcgi` + `efetch.fcgi`
- Base URL: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- Query pattern: `"{intervention}" AND (aging OR ageing OR lifespan OR longevity OR senescence)`
- Return format: XML, parse with ElementTree
- Extract: PMID, title, abstract, authors, journal, pub date, DOI, MeSH terms
- Rate limit: 3 requests/second without API key, 10/sec with

### ClinicalTrials.gov Agent (PRIORITY — build second)
- Use v2 API: `https://clinicaltrials.gov/api/v2/studies`
- Query by intervention name
- Extract: NCT ID, title, phase, status, enrollment, conditions, start/completion dates, primary outcomes
- Map phase to evidence level (Phase 3 completed = Level 2, etc.)

### LLM Classification
- Classification happens ON DEMAND when reasoning modules need it, NOT at ingest time
- Ingest agents are fast and dumb — they just fetch and store raw data
- Use Gemini API for classification when a report is requested
- Send title + abstract + MeSH terms (if available) to get evidence_level, organism, etc.
- Cache results — write classifications back to storage so they persist
- Use MedGemma for deeper medical reasoning when available
- See ARCHITECTURE.md Sections 3-4 for full ingest and classification pipeline details

### Storage
- **JSON files**: Primary store. One file per intervention in `data/documents/`. Human-readable, debuggable, Pydantic serializes directly.
- **SQLite**: Mirrors JSON for structured queries and temporal aggregations. Both are written to on every ingest.
- **StorageManager**: Single interface that writes to both and provides unified query methods. Reasoning modules and API routes ONLY use StorageManager, never raw file/db access.
- See ARCHITECTURE.md Section 2 for full details on the dual storage strategy.

### Reasoning Modules

Each module in `src/reasoning/` must:
1. Accept an intervention name
2. Query the storage layer for relevant documents
3. Return a structured result (Pydantic model)
4. Be independently callable via API

**Evidence Grader**: Count studies per evidence level, weight by sample size and journal impact factor, compute composite confidence score 0-100.

**Trajectory Scorer**: Group studies by year and evidence level. Compute: rate of new publications, whether evidence is climbing the hierarchy over time, time since last major study. Output a momentum score and phase label (emerging/accelerating/mature/stagnant/declining).

**Gap Spotter**: Check for missing evidence types against an ideal hierarchy. Flag: no human data, no RCTs, all studies from <3 labs, no female subjects, no dose-response data, no long-term follow-up, no replication studies.

**Report Generator**: Orchestrates all modules, combines outputs into a single structured report with sections and a final confidence score with transparent reasoning.

## Environment Variables

```
GEMINI_API_KEY=           # Google Gemini API key
MEDGEMMA_ENDPOINT=        # Lyceum endpoint for MedGemma (optional)
NCBI_API_KEY=             # NCBI API key (optional, increases rate limit)
DATABASE_PATH=data/longevity_lens.db
DATA_DIR=data/
LOG_LEVEL=INFO
```

## Build Order (Hackathon Priority)

### Phase 1: Core Data Layer (Hours 1-6)
1. `schema/document.py` — Pydantic models (Base + source-specific, see ARCHITECTURE.md)
2. `storage/json_store.py` + `storage/sqlite_store.py` + `storage/manager.py`
3. `ingest/pubmed.py` — PubMed agent (NO LLM calls at ingest)
4. `ingest/clinical_trials.py` — ClinicalTrials agent
5. `classify/llm_classifier.py` — Gemini-based classification (called on demand)
6. `scripts/seed_intervention.py` — Test with "rapamycin"

### Phase 2: API + Core Reasoning (Hours 6-12)
7. `api/main.py` + routes
8. `reasoning/evidence_grader.py`
9. `reasoning/trajectory.py`
10. `reasoning/gap_spotter.py`
11. `reasoning/report_generator.py`

### Phase 3: Demo (Hours 12-16)
12. `frontend/app.py` — Streamlit
13. Test with all 7 example interventions
14. Polish output formatting

### Phase 4: Stretch (Hours 16-23)
15. `ingest/news.py` + `reasoning/hype_ratio.py`
16. Docker deployment
17. MedGemma integration for deeper analysis
18. Comparison mode (intervention vs intervention)

## Coding Standards

- All functions have type hints
- Use async/await for API calls (httpx.AsyncClient)
- Pydantic v2 for all data models
- Structured logging with `loguru`
- Every ingest agent has a corresponding test with mock data
- Environment variables via pydantic-settings
- Error handling: never crash on a single failed API call — log and continue

## Running

```bash
# Install dependencies
pip install -e ".[dev]"

# Set up environment
cp .env.example .env
# Edit .env with your API keys

# Seed data for an intervention
python scripts/seed_intervention.py rapamycin

# Start API server
uvicorn src.api.main:app --reload --port 8000

# Start Streamlit frontend
streamlit run src/frontend/app.py

# Run tests
pytest tests/
```

## Deployment (if time allows)

```bash
docker-compose up --build
```

The docker-compose.yml should have:
- `api` service: FastAPI on port 8000
- `frontend` service: Streamlit on port 8501
- Shared volume for SQLite + ChromaDB data
- Environment variables from .env

## Key Principle

**The schema is the moat.** If the unified document schema and ingest pipeline are solid, adding new reasoning modules is trivial — each one is just a prompt + aggregation over well-structured data. Invest the most time in getting Phase 1 right.
