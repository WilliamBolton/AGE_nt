# CLAUDE.md — AGE-nt Evidence Grading Agent

**IMPORTANT: Read ARCHITECTURE.md before implementing anything.** It contains the full schema definitions, storage strategy, ingest pipeline design, and the rationale for every architectural decision. This file is the quick-start overview; ARCHITECTURE.md is the detailed reference.

## Project Overview

This is **AGE-nt** — an agentic system that scrapes, standardises, and reasons over scientific evidence for aging interventions. The core insight: the **data layer is the product**. Reasoning modules (evidence grading, trajectory scoring, gap analysis, hype ratio) are swappable consumers of a unified, temporally-indexed document store.

## Architecture

```
Sources (PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar,
         DrugAge, NIH Reporter, Patents, FDA, Tavily, Reddit/HN)
    ↓
Ingest Agents (one per source, no LLM calls — fast and dumb)
    ↓
Query Expander (LLM expands intervention name → search terms, once per intervention)
    ↓
Unified Document Schema (Base + 11 source-specific Pydantic subclasses)
    ↓
Storage (JSON files primary + SQLite structured queries)
    ↓
MCP Server (11 tools, SSE transport) / FastAPI (6 route modules)
    ↓
Reasoning Tools (Trajectory ✅, Edison ✅, Evidence Grader/Gap Spotter/Hype Ratio stubs)
    ↓
Frontends (React/TypeScript app)
```

## Tech Stack

- **Language:** Python 3.11+
- **API Framework:** FastAPI + uvicorn
- **Database:** JSON files (primary, human-readable) + SQLite (structured queries)
- **LLM:** OpenAI GPT-4o-mini (default) or Google Gemini (configurable via `LLM_PROVIDER`). Edison (PaperQA3) for deep medical reasoning.
- **Ingest:** httpx for API calls
- **MCP:** FastMCP server with 11 tools, SSE transport on port 8001
- **Frontend:** React/TypeScript (Vite) in `frontend/`

## Project Structure

```
bio-hack/
├── CLAUDE.md                    # This file
├── ARCHITECTURE.md              # Detailed schema, storage, pipeline design
├── FUTURE_WORK.md               # Roadmap and stretch goals
├── JSON_SCHEMA_REFERENCE.md     # Schema reference for MCP tool consumers
├── HACKATHON_BRIEF.md           # Original hackathon brief
├── README.md                    # Project readme
├── pyproject.toml               # Dependencies (use uv)
│
├── src/
│   ├── __init__.py
│   ├── config.py                # Settings, API keys, env vars (pydantic-settings)
│   │
│   ├── schema/
│   │   └── document.py          # Pydantic models: Base + 11 source-specific subclasses
│   │
│   ├── ingest/                  # 10 complete ingest agents (all async, no LLM calls)
│   │   ├── base.py              # Abstract base ingest agent
│   │   ├── query_expander.py    # LLM-based query expansion (once per intervention)
│   │   ├── pubmed.py            # PubMed E-utilities
│   │   ├── clinical_trials.py   # ClinicalTrials.gov v2 API
│   │   ├── europe_pmc.py        # Europe PMC (journals + preprints + Cochrane)
│   │   ├── semantic_scholar.py  # Semantic Scholar Graph API
│   │   ├── drugage.py           # DrugAge CSV (animal lifespan data)
│   │   ├── nih_reporter.py      # NIH Reporter API v2 (funding data)
│   │   ├── patents.py           # Lens.org API + Google Patents fallback
│   │   ├── fda.py               # FDA DailyMed API (regulatory)
│   │   ├── tavily.py            # Tavily web search (broad web)
│   │   ├── social.py            # Reddit/HN via Tavily (social sentiment)
│   │   └── google_trends.py     # Google Trends (standalone function, not a doc agent)
│   │
│   ├── storage/
│   │   ├── json_store.py        # JSON file storage (primary, dedup by source_url)
│   │   ├── sqlite_store.py      # SQLite structured metadata (INSERT OR REPLACE by id)
│   │   └── manager.py           # Unified StorageManager interface
│   │
│   ├── api/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── dependencies.py      # Shared deps
│   │   └── routes/
│   │       ├── interventions.py # /interventions endpoints
│   │       ├── ingest.py        # /ingest trigger
│   │       ├── reasoning.py     # /reasoning endpoints
│   │       ├── tools.py         # Dynamic tool discovery and execution
│   │       ├── chat.py          # Agentic LLM conversation with tool integration
│   │       └── pharma.py        # Pharma/biotech company profiles + due diligence
│   │
│   ├── tools/                   # Reasoning tools (wired to MCP)
│   │   ├── base.py              # Abstract base (stub)
│   │   ├── edison.py            # ✅ Edison/PaperQA3 wrapper (implemented)
│   │   ├── trajectory.py        # ✅ Temporal momentum scoring (implemented, 558 lines)
│   │   ├── sql_query.py         # ✅ SQL query safety layer (implemented)
│   │   ├── evidence_grader.py   # Evidence distribution scoring (stub)
│   │   ├── gap_spotter.py       # Missing evidence analysis (stub)
│   │   ├── hype_ratio.py        # Evidence vs media hype (stub)
│   │   └── report_generator.py  # Orchestrates all tools (stub)
│   │
│   ├── mcp_server/
│   │   └── server.py            # FastMCP server, 11 tools, SSE on port 8001
│   │
│   ├── stats/
│   │   └── summary.py           # Deterministic summary generation
│   │
│   └── frontend/
│       └── app.py               # Streamlit (placeholder)
│
├── frontend/                    # React/TypeScript app (Vite)
│   ├── src/                     # React components
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
│
├── scripts/
│   ├── seed_intervention.py     # CLI: ingest all sources for one intervention
│   ├── seed_all.py              # CLI: batch ingest with checkpoint/resume
│   ├── generate_summary.py      # CLI: generate summary stats
│   ├── compile_profiles.py      # CLI: generate pharma/biotech company profiles
│   ├── generate_bj_quotes.py    # CLI: generate Bryan Johnson stances dataset
│   └── llm_api_test.py          # Test LLM API connectivity
│
├── tests/
│   ├── test_schema.py
│   ├── test_ingest_pubmed.py
│   └── test_evidence_grader.py
│
└── data/
    ├── interventions.json       # 55 interventions with aliases + categories
    ├── documents/               # {intervention}.json — one file per intervention
    ├── classifications/         # {intervention}.json — LLM classification results
    ├── summary/                 # {intervention}.json — summary stats
    ├── trends/                  # Google Trends data
    ├── query_cache/             # Cached LLM query expansions
    ├── drugage/                 # DrugAge CSV data
    ├── anage/                   # AnAge database
    ├── pharma_profiles/         # {company}.json — pharma company profiles
    ├── biotech_profiles/        # {company}.json — biotech startup profiles
    ├── bryan_johnson.json       # Bryan Johnson intervention stances
    ├── age_nt.db                # SQLite database (mirrors JSON)
    ├── seed_all.log             # Batch seeding log
    └── seed_summary.json        # Last batch seed results
```

## Document Schema

Defined in `src/schema/document.py`. Uses **Base + source-specific subclasses** with Pydantic discriminated unions. This is the most critical design decision — see ARCHITECTURE.md Section 1 for full rationale.

- **BaseDocument**: Common fields (id, source_type, intervention, title, abstract, source_url, dates). Classification fields (evidence_level, organism, etc.) are **nullable** — filled later by reasoning agents, not at ingest.
- **11 subclasses**: PubMedDocument, ClinicalTrialDocument, EuropePMCDocument, SemanticScholarDocument, DrugAgeDocument, NIHGrantDocument, PatentDocument, RegulatoryDocument, PreprintDocument, NewsDocument, SocialDocument
- **12 SourceTypes**: pubmed, clinicaltrials, europe_pmc, semantic_scholar, drugage, nih_grant, patent, regulatory, preprint, news, social, google_trends
- **Discriminated union**: `Document = Annotated[Union[...], Field(discriminator="source_type")]` — auto-picks correct subclass on deserialization

## API Endpoints

```
# Interventions
GET  /interventions                              → List all indexed interventions
GET  /interventions/{name}/documents             → All docs, filterable by:
                                                     ?source_type=pubmed
                                                     ?evidence_level=1,2
                                                     ?date_from=2020-01-01
                                                     ?organism=human
GET  /interventions/{name}/timeline              → Temporal aggregation (studies per level per year)
GET  /interventions/{name}/stats                 → Comprehensive summary stats
GET  /interventions/{name}/trends                → Google Trends data
GET  /interventions/{name}/gaps                  → Gap analysis results
GET  /interventions/{name}/hype                  → News/social sentiment over time
POST /interventions/{name}/report                → Trigger full reasoning pipeline → structured JSON report
POST /query                                      → Semantic search across all docs
POST /ingest                                     → Trigger ingest for a new intervention

# Pharma/Biotech
GET  /pharma/profiles                            → List all pharma company profiles
GET  /pharma/{company}                           → Get pharma company profile
GET  /biotech/profiles                           → List all biotech startup profiles
GET  /biotech/{company}                          → Get biotech company profile
GET  /pharma/dd/{company}                        → Due diligence analysis

# Tools & Chat
POST /tools                                      → Dynamic tool discovery and execution
POST /chat                                       → Agentic LLM conversation with tool integration
```

## Key Implementation Notes

### Ingest Agents

All 10 agents in `src/ingest/` follow the same pattern:
1. Accept intervention name + aliases + query_expansion (from LLM expander)
2. Query source API
3. Parse response into typed Pydantic subclass (no LLM calls)
4. Return a list of source-specific Document objects
5. Handle rate limits via internal sleeps

**Agents are fast and dumb — no LLM classification at ingest time.** Query expansion (synonym generation) is the only LLM call, run once per intervention before agents execute.

### LLM Classification
- Classification happens ON DEMAND when reasoning tools need it, NOT at ingest time
- Classification fields (evidence_level, organism, etc.) are None at ingest
- Results cached in `data/classifications/` so they persist
- See ARCHITECTURE.md Sections 3-4 for the classification pipeline design

### Storage
- **JSON files**: Primary store. One file per intervention in `data/documents/`. Dedup by `source_url`.
- **SQLite**: Mirrors JSON for structured queries. INSERT OR REPLACE by document `id`.
- **StorageManager**: Single interface that writes to both. All consumers use this — never raw file/db access.
- See ARCHITECTURE.md Section 2 for the dual storage rationale.

### Reasoning Tools

Located in `src/tools/`. Tools can involve LLM calls and can also call other tools — the orchestration is nested and hierarchical but adaptive, not a static graph.

**Implemented:**
- **Edison** (`src/tools/edison.py`): PaperQA3 wrapper for deep medical reasoning. Job types: literature, literature_high, precedent, analysis, molecules.
- **Trajectory Scorer** (`src/tools/trajectory.py`, 558 lines): Computes velocity metrics (recent vs historical publication rates, acceleration), diversification (Shannon entropy over source types), trial pipeline metrics (phase/status breakdowns, pipeline velocity), and time-series data (yearly/cumulative counts, trends overlay).
- **SQL Query** (`src/tools/sql_query.py`): Safety layer for read-only SQL queries — validates queries, blocks writes, rewrites `SELECT *` to exclude heavy columns.

**Stubs to implement**: Evidence Grader, Gap Spotter, Hype Ratio, Report Generator. Each should query StorageManager and return structured results. MCP server already has matching tool definitions with dynamic fallback to `src/tools/`.

## Environment Variables

```
# LLM (one or both)
LLM_PROVIDER=openai          # "openai" (default) or "gemini"
OPENAI_API_KEY=              # OpenAI API key (GPT-4o-mini default)
GEMINI_API_KEY=              # Google Gemini API key

# External APIs
NCBI_API_KEY=                # NCBI (optional, increases PubMed rate limit 3→10 req/s)
TAVILY_API_KEY=              # Tavily web search + social
EDISON_API_KEY=              # Edison/PaperQA3 (optional, for deep analysis)

# Storage
DATABASE_URL=sqlite:///data/age_nt.db

# Logging
LOG_LEVEL=INFO
```

## Current Status

### Built
- **Schema**: Base + 11 source-specific Pydantic subclasses with discriminated union. Classification fields use `exclude=True` (stored separately in `data/classifications/`).
- **Ingest**: 10 agents (PubMed, ClinicalTrials, Europe PMC, Semantic Scholar, DrugAge, NIH Reporter, Patents, FDA, Tavily, Social) + Google Trends + LLM query expander
- **Storage**: JSON + SQLite dual store with StorageManager, deduplication
- **API**: FastAPI with 6 route modules (interventions, ingest, reasoning, tools, chat, pharma)
- **MCP Server**: 11 tools (7 functional, 4 stubs with dynamic tool fallback), SSE transport
- **Scripts**: `seed_intervention.py`, `seed_all.py` (batch), `generate_summary.py`, `compile_profiles.py`, `generate_bj_quotes.py`
- **Tools**: Edison/PaperQA3, Trajectory Scorer (fully implemented), SQL Query safety layer
- **Data**: 55 interventions, 15 pharma profiles, 10 biotech profiles, Bryan Johnson stances
- **Frontend**: React/TypeScript app in `frontend/`

### Next to build
- Reasoning tools: Evidence Grader, Gap Spotter, Hype Ratio, Report Generator (see FUTURE_WORK.md)
- Wire remaining reasoning tools into MCP server stubs

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
uv sync

# Set up environment
cp .env.example .env
# Edit .env with your API keys

# Seed data for a single intervention
uv run python scripts/seed_intervention.py rapamycin

# Batch seed all 55 interventions (overnight)
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

## Key Principle

**The schema is the moat.** If the unified document schema and ingest pipeline are solid, adding new reasoning modules is trivial — each one is just a prompt + aggregation over well-structured data. Invest the most time in getting Phase 1 right.
