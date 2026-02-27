# FUTURE_WORK.md — Stretch Goals & Post-Hackathon Roadmap

## Stretch Goals (If Time Permits During Hackathon)

### S1. Hype-to-Evidence Ratio Module
- Ingest news articles and social media mentions (Reddit r/longevity, Google Trends)
- Compute sentiment + volume over time
- Cross-reference against evidence grade to produce a "Bull/Bear Index"
- Visual: hype curve overlaid on evidence accumulation timeline
- **Why it matters:** Immediately identifies overmarketed interventions with weak evidence

### S2. MedGemma Deep Analysis
- Deploy MedGemma on Lyceum GPU
- Use for: endpoint relevance scoring (is "grip strength" a meaningful aging endpoint?), mechanism plausibility assessment, cross-study contradiction detection
- Falls back to Gemini API if MedGemma unavailable
- **Why it matters:** Shows off the medical reasoning capability that Gemini alone can't match

### S3. Intervention Comparison Mode
- `GET /compare?interventions=rapamycin,metformin,NMN`
- Side-by-side evidence profiles, trajectory overlays, gap comparison
- Radar chart visualisation across evidence levels
- **Why it matters:** This is the killer feature for VC due diligence — comparing pipeline candidates

### S4. Contradiction & Fragility Detection
- Within each evidence level, assess whether studies agree or conflict
- Use LLM to compare key findings pairwise
- Output a "consensus fragility score" — high when studies disagree
- Flag if all positive results come from <3 independent labs
- **Why it matters:** 10 conflicting studies ≠ 10 confirming studies, but naive counting misses this

### S5. Patent & Funding Signal
- Scrape Google Patents API for aging-related patents by intervention
- Cross-reference with NIH Reporter for funded grants
- Commercial interest + funding momentum as additional trajectory signals
- **Why it matters:** Patent filings and grant awards are leading indicators of translational potential

### S6. MCP Server — ChatGPT & Claude Connector
- Build a single MCP (Model Context Protocol) server that exposes all LongevityLens tools
- One server, all tools — ChatGPT and Claude both connect to the same endpoint
- Architecture:
  ```
  Single MCP Server (longevity-lens) at /sse
  ├── Tool: list_interventions
  ├── Tool: get_intervention_stats
  ├── Tool: get_evidence_grade
  ├── Tool: get_evidence_trajectory
  ├── Tool: get_evidence_gaps
  ├── Tool: get_hype_ratio
  ├── Tool: get_full_report
  └── Tool: search_documents
      └── All tools share the same StorageManager (JSON + SQLite)
  ```
- Implementation: Use `mcp[server]` Python package with SSE transport, mount on existing FastAPI app or standalone Starlette app
- Tools are thin wrappers around the same reasoning functions the REST API calls — no duplication of logic
- Deployment for demo: `ngrok http 8001` gives a public URL, or deploy to Lyceum VM
- **ChatGPT connection**: Settings → Apps & Connectors → Developer Mode → Create connector with MCP Server URL
- **Claude connection**: Native MCP support — just add the server URL in settings
- **Why it matters:** "Let me show you this working live inside ChatGPT right now" is a showstopper demo moment. It proves the system isn't just a standalone app — it's an infrastructure layer any LLM can plug into. Similar to how Gosset.ai exposes drug pipeline data via MCP, LongevityLens exposes evidence grading as a service.
- **Build in last 2-3 hours only if reasoning modules and Streamlit demo are solid.** The MCP layer is ~2 hours of work (the tools already exist as functions, you're just wrapping them in the MCP protocol).

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

### Future: SQLite Query Layer
If cross-intervention queries become necessary (e.g. "which intervention has the most Phase 3 trials?", "rank all interventions by evidence volume"), SQLite already mirrors the JSON with indexes on `intervention`, `source_type`, `date_published`, and `evidence_level`. A future `query_across_interventions(...)` tool could use SQL for aggregations that don't make sense at the single-file level. This avoids loading every intervention's JSON file to answer one question.

Not needed now — agents currently operate on one intervention at a time.

---

## Technical Debt to Address

- [ ] Move from synchronous to fully async ingest pipeline
- [ ] Add proper retry logic with exponential backoff for all external APIs
- [x] Implement document deduplication (same study appearing in PubMed + Europe PMC — dedup by DOI/PMID)
- [ ] Add embedding model versioning (re-embed when model changes)
- [ ] Proper database migrations (Alembic for SQLite→Postgres transition)
- [ ] Comprehensive test suite with fixtures for each source API
- [ ] Rate limit monitoring and alerting (Semantic Scholar rate limiting is a known issue)
- [ ] LLM response caching with TTL to reduce API costs
- [ ] Consolidate document schemas — 11 subclasses may be more than needed long-term
- [ ] Add data freshness tracking — flag when an intervention's data is stale and needs re-ingestion

## Research Questions

- How well does LLM-based evidence classification agree with expert human classification? (validation study)
- Can trajectory scoring predict which interventions will advance to the next evidence level? (prospective test)
- What's the correlation between our hype ratio and supplement market sales data?
- Can we detect citation networks that inflate apparent evidence strength? (citation ring detection)
