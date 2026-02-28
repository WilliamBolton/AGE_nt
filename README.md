# AGE-nt

An agentic system that scrapes, standardises, and reasons over scientific evidence for aging interventions. The core insight: the **data layer is the product**. Reasoning modules (evidence grading, trajectory scoring, gap analysis, hype ratio) are swappable consumers of a unified, temporally-indexed document store.

## How it works

```
Sources (PubMed, Europe PMC, ClinicalTrials.gov, NIH Reporter, FDA, Patents, Reddit, News, Google Trends)
    |
Ingest Agents (one per source, fast & dumb — no LLM at ingest)
    |
Unified Document Schema (every item normalised to typed Pydantic models)
    |
Dual Storage (JSON files for human readability + SQLite for structured queries)
    |
FastAPI (query, filter, aggregate, trigger reasoning)
    |
Reasoning Modules (Evidence Grader, Trajectory Scorer, Gap Spotter, Hype Ratio)
    |
Frontends (Streamlit demo)
```

## Quick start

```bash
# Install dependencies
pip install -e ".[dev]"
# or with uv:
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your API keys (see Environment Variables below)

# Seed data for an intervention
python scripts/seed_intervention.py rapamycin

# Seed specific sources only
python scripts/seed_intervention.py rapamycin --sources pubmed,europe_pmc,nih_reporter,fda

# Adjust results per source
python scripts/seed_intervention.py metformin --max-results 100
```

## Data sources

AGE-nt ingests from **11 sources** across 10 agents:

| Agent | Source | What it captures | Auth needed |
|-------|--------|-----------------|-------------|
| **PubMed** | NCBI E-utilities | Journal articles, 3-tier relevance scoring | Optional (NCBI key for higher rate limit) |
| **ClinicalTrials.gov** | CT.gov v2 API | Clinical trials with full lifecycle dates | No |
| **Europe PMC** | Europe PMC REST | Journals + preprints + Cochrane reviews, deduped against PubMed | No |
| **Semantic Scholar** | S2 Academic Graph | Papers with citation counts + influential citation counts | No |
| **DrugAge** | Local CSV | Animal lifespan studies with quantitative change data | No (manual CSV) |
| **NIH Reporter** | NIH Reporter v2 | Federally funded research grants, NIA funding signal | No |
| **Patents** | Lens.org / Google Patents | Patent filings as commercial interest signal | No |
| **FDA / DailyMed** | DailyMed + openFDA | Approved drug labels, indications, warnings | No |
| **Web Search** | Tavily API | News and media articles (academic URLs filtered) | TAVILY_API_KEY |
| **Reddit** | Reddit JSON API | Social discussion from longevity subreddits | No |
| **Google Trends** | pytrends | Interest-over-time data (not a document — feeds hype ratio) | No |

## Environment variables

```bash
# LLM (for query expansion — not used during ingest)
LLM_PROVIDER=openai                    # or "gemini"
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# External APIs (all optional)
NCBI_API_KEY=...                       # Increases PubMed rate limit (3 -> 10 req/sec)
TAVILY_API_KEY=...                     # Required for web search agent only

# Storage
DATABASE_URL=sqlite:///data/age_nt.db

# Logging
LOG_LEVEL=INFO
```

## Project structure

```
src/
  schema/document.py        # Pydantic models — the core of everything
  config.py                 # Settings, API keys, env vars
  ingest/
    base.py                 # Abstract base agent
    pubmed.py               # PubMed E-utilities
    clinical_trials.py      # ClinicalTrials.gov v2
    europe_pmc.py           # Europe PMC (journals, preprints, Cochrane)
    semantic_scholar.py      # Semantic Scholar Academic Graph
    drugage.py              # DrugAge CSV (animal lifespan data)
    nih_reporter.py         # NIH Reporter grants
    patents.py              # Lens.org / Google Patents
    fda.py                  # FDA DailyMed + openFDA
    tavily.py               # Tavily web search (news/media)
    social.py               # Reddit
    google_trends.py        # Google Trends (time series, not documents)
    query_expander.py       # LLM-powered search term expansion
  storage/
    json_store.py           # JSON file storage (one file per intervention)
    sqlite_store.py         # SQLite for structured queries
    manager.py              # Unified facade over both stores
  api/                      # FastAPI endpoints (TODO)
  reasoning/                # Evidence grading, trajectory, gaps (TODO)
  frontend/                 # Streamlit demo (TODO)

scripts/
  seed_intervention.py      # CLI to ingest data for one intervention

data/
  interventions.json        # 7 canonical interventions with aliases
  documents/                # Per-intervention JSON files
  classifications/          # LLM classification results (populated by reasoning)
  trends/                   # Google Trends time series data
  query_cache/              # Cached LLM query expansions
  drugage/                  # Place drugage_database.csv here
```

## Document schema

Every scraped item is normalised into a typed Pydantic model. The base `BaseDocument` has common fields (id, source_type, intervention, title, abstract, dates). Source-specific subclasses add their own fields:

- `PubMedDocument` — PMID, DOI, MeSH terms, journal, publication types
- `ClinicalTrialDocument` — NCT ID, phase, status, enrollment, 4 lifecycle dates
- `EuropePMCDocument` — PMCID, citation count, Cochrane/preprint flags
- `SemanticScholarDocument` — citation count, influential citations, TLDR
- `DrugAgeDocument` — species, strain, dosage, lifespan change %, significance
- `GrantDocument` — project number, PI, funding amount, NIH institute
- `PatentDocument` — patent ID, assignee, inventors, filing/grant dates
- `RegulatoryDocument` — approved indications, drug class, warnings, NDA number
- `NewsDocument` — outlet, sentiment, claims strength
- `SocialDocument` — platform, score, comment count

Deserialization uses a Pydantic discriminated union on `source_type` — each document automatically resolves to the correct subclass.

## Design principles

**Schema is the moat.** If the unified document schema and ingest pipeline are solid, adding new reasoning modules is trivial.

**Scrape first, reason later.** Ingest agents are fast and dumb — no LLM calls at ingest time. Classification happens on demand when reasoning modules need it.

**Dual storage.** JSON files are human-readable and debuggable. SQLite enables SQL queries and temporal aggregations. Both are written to on every ingest via `StorageManager`.

**Temporal analysis is a first-class feature.** Clinical trials have 4 lifecycle dates. Grants have start/end dates. Google Trends gives interest over time. This powers trajectory scoring.

**Graceful degradation.** Every agent catches its own errors — a failed API call logs a warning and continues. Missing API keys skip the agent. Missing CSV files return empty lists.

## Example interventions

The system ships with 7 canonical interventions in `data/interventions.json`:

- **Rapamycin** (sirolimus) — mTOR inhibition
- **Metformin** (glucophage) — metabolic intervention
- **NAD+ precursors** (NMN, NR) — NAD+ metabolism
- **Senolytics** (dasatinib+quercetin, fisetin) — senescent cell clearance
- **Young plasma** (parabiosis) — systemic factors
- **Hyperbaric oxygen therapy** (HBOT) — oxygen therapy
- **Epigenetic reprogramming** (Yamanaka factors, OSKM) — epigenetic intervention

## Tech stack

- **Python 3.11+** with type hints throughout
- **Pydantic v2** for all data models
- **httpx** for async HTTP
- **aiosqlite** for async SQLite
- **FastAPI** for the API layer
- **Streamlit** for the demo frontend
- **loguru** for structured logging
- **pytrends** for Google Trends data
