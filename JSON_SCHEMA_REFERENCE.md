# JSON Schema Reference — LongevityLens Data Layer

> **Purpose:** This document is a machine-readable reference for LLM agents and automated systems that need to search, extract, and reason over LongevityLens JSON data. Every field, type, enum value, and nesting structure is documented below.

---

## File Map

```
data/
├── longevity_lens.db                   # SQLite (mirrors JSON, supports structured queries)
├── documents/
│   └── {intervention}.json             # All ingested documents for one intervention
├── trends/
│   └── {intervention}.json             # Google Trends time-series data
├── query_cache/
│   └── {intervention}.json             # Cached LLM-expanded search queries
├── interventions.json                  # Config file — list of interventions to track (not data)
├── anage/                              # External AnAge database files
└── drugage/                            # External DrugAge database files
```

> **Note:** `interventions.json` is a config file for ingest scripts, not a data store. It lists interventions we *intend* to scrape — not what has actually been ingested. To see what data exists, check `data/documents/`.

---

## 1. Document Store (Primary Data)

**Path:** `data/documents/{intervention}.json`

This is the core data file. One file per intervention, containing all ingested documents from every source.

### Envelope Structure

```json
{
  "intervention": "rapamycin",                     // string — matches filename
  "aliases": ["sirolimus", "rapamune"],            // string[]
  "last_updated": "2026-02-27",                    // date string (YYYY-MM-DD)
  "document_count": 312,                           // int — total docs in this file
  "documents": [ ... ]                             // Document[] — array of document objects
}
```

### Shared Fields (All Document Types)

Every document in the `documents` array has these fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | UUID (unique identifier) |
| `source_type` | `string` | **Discriminator.** Determines which extra fields are present. See enum below. |
| `intervention` | `string` | Canonical lowercase name |
| `intervention_aliases` | `string[]` | Alternative names |
| `title` | `string` | Document title |
| `abstract` | `string` | Abstract or description text |
| `source_url` | `string` | Original URL |
| `date_published` | `string` | Publication date (`YYYY-MM-DD`) |
| `date_indexed` | `string` | Ingest date (`YYYY-MM-DD`) |

### `source_type` Enum Values

The `source_type` field determines which additional fields a document carries:

| Value | Description | Extra Fields Section |
|-------|-------------|---------------------|
| `"pubmed"` | PubMed articles | [PubMed fields](#pubmed-fields) |
| `"clinicaltrials"` | ClinicalTrials.gov studies | [Clinical Trial fields](#clinical-trial-fields) |
| `"preprint"` | bioRxiv / medRxiv preprints | [Preprint fields](#preprint-fields) |
| `"news"` | News/media articles | [News fields](#news-fields) |
| `"social"` | Reddit, Twitter, etc. | [Social fields](#social-fields) |
| `"europe_pmc"` | Europe PMC articles | [Europe PMC fields](#europe-pmc-fields) |
| `"semantic_scholar"` | Semantic Scholar papers | [Semantic Scholar fields](#semantic-scholar-fields) |
| `"drugage"` | DrugAge database entries | [DrugAge fields](#drugage-fields) |
| `"nih_grant"` | NIH grant records | [Grant fields](#grant-fields) |
| `"patent"` | Patent filings | [Patent fields](#patent-fields) |
| `"regulatory"` | FDA/regulatory documents | [Regulatory fields](#regulatory-fields) |
| `"google_trends"` | *(Not stored as document — see Trends section)* | — |

---

### PubMed Fields

Documents where `source_type == "pubmed"`:

| Field | Type | Description |
|-------|------|-------------|
| `pmid` | `string` | PubMed ID |
| `doi` | `string \| null` | Digital Object Identifier |
| `authors` | `string[]` | Author names |
| `journal` | `string \| null` | Journal name |
| `impact_factor` | `float \| null` | Journal impact factor |
| `mesh_terms` | `string[]` | MeSH descriptor terms |
| `publication_types` | `string[]` | e.g. `["Journal Article", "Systematic Review"]` |
| `peer_reviewed` | `bool` | Always `true` for PubMed |

**Example query pattern:** To find all PubMed systematic reviews for rapamycin, filter for `source_type == "pubmed"` and check if `publication_types` contains `"Systematic Review"`.

---

### Clinical Trial Fields

Documents where `source_type == "clinicaltrials"`:

| Field | Type | Description |
|-------|------|-------------|
| `nct_id` | `string` | ClinicalTrials.gov NCT identifier |
| `phase` | `string \| null` | Trial phase (e.g. `"Phase 2"`, `"Phase 3"`) |
| `status` | `string \| null` | e.g. `"Completed"`, `"Recruiting"`, `"Terminated"` |
| `enrollment` | `int \| null` | Number of participants |
| `sponsor` | `string \| null` | Sponsoring organization |
| `conditions` | `string[]` | Medical conditions studied |
| `primary_outcomes` | `string[]` | Primary outcome measures |
| `results_summary` | `string \| null` | Results text if available |
| `date_registered` | `string \| null` | Registration date (`YYYY-MM-DD`) |
| `date_started` | `string \| null` | Study start date |
| `date_completed` | `string \| null` | Study completion date |
| `date_results_posted` | `string \| null` | Results posted date |

**Example query pattern:** To find completed Phase 3 human trials, filter `source_type == "clinicaltrials"`, `phase` contains `"3"`, `status == "Completed"`.

---

### Preprint Fields

Documents where `source_type == "preprint"`:

| Field | Type | Description |
|-------|------|-------------|
| `doi` | `string \| null` | DOI |
| `server` | `string` | `"biorxiv"` or `"medrxiv"` |
| `authors` | `string[]` | Author names |
| `peer_reviewed` | `bool` | Always `false` (preprints) |
| `date_peer_published` | `string \| null` | Date if later peer-reviewed |

---

### News Fields

Documents where `source_type == "news"`:

| Field | Type | Description |
|-------|------|-------------|
| `outlet` | `string` | News outlet name |
| `author` | `string \| null` | Article author |
| `sentiment` | `float \| null` | Sentiment score: `-1.0` (negative) to `1.0` (positive) |
| `reach_estimate` | `int \| null` | Estimated audience reach |
| `claims_strength` | `string \| null` | One of: `"breakthrough"`, `"promising"`, `"incremental"`, `"negative"` |
| `cites_primary_source` | `bool` | Whether article cites primary research |
| `primary_source_doi` | `string \| null` | DOI of cited research |

---

### Social Fields

Documents where `source_type == "social"`:

| Field | Type | Description |
|-------|------|-------------|
| `platform` | `string` | `"reddit"`, `"twitter"`, etc. |
| `subreddit` | `string \| null` | Subreddit name (Reddit only) |
| `score` | `int \| null` | Upvotes / likes |
| `comment_count` | `int \| null` | Number of comments |
| `sentiment` | `float \| null` | `-1.0` to `1.0` |

---

### Europe PMC Fields

Documents where `source_type == "europe_pmc"`:

| Field | Type | Description |
|-------|------|-------------|
| `pmid` | `string \| null` | PubMed ID |
| `pmcid` | `string \| null` | PubMed Central ID |
| `doi` | `string \| null` | DOI |
| `authors` | `string[]` | Author names |
| `journal` | `string \| null` | Journal name |
| `cited_by_count` | `int \| null` | Citation count from Europe PMC |
| `is_open_access` | `bool` | Open access flag |
| `peer_reviewed` | `bool` | Default `true` |
| `is_preprint` | `bool` | Whether this is a preprint |
| `is_cochrane` | `bool` | Whether from Cochrane Library |
| `preprint_server` | `string \| null` | `"bioRxiv"`, `"medRxiv"` if preprint |
| `publication_types` | `string[]` | Publication type labels |
| `mesh_terms` | `string[]` | MeSH terms |

---

### Semantic Scholar Fields

Documents where `source_type == "semantic_scholar"`:

| Field | Type | Description |
|-------|------|-------------|
| `paper_id` | `string` | Semantic Scholar paper ID |
| `doi` | `string \| null` | DOI |
| `authors` | `string[]` | Author names |
| `journal` | `string \| null` | Journal/venue name |
| `year` | `int \| null` | Publication year |
| `citation_count` | `int \| null` | Total citations |
| `influential_citation_count` | `int \| null` | Highly-influential citations |
| `tldr` | `string \| null` | Auto-generated one-sentence summary |
| `publication_types` | `string[]` | Publication type labels |
| `is_open_access` | `bool` | Open access flag |

---

### DrugAge Fields

Documents where `source_type == "drugage"`:

| Field | Type | Description |
|-------|------|-------------|
| `species` | `string` | Organism species (e.g. `"Mus musculus"`) |
| `strain` | `string \| null` | Organism strain |
| `dosage` | `string \| null` | Dosage amount |
| `dosage_unit` | `string \| null` | Dosage unit (e.g. `"mg/kg"`) |
| `administration_route` | `string \| null` | Route (e.g. `"oral"`, `"injection"`) |
| `lifespan_change_percent` | `float \| null` | Lifespan change as percentage (e.g. `15.0` = 15% extension, `-5.0` = 5% decrease) |
| `significance` | `string \| null` | `"significant"` or `"not significant"` |
| `reference_pmid` | `string \| null` | PubMed ID of source study |
| `gender` | `string \| null` | `"male"`, `"female"`, `"both"`, `"mixed"` |

**Example query pattern:** To find all significant lifespan extensions in mice, filter `source_type == "drugage"`, `species` contains `"musculus"`, `significance == "significant"`, `lifespan_change_percent > 0`.

---

### Grant Fields

Documents where `source_type == "nih_grant"`:

| Field | Type | Description |
|-------|------|-------------|
| `project_number` | `string` | NIH project number |
| `pi_name` | `string \| null` | Principal investigator |
| `organisation` | `string \| null` | Institution name |
| `total_funding` | `float \| null` | Total funding amount (USD) |
| `fiscal_year` | `int \| null` | Fiscal year |
| `grant_start` | `string \| null` | Grant start date |
| `grant_end` | `string \| null` | Grant end date |
| `funding_mechanism` | `string \| null` | e.g. `"R01"`, `"R21"`, `"U01"` |
| `nih_institute` | `string \| null` | e.g. `"NIA"`, `"NCI"` |

---

### Patent Fields

Documents where `source_type == "patent"`:

| Field | Type | Description |
|-------|------|-------------|
| `patent_id` | `string` | Patent identifier |
| `assignee` | `string \| null` | Patent assignee (company/person) |
| `inventors` | `string[]` | Inventor names |
| `filing_date` | `string \| null` | Filing date (`YYYY-MM-DD`) |
| `grant_date` | `string \| null` | Grant date |
| `patent_status` | `string \| null` | `"granted"`, `"pending"`, `"expired"` |
| `patent_office` | `string \| null` | `"USPTO"`, `"EPO"`, `"WIPO"` |
| `claims_count` | `int \| null` | Number of claims |

---

### Regulatory Fields

Documents where `source_type == "regulatory"`:

| Field | Type | Description |
|-------|------|-------------|
| `approved_indications` | `string[]` | Approved medical indications |
| `approval_date` | `string \| null` | Approval date (`YYYY-MM-DD`) |
| `drug_class` | `string \| null` | Drug classification |
| `warnings_summary` | `string \| null` | Safety warnings text |
| `pharmacokinetics_summary` | `string \| null` | PK summary text |
| `nda_number` | `string \| null` | FDA NDA/BLA application number |

---

## 2. Enums Reference

These enums are used across the schema by the Pydantic models and reasoning modules.

### `evidence_level` (Integer)

| Value | Label | Description |
|-------|-------|-------------|
| `1` | SYSTEMATIC_REVIEW | Systematic reviews and meta-analyses |
| `2` | RCT | Randomised controlled trials |
| `3` | OBSERVATIONAL | Observational / epidemiological studies |
| `4` | ANIMAL | Animal model studies (in vivo) |
| `5` | IN_VITRO | Cell culture / in vitro experiments |
| `6` | IN_SILICO | Computational predictions |

### `effect_direction` (String)

| Value | Description |
|-------|-------------|
| `"positive"` | Beneficial effect on longevity/aging |
| `"negative"` | Harmful effect |
| `"null"` | No significant effect |
| `"mixed"` | Mixed or context-dependent results |

### `hallmarks_addressed` (String)

The 12 hallmarks of aging:

| Value | Hallmark |
|-------|----------|
| `"genomic_instability"` | Genomic instability |
| `"telomere_attrition"` | Telomere attrition |
| `"epigenetic_alterations"` | Epigenetic alterations |
| `"loss_of_proteostasis"` | Loss of proteostasis |
| `"disabled_macroautophagy"` | Disabled macroautophagy |
| `"deregulated_nutrient_sensing"` | Deregulated nutrient sensing |
| `"mitochondrial_dysfunction"` | Mitochondrial dysfunction |
| `"cellular_senescence"` | Cellular senescence |
| `"stem_cell_exhaustion"` | Stem cell exhaustion |
| `"altered_intercellular_communication"` | Altered intercellular communication |
| `"chronic_inflammation"` | Chronic inflammation |
| `"dysbiosis"` | Dysbiosis |

> **Note:** These enum fields are not yet present in the document JSON files. They will be populated by LLM classification when reasoning modules are built. For now, documents only contain the raw ingested fields.

---

## 3. Google Trends Data

**Path:** `data/trends/{intervention}.json`

This is NOT a document — it uses a separate structure for time-series interest data.

```json
{
  "intervention": "rapamycin",                     // string
  "fetched_at": "2026-02-27T20:28:06.087046",     // ISO datetime
  "timeframe": "today 5-y",                        // string — Google Trends timeframe parameter
  "data_points": [                                  // object[] — weekly interest data
    {
      "date": "2021-02-21",                         // string (YYYY-MM-DD)
      "interest": 11                                // int (0-100, relative to peak)
    }
  ],
  "related_queries": [                              // string[] — top related search queries
    "rapamycin aging",
    "rapamycin mtor"
  ],
  "peak_interest": 100,                             // int — max interest value in period
  "peak_date": "2025-08-10",                        // string (YYYY-MM-DD)
  "current_interest": 57                            // int — most recent data point value
}
```

---

## 4. Query Expansion Cache

**Path:** `data/query_cache/{intervention}.json`

LLM-generated search term expansions, cached to avoid repeated API calls.

```json
{
  "primary_name": "rapamycin",                      // string
  "synonyms": ["sirolimus", "rapamune"],            // string[]
  "analogs": ["everolimus", "temsirolimus"],        // string[] — related compounds
  "mechanism_terms": [                              // string[] — biological mechanism keywords
    "mTOR pathway",
    "mechanistic target of rapamycin",
    "autophagy modulation"
  ],
  "mesh_terms": [                                   // string[] — MeSH terms for PubMed queries
    "Sirolimus[MeSH Terms]",
    "mTOR Inhibitors[MeSH Terms]"
  ],
  "queries": {                                      // dict — source-optimized query strings
    "pubmed": "rapamycin[MeSH Terms] OR sirolimus[MeSH Terms] AND ...",
    "clinical_trials": "rapamycin OR sirolimus OR rapamune",
    "general": "research on rapamycin and its effects on aging and longevity",
    "preprint": "rapamycin OR sirolimus in the context of aging and longevity"
  }
}
```

---

## 5. How to Navigate the Data

### Get all documents for an intervention
Open `data/documents/{intervention}.json`. The `documents` array contains every ingested document.

### Filter by source type
Each document has a `source_type` field. To get only PubMed papers, iterate `documents` and keep entries where `source_type == "pubmed"`.

### Find PubMed articles by MeSH term
Filter for `source_type == "pubmed"`, then check if the `mesh_terms` array contains the term you want (e.g. `"Aging"`).

### Find clinical trials by phase and status
Filter for `source_type == "clinicaltrials"`, then check `phase` (e.g. `"Phase 3"`) and `status` (e.g. `"Completed"`).

### Find significant lifespan extensions in animal models
Filter for `source_type == "drugage"`, then check `significance == "significant"` and `lifespan_change_percent > 0`. Use `species` to narrow to a specific organism.

### Count publications over time
Collect `date_published` from all documents (or a filtered subset), group by year, and count.

### Compare hype vs evidence
- **Evidence volume:** count documents where `source_type` is `"pubmed"`, `"clinicaltrials"`, or `"europe_pmc"`
- **Media hype:** filter for `source_type == "news"` and look at `sentiment` and `claims_strength`
- **Public interest:** load `data/trends/{intervention}.json` and read `data_points` for the interest timeline

---

## 6. Field Availability by Source Type (Quick Reference)

| Field | pubmed | clinicaltrials | preprint | news | social | europe_pmc | semantic_scholar | drugage | nih_grant | patent | regulatory |
|-------|--------|---------------|----------|------|--------|------------|-----------------|---------|-----------|--------|------------|
| `pmid` | Y | - | - | - | - | Y | - | - | - | - | - |
| `doi` | Y | - | Y | - | - | Y | Y | - | - | - | - |
| `authors` | Y | - | Y | - | - | Y | Y | - | - | - | - |
| `journal` | Y | - | - | - | - | Y | Y | - | - | - | - |
| `mesh_terms` | Y | - | - | - | - | Y | - | - | - | - | - |
| `nct_id` | - | Y | - | - | - | - | - | - | - | - | - |
| `phase` | - | Y | - | - | - | - | - | - | - | - | - |
| `status` | - | Y | - | - | - | - | - | - | - | - | - |
| `enrollment` | - | Y | - | - | - | - | - | - | - | - | - |
| `sentiment` | - | - | - | Y | Y | - | - | - | - | - | - |
| `citation_count` | - | - | - | - | - | Y | Y | - | - | - | - |
| `species` | - | - | - | - | - | - | - | Y | - | - | - |
| `lifespan_change_percent` | - | - | - | - | - | - | - | Y | - | - | - |
| `total_funding` | - | - | - | - | - | - | - | - | Y | - | - |
| `patent_id` | - | - | - | - | - | - | - | - | - | Y | - |
| `approved_indications` | - | - | - | - | - | - | - | - | - | - | Y |
