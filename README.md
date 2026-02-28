# AGE-nt

Intervention intelligence for aging. Real data, transparent scores, no hallucinations.

An agentic system that scrapes, standardises, and reasons over scientific evidence for aging interventions. The core insight: the **data layer is the product**. Reasoning modules (evidence grading, trajectory scoring, gap analysis, hype ratio) are swappable consumers of a unified, temporally-indexed document store.

## How it works

```
Sources (PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar,
         DrugAge, NIH Reporter, Patents, FDA, Tavily, Reddit/HN)
    ↓
Ingest Agents (one per source, fast & dumb — no LLM at ingest)
    ↓
Query Expander (LLM expands intervention → search terms, once per intervention)
    ↓
Unified Document Schema (Base + 11 source-specific Pydantic subclasses)
    ↓
Dual Storage (JSON files primary + SQLite structured queries)
    ↓
MCP Server (11 tools, SSE) / FastAPI (6 route modules)
    ↓
Reasoning Tools (Trajectory ✅, Edison ✅, + stubs)
    ↓
Frontends (React/TypeScript app, MCP via Claude Desktop)
```

## Quick start

```bash
# Install dependencies
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your API keys (see Environment Variables below)

# Seed data for an intervention
uv run python scripts/seed_intervention.py rapamycin

# Seed specific sources only
uv run python scripts/seed_intervention.py rapamycin --sources pubmed,europe_pmc,nih_reporter,fda

# Batch seed all 55 interventions
uv run python scripts/seed_all.py                          # all sources
uv run python scripts/seed_all.py --skip-tavily            # conserve Tavily credits
uv run python scripts/seed_all.py --start-from metformin   # resume after crash
uv run python scripts/seed_all.py --dry-run                # preview only

# Start MCP server (for Claude Desktop / ChatGPT)
uv run python -m src.mcp_server.server

# Start API server
uvicorn src.api.main:app --reload --port 8000

# Start React frontend
cd frontend && npm run dev

# Run tests
pytest tests/
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

## MCP Tools

The MCP server exposes 11 tools on port 8001 (SSE transport). The calling LLM decides which tools to invoke and in what order — adaptive orchestration, not a static pipeline.

| Tool | Status | Description |
|------|--------|-------------|
| `list_interventions` | ✅ | List all 55 indexed interventions with doc counts |
| `get_intervention_stats` | ✅ | Comprehensive summary stats per intervention |
| `search_documents` | ✅ | Full-text search across all docs |
| `get_evidence_trajectory` | ✅ | Velocity, diversification, trial pipeline metrics |
| `get_bryan_johnson_take` | ✅ | Bryan Johnson's stance on an intervention |
| `sql_query` | ✅ | Read-only SQL against the documents table |
| `run_python` | ✅ | Execute Python for analysis/visualisation |
| `get_evidence_grade` | stub | Evidence distribution scoring |
| `get_evidence_gaps` | stub | Missing evidence analysis |
| `get_hype_ratio` | stub | Evidence vs media hype comparison |
| `get_full_report` | stub | Orchestrate all reasoning tools |

## Environment variables

```bash
# LLM (for query expansion — not used during ingest)
LLM_PROVIDER=openai                    # or "gemini"
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# External APIs (all optional)
NCBI_API_KEY=...                       # Increases PubMed rate limit (3 -> 10 req/sec)
TAVILY_API_KEY=...                     # Required for web search agent only
EDISON_API_KEY=...                     # Edison/PaperQA3 (optional, for deep analysis)

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
    semantic_scholar.py     # Semantic Scholar Academic Graph
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
  api/
    main.py                 # FastAPI app entry
    routes/
      interventions.py      # /interventions endpoints
      ingest.py             # /ingest trigger
      reasoning.py          # /reasoning endpoints
      tools.py              # Dynamic tool discovery and execution
      chat.py               # Agentic LLM conversation with tool integration
      pharma.py             # Pharma/biotech profiles + due diligence
  tools/
    edison.py               # ✅ Edison/PaperQA3 wrapper
    trajectory.py           # ✅ Temporal momentum scoring (558 lines)
    sql_query.py            # ✅ SQL query safety layer
    evidence_grader.py      # Evidence distribution scoring (stub)
    gap_spotter.py          # Missing evidence analysis (stub)
    hype_ratio.py           # Evidence vs media hype (stub)
    report_generator.py     # Orchestrates all tools (stub)
  mcp_server/
    server.py               # FastMCP server, 11 tools, SSE on port 8001
  stats/
    summary.py              # Deterministic summary generation
  frontend/
    app.py                  # Streamlit (placeholder)

frontend/                   # React/TypeScript app (Vite)
  src/                      # React components
  index.html
  vite.config.ts

scripts/
  seed_intervention.py      # CLI to ingest data for one intervention
  seed_all.py               # CLI batch ingest with checkpoint/resume
  generate_summary.py       # CLI generate summary stats
  compile_profiles.py       # CLI generate pharma/biotech profiles
  generate_bj_quotes.py     # CLI generate Bryan Johnson stances

data/
  interventions.json        # 55 interventions with aliases + categories
  documents/                # Per-intervention JSON files
  classifications/          # LLM classification results (populated by reasoning)
  summary/                  # Summary stats per intervention
  trends/                   # Google Trends time series data
  query_cache/              # Cached LLM query expansions
  drugage/                  # DrugAge CSV data
  anage/                    # AnAge database
  pharma_profiles/          # Pharma company profiles (15 companies)
  biotech_profiles/         # Biotech startup profiles (10 companies)
  bryan_johnson.json        # Bryan Johnson intervention stances
  age_nt.db                 # SQLite database (mirrors JSON)
```

## Document schema

Every scraped item is normalised into a typed Pydantic model. The base `BaseDocument` has common fields (id, source_type, intervention, title, abstract, dates). Classification fields (`evidence_level`, `organism`, etc.) use `exclude=True` — they're stored separately in `data/classifications/` and populated by reasoning agents after ingest. Source-specific subclasses add their own fields:

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

**Adaptive orchestration.** The MCP server exposes tools; the calling LLM decides which to invoke and in what order. Tools can nest (call LLMs, call other tools). No static DAG — the LLM figures out the workflow based on the user's question.

**Dual storage.** JSON files are human-readable and debuggable. SQLite enables SQL queries and temporal aggregations. Both are written to on every ingest via `StorageManager`.

**Temporal analysis is a first-class feature.** Clinical trials have 4 lifecycle dates. Grants have start/end dates. Google Trends gives interest over time. This powers trajectory scoring.

**Graceful degradation.** Every agent catches its own errors — a failed API call logs a warning and continues. Missing API keys skip the agent. Exhaustion flags prevent retrying dead APIs.

## Interventions

The system ships with **55 interventions** across 16 categories in `data/interventions.json`, including:

- **Rapamycin** (sirolimus) — mTOR inhibition
- **Metformin** (glucophage) — metabolic intervention
- **NAD+ precursors** (NMN, NR) — NAD metabolism
- **Senolytics** (dasatinib+quercetin, fisetin) — senescent cell clearance
- **Young plasma** (parabiosis) — systemic factors
- **Hyperbaric oxygen therapy** (HBOT) — oxygen therapy
- **Epigenetic reprogramming** (Yamanaka factors, OSKM) — epigenetic intervention
- And 48 more across categories: anti-inflammatory, autophagy induction, cell therapy, dietary intervention, neuroprotection, sirtuin activation, telomere intervention, etc.

## Tech stack

- **Python 3.11+** with type hints throughout
- **Pydantic v2** for all data models
- **httpx** for async HTTP
- **aiosqlite** for async SQLite
- **FastAPI** for the API layer
- **FastMCP** for the MCP server (SSE transport)
- **React/TypeScript** (Vite) for the frontend
- **loguru** for structured logging
- **pytrends** for Google Trends data
