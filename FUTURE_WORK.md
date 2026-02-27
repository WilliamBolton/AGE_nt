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

---

## Post-Hackathon Roadmap

### Phase 1: Production Data Layer (Weeks 1-4)

#### Full-Text Ingestion
- Currently limited to titles + abstracts from PubMed
- Add Unpaywall API integration for open-access full texts
- Semantic chunking of full papers for more granular evidence extraction
- Extract specific data: effect sizes, confidence intervals, p-values, dosing protocols

#### Expanded Source Coverage
- **Preprint servers**: bioRxiv, medRxiv (API available)
- **Regulatory**: FDA approvals, EMA opinions
- **Conference abstracts**: Scrape from aging conference proceedings
- **GenAge/DrugAge databases**: Integrate genomics.senescence.info data
- **ITP results**: Structured data from NIA Interventions Testing Program

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

#### Regulatory Intelligence
- Track FDA/EMA pipeline for aging-adjacent indications
- Map clinical trial failures and their implications for the evidence base
- Predict which interventions are most likely to reach Phase 3 based on trajectory patterns

---

## Technical Debt to Address

- [ ] Move from synchronous to fully async ingest pipeline
- [ ] Add proper retry logic with exponential backoff for all external APIs
- [ ] Implement document deduplication (same study appearing in PubMed + preprint)
- [ ] Add embedding model versioning (re-embed when model changes)
- [ ] Proper database migrations (Alembic for SQLite→Postgres transition)
- [ ] Comprehensive test suite with fixtures for each source API
- [ ] Rate limit monitoring and alerting
- [ ] LLM response caching with TTL to reduce API costs

## Research Questions

- How well does LLM-based evidence classification agree with expert human classification? (validation study)
- Can trajectory scoring predict which interventions will advance to the next evidence level? (prospective test)
- What's the correlation between our hype ratio and supplement market sales data?
- Can we detect citation networks that inflate apparent evidence strength? (citation ring detection)
