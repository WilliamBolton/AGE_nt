# FUTURE_WORK.md — Stretch Goals & Post-Hackathon Roadmap

## Next: MCP Reasoning Tools

These tools consume existing data via `StorageManager` and expose reasoning through the MCP server. The stub definitions already exist in `src/mcp_server/server.py` and empty tool files in `src/tools/`.

### T1. Hype-to-Evidence Ratio Tool
- Cross-reference social/news/Tavily data against evidence grade
- Produce a "Bull/Bear Index" — hype volume vs evidence strength
- Visual: hype curve overlaid on evidence accumulation timeline
- **Why it matters:** Immediately identifies overmarketed interventions with weak evidence

### T2. Intervention Comparison Tool
- `compare_interventions(interventions=["rapamycin", "metformin", "NMN"])`
- Side-by-side evidence profiles, trajectory overlays, gap comparison
- Radar chart visualisation across evidence levels
- **Why it matters:** Killer feature for VC due diligence — comparing pipeline candidates

### T3. Contradiction & Fragility Detection Tool
- Within each evidence level, assess whether studies agree or conflict
- Use LLM to compare key findings pairwise
- Output a "consensus fragility score" — high when studies disagree
- Flag if all positive results come from <3 independent labs
- **Why it matters:** 10 conflicting studies ≠ 10 confirming studies, but naive counting misses this

### T4. Evidence Grader & Gap Spotter Tools
- Already stubbed in MCP server and `src/tools/`
- Evidence Grader: count studies per evidence level, weight by sample size, compute composite confidence score
- Gap Spotter: check for missing evidence types, flag no human data / no RCTs / single-lab results

### ✅ T5. Temporal Analysis & Trajectory Tools (Implemented)
- **Trajectory Scorer** (`src/tools/trajectory.py`, 558 lines): Fully implemented with VelocityMetrics (recent vs historical publication rates, acceleration), DiversificationMetrics (Shannon entropy over source types), TrialPipelineMetrics (phase/status breakdowns, pipeline velocity), and plot-ready time series (yearly/cumulative counts, trends overlay).
- **Cross-source timeline**: Combines temporal signals from all sources — `date_published` (papers), `filing_date`/`grant_date` (patents), `grant_start`/`fiscal_year` (NIH), `approval_date` (FDA), `date_peer_published` (preprints)
- **MCP tool**: `get_evidence_trajectory` is functional and calls the trajectory scorer directly

### T6. Demo / Frontend
- Streamlit or lightweight web app showing how a pharma/VC user would interact with the system
- Key screens: intervention dashboard (evidence profile, trajectory chart, gap analysis), comparison view, search
- Judges assessing **market fit, innovation, commercial viability** — demo needs to tell a story about who uses this and why
- Show the MCP flow: Claude Desktop calling tools, getting real data, generating analysis vs generic LLM knowledge
- Consider a "pharma due diligence" walkthrough: pick an intervention, show evidence grade, timeline, gaps, hype ratio — the full pipeline

### T7. Summarisation Tool
- LLM-based summarisation of ingested documents for an intervention — NOT classification of individual docs, but generating a structured overview
- Reads raw docs from StorageManager, sends batches to LLM (title + abstract + key metadata), produces structured summary per intervention
- Output saved to `data/summaries/{intervention}.json` as a new data artifact (not modifying source docs)
- Could populate classification fields (evidence_level, organism, study_type, effect_direction) as a side effect, cached in `data/classifications/`
- Prompt template designed in ARCHITECTURE.md Section 4 — sends title + abstract + MeSH/publication_types to get structured JSON back
- Run on-demand when a report is requested, or batch after a big scrape
- **Why it matters:** Bridge between raw data and reasoning tools — Evidence Grader and Gap Spotter need classified docs to function properly

## Completed

### ✅ MCP Server (S6)
- `src/mcp_server/server.py` — FastMCP server with 11 tools, SSE transport on port 8001
- 7 functional tools: list_interventions, get_intervention_stats, search_documents, get_evidence_trajectory, get_bryan_johnson_take, sql_query, run_python
- 4 stubs with dynamic tool fallback: get_evidence_grade, get_evidence_gaps, get_hype_ratio, get_full_report
- **Claude Desktop setup:** Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "age-nt": {
        "url": "http://localhost:8001/sse"
      }
    }
  }
  ```
- **Run:** `.venv/bin/python -m src.mcp_server.server` then restart Claude Desktop

### ✅ Patent & Funding Signals (S5)
- `src/ingest/patents.py` — Lens.org API with Google Patents scrape fallback
- `src/ingest/nih_reporter.py` — NIH Reporter API v2 with NIA boost scoring
- Both fully integrated into the ingest pipeline

### ✅ Batch Seeding with Checkpoint/Resume (seed_all.py)
- `scripts/seed_all.py` — overnight batch runner for all 55 interventions
- `--start-from` for resume after crash, `--category` filter, `--dry-run`, `--skip-tavily`
- Per-source error tracking, ETA, summary JSON saved to `data/seed_summary.json`
- File logging to `data/seed_all.log`

## Stretch Goals

### S8. Landscape Explorer (Frontend)
- Interactive scatter plot of all 25 biotechs: evidence score vs research momentum
- Filters by category, stage, funding range, hallmark
- Comparison mode: select 2-3 biotechs for side-by-side profile view
- Component already built at `frontend/src/pages/LandscapeExplorer.tsx` — just needs wiring back into nav and routes
- Depends on pre-computed analysis data or live tool calls for evidence/trajectory scores

### S7. Pre-compute Analysis Pipeline
- `scripts/precompute_analysis.py` — batch-run all reasoning tools across all 54 interventions, save outputs as static JSON to `data/analysis/{tool}/{intervention}.json`
- Dynamic tool discovery: imports from `src/tools/` and auto-detects available tools via `discover_tools()`
- Runs only the tools that exist — if a teammate adds a new tool tomorrow, the script picks it up automatically
- Produces an `index.json` manifest with summary scores per intervention
- Not needed now — the API caches tool outputs on first request. Useful later for warming caches or CDN deployment
- Could run as a CI/CD step after tool code changes to keep cached data fresh

### On-Demand Ingest via MCP
- Add an `ingest_intervention` MCP tool that triggers the full scraping pipeline for new interventions
- If a user asks about an intervention not in the database, the LLM can scrape it on the fly
- Wraps the existing `seed_intervention.py` logic as an async MCP tool
- Also useful: `add_intervention` tool to register new canonical names + aliases before ingesting
- **Why it matters:** Makes the system self-expanding — the LLM autonomously grows the evidence base based on user questions

## Deprioritised

### MedGemma Deep Analysis
- Edison (PaperQA3) already covers deep medical reasoning via `src/tools/edison.py`
- Job types `literature_high`, `analysis`, `molecules` handle endpoint relevance, mechanism plausibility, contradiction detection
- Revisit only if Edison proves insufficient for a specific reasoning task

---

## Post-Hackathon Roadmap

### Phase 1: Production Data Layer (Weeks 1-4)

#### Full-Text Ingestion
- Currently limited to titles + abstracts from PubMed
- Add Unpaywall API integration for open-access full texts
- Semantic chunking of full papers for more granular evidence extraction
- Extract specific data: effect sizes, confidence intervals, p-values, dosing protocols

#### Expanded Source Coverage
- **Already built**: PubMed, ClinicalTrials.gov, Europe PMC (journals + preprints + Cochrane), Semantic Scholar, DrugAge, NIH Reporter, Patents, FDA/DailyMed, Tavily web search, Reddit, Google Trends, AnAge, Edison (PaperQA3)
- **Next to add**: Conference abstracts (scrape aging conference proceedings), EMA opinions, ITP results (structured data from NIA Interventions Testing Program), YouTube (longevity influencer hype signal), Podcast transcripts (Huberman, Attia, Sinclair)
- **Semantic search layer**: Add ChromaDB or similar vector DB for embedding-based search across all documents. Currently using SQL LIKE search — semantic search would surface papers by meaning rather than keywords.

#### Continuous Ingest Pipeline
- Replace manual seeding with scheduled cron jobs
- PubMed RSS feeds for real-time new publication alerts
- ClinicalTrials.gov RSS for trial status changes
- Webhook triggers when new evidence changes a confidence score

#### Better Entity Resolution
- Build an intervention ontology: rapamycin = sirolimus = Rapamune = mTOR inhibitor (class)
- Map interventions to MeSH terms, ChEBI IDs, DrugBank IDs
- Hierarchical grouping: specific compounds → drug classes → mechanisms → hallmarks

### Phase 2: Advanced Reasoning (Weeks 4-8)

#### Calibrated Confidence Scoring
- Move beyond simple weighted averages
- Bayesian scoring: prior from mechanism plausibility, updated by each piece of evidence
- Uncertainty quantification: confidence intervals, not point estimates
- Benchmark against expert assessments (e.g., compare our scores to published systematic reviews)

#### Causal Reasoning
- Distinguish correlation from causation in observational studies
- Assess Bradford Hill criteria automatically for each intervention
- Flag confounding factors mentioned in studies

#### Dose-Response Analysis
- Extract dosing information from studies
- Flag when animal doses don't have human-equivalent translations
- Identify optimal dose ranges where evidence converges

#### Multi-Intervention Interaction
- Some interventions may synergise or conflict
- Map known drug interactions
- Identify interventions targeting the same pathway (redundancy detection)

### Phase 3: Product & Deployment (Weeks 8-16)

#### Two-Track Frontend
1. **Consumer app** (Streamlit → Next.js): "Is this supplement worth taking?" Simple evidence report, traffic-light scoring, plain language
2. **Pharma/VC dashboard** (React): Full pipeline due diligence, comparison mode, temporal charts, exportable reports, team collaboration

#### Report Export
- Generate PDF evidence reports (structured, branded)
- DOCX export for integration into investment memos
- Slide deck auto-generation for board presentations

#### User Accounts & Alerts
- Save watchlists of interventions
- Email alerts when evidence profile changes significantly
- API keys for programmatic access (for biotech clients)

#### Deployment
- Move from SQLite to PostgreSQL
- Deploy on GCP/AWS with managed vector DB (Pinecone or Weaviate Cloud)
- CI/CD pipeline with GitHub Actions
- Rate limiting, authentication, usage tracking

### Phase 4: Ecosystem (Months 4-12)

#### Community & Validation
- Open-source the evidence schema as a standard
- Build a community of aging researchers who validate and correct classifications
- Human-in-the-loop feedback to improve LLM classification accuracy over time

#### Integration Partners
- Plugin for systematic review tools (Covidence, Rayyan)
- Integration with reference managers (Zotero, Mendeley)
- API for longevity news sites and podcasts to embed evidence grades

#### MCP Platform Integrations (Production)
- Harden the MCP server from hackathon demo to production: add OAuth authentication, rate limiting, usage analytics
- Publish as a verified ChatGPT connector (remove developer mode requirement)
- Publish to Claude's MCP marketplace
- Add MCP tools for advanced workflows: `compare_interventions`, `monitor_intervention` (set up alerts), `export_report_pdf`
- Support MCP tool composition — let the LLM chain tools (e.g., search → grade → compare in a single conversation)
- Explore integration with other MCP-compatible platforms as the ecosystem grows (Cursor, Windsurf, custom agents)
- Enterprise deployment: self-hosted MCP server behind customer's firewall with their proprietary data layered on top of public evidence

#### Regulatory Intelligence
- Track FDA/EMA pipeline for aging-adjacent indications
- Map clinical trial failures and their implications for the evidence base
- Predict which interventions are most likely to reach Phase 3 based on trajectory patterns

---

## Agent Data Access Strategy

### Current: JSON Tool Functions (Active)
Agents access data through thin Python tool functions that read from JSON files (`data/documents/{intervention}.json`). JSON is the source of truth — one file per intervention, self-contained, human-debuggable.

Tool functions handle filtering and field selection so agents never load full files into context:
- `search_documents(intervention, source_type, date_from, fields, limit)` — filtered rows with only requested fields
- `count_documents(intervention, source_type, ...)` — returns counts, no content
- `get_document(intervention, doc_id)` — single doc by ID, full detail
- `get_stats(intervention)` — aggregate counts by source type, year, etc.
- `get_trends(intervention)` — Google Trends time-series data

The `fields` parameter is key — an agent asking for `["title", "pmid", "date_published"]` gets ~3 fields per doc instead of 20+. This keeps context lean.

See `JSON_SCHEMA_REFERENCE.md` for the full schema reference agents use to know which fields and filters are available.

### Active: SQLite Query Layer via MCP
The `sql_query` MCP tool provides read-only SQL access to the documents table. Cross-intervention queries (e.g. "which intervention has the most Phase 3 trials?", "rank all interventions by evidence volume") are now possible via SQL. The tool validates queries (blocks writes), rewrites `SELECT *` to exclude heavy columns, and enforces LIMIT clauses. Safety layer in `src/tools/sql_query.py`.

---

## Technical Debt

### Essential (before/during big scrapes)
- [x] Add retry logic with exponential backoff for external APIs (`seed_all.py`: `_ingest_with_retry`, 3 attempts, 5/10/20s backoff)
- [x] Rate limit monitoring — transient errors logged with attempt counts in `data/seed_all.log`
- [ ] Review agent timeouts — 30s default may be too short for Europe PMC with 100+ results; too long to waste on a dead endpoint

### Nice to have
- [x] Move to concurrent ingest (`seed_all.py`: `asyncio.gather` across all agents per intervention, sequential storage writes)
- [x] Implement document deduplication (same study appearing in PubMed + Europe PMC — dedup by DOI/PMID)
- [x] Batch seeding with checkpoint/resume (`scripts/seed_all.py`)
- [ ] Proper database migrations (Alembic for SQLite→Postgres transition)
- [ ] Comprehensive test suite with fixtures for each source API
- [ ] LLM response caching with TTL to reduce API costs
- [ ] Consolidate document schemas — 11 subclasses may be more than needed long-term
- [ ] Add data freshness tracking — flag when an intervention's data is stale and needs re-ingestion
- [ ] Add embedding model versioning (re-embed when model changes)

## Influencer & KOL Takes

Currently `get_bryan_johnson_take` uses hardcoded quotes in `data/bryan_johnson.json` (representative paraphrases of his known public positions). Future work:

- [ ] **Live X/Twitter integration**: Pull real-time tweets from longevity influencers (Bryan Johnson, David Sinclair, Peter Attia, Rhonda Patrick, Andrew Huberman) via X API, filter for mentions of tracked interventions
- [ ] **Podcast transcript mining**: Index transcripts from longevity podcasts (Huberman Lab, The Drive, FoundMyFitness) and extract intervention-specific claims
- [ ] **Sentiment tracking over time**: Track how influencer sentiment on specific interventions changes (e.g. Bryan Johnson dropping metformin)
- [ ] **Influencer agreement matrix**: Compare which influencers agree/disagree on each intervention
- [ ] **Add more influencer profiles**: Extend the pattern to other KOLs (each gets a `data/{name}.json` file)
- [ ] **Citation checking**: Cross-reference influencer claims against our evidence database — flag when a claim isn't supported by the evidence level they imply

## Research Questions

- How well does LLM-based evidence classification agree with expert human classification? (validation study)
- Can trajectory scoring predict which interventions will advance to the next evidence level? (prospective test)
- What's the correlation between our hype ratio and supplement market sales data?
- Can we detect citation networks that inflate apparent evidence strength? (citation ring detection)
