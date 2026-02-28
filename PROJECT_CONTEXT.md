# Project context — center future developments here

**Project:** LongevityLens / Agentic AI DeepMind — Evidence grading for aging interventions.

## Goal

Build an **agentic system** that, given any aging-related intervention (e.g. rapamycin, NAD+ precursors, metformin), automatically:

- **Retrieves** literature and data (PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge, NIH Reporter, patents, FDA, etc.)
- **Classifies** studies by evidence level (1–6: systematic review → RCT → observational → animal → in vitro → in silico)
- **Identifies gaps** in the evidence hierarchy
- **Outputs** a **calibrated confidence score** with a **human-readable, transparent report**

## Why it matters

- Longevity biotech has a due-diligence problem; manual systematic reviews are slow and expensive.
- The system should support investors, analysts, and researchers to assess evidence strength in minutes, with reproducible reasoning.

## Tech & architecture

- **Orchestration:** LangGraph + agents (your responsibility). Pipeline: expand query → ingest → classify → evidence grade → trajectory → gaps → report.
- **LLMs:** Gemini for orchestration/planning and report generation; MedGemma (when available) for medical reasoning.
- **Data layer:** Unified document schema (Pydantic), dual storage (JSON + SQLite), ingest agents that are “fast and dumb” (no LLM at ingest); classification and reasoning on demand.
- **Evidence hierarchy:** Level 1 = highest (systematic reviews/meta-analyses), Level 6 = lowest (in silico). Confidence should reflect this.

## Example interventions to support

Rapamycin, metformin, NAD+ precursors (NMN/NR), senolytics, young plasma/parabiosis, hyperbaric oxygen, epigenetic reprogramming (Yamanaka factors).

## Where to take it next

- Replace reasoning/classification **stubs** with full `reasoning.*` and `classify.llm_classifier` when ready.
- Add more ingest sources or conditional branching in the graph (e.g. run only missing sources).
- Integrate MedGemma for deeper medical reasoning.
- Expose the pipeline via API (e.g. `POST /interventions/{name}/report`) and/or a simple frontend.
- Keep the **unified schema and data layer** as the core; treat reasoning modules as swappable consumers.

---

*Use this file as the north star for future developments in this repo.*
