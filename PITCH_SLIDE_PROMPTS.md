# Prompts for Building Pitch Slides from PITCH_REPORT.md

Use these prompts with another LLM to generate a **5-minute pitch presentation** (slides + optional speaker notes). **Prompt 1** is comprehensive and self-contained: it embeds the full evaluation criteria, project context, and pitch content so you can run it **once without** attaching PROJECT_CONTEXT.md, EVALUATION_CONTEXT.md, or PITCH_REPORT.md. The other prompts assume you attach or paste those documents as context.

---

## Evaluation criteria to satisfy (from EVALUATION_CONTEXT.md)

- **Pitch duration:** 5 minutes total.
- **Content areas:** (1) Technical overview, (2) Rationale, (3) Innovation, (4) Outlook.
- **Judging emphasis:** Judges look for **novelty**; highlight novel elements beyond the core project tasks.

---

## Prompt 1 — Master prompt (full deck, run once)

Use this as a **single, self-contained prompt** when the next LLM does not have access to PROJECT_CONTEXT.md, EVALUATION_CONTEXT.md, or PITCH_REPORT.md. **Short version** below fits smaller context windows.

---

### Prompt 1 — SHORT (for limited context window)

```
You are a pitch-deck designer for a hackathon VC track. Create a complete **5-minute pitch** slide deck. Use ONLY the information below; do not invent facts.

**EVALUATION (must satisfy):**
- 5 min total, one speaker. Cover in order: (1) Technical overview, (2) Rationale, (3) Innovation, (4) Outlook. Judges emphasise **novelty**—explicitly highlight elements beyond the core project brief in Innovation. Audience: track judges + possible VC mentor (Heal Capital). Tone: professional, evidence-based.

**PROJECT:** Track = Evidence Grading for Aging Interventions. Objective: agentic system (Gemini + MedGemma) that retrieves, classifies, synthesises ageing intervention evidence. Deliverable: given intervention name → structured evidence report + transparent confidence score. Challenge: differentiate rigorous clinical evidence from cell/animal studies; handle metformin/rapamycin to NMN/hyperbaric oxygen/epigenetic reprogramming. Evidence levels 1–6 (systematic review → RCT → observational → animal → in vitro → in silico). Why it matters: due-diligence problem; **$5.2B VC** longevity 2021–2024; **six-figure** consultant cost; manual reviews slow/outdated; need minutes not months, transparent & reproducible.

**KEY FACTS FOR SLIDES (use these exact numbers/names):**
- One-liner: Agentic system → any ageing intervention → evidence report with confidence score, gap analysis, social-hype context, limitations → PDF; path to API/SaaS.
- Problem: Due-diligence problem; $5.2B VC; evidence assessment manual, slow, expensive; six-figure consultant cost; inconsistent standards, hype risk.
- Solution: 11 sources, evidence levels 1–6, gap analysis with "how to close", Reddit + Google Trends hype score, **Judge** agent (critique-only), **50+ interventions** + aliases → one query, one PDF, minutes.
- Pipeline (6 steps): Retriever → [Researcher Classifier | Gap Analyst | Social Media Expert] (parallel) → Judge → Reporter → PDF. LangGraph; Gemini + optional MedGemma; unified schema; JSON + SQLite; 11 sources (PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge, NIH Reporter, Patents, FDA/DailyMed, Tavily, Reddit, Google Trends).
- Rationale: Automate due diligence; schema-first (one store, multiple use cases); multi-source; deterministic rubric = reproducible; Judge = critical self-check, trust for VCs.
- Novelty (stress these): Judge agent (not in brief); social hype vs evidence in one report; end-to-end PDF; deterministic + optional LLM; 50+ interventions + aliases; rubric-driven auditable; single query → full report; unified data layer.
- Market: $5.2B VC; primary = VCs/family offices, secondary = pharma BD, tertiary = research/regulators. Vs consultants (slow/expensive) vs generic AI (no hierarchy/gap/hype in one report). Differentiation: evidence intelligence, not generic search.
- Outlook: Positioning = "Evidence intelligence for longevity." Revenue: SaaS/API, custom rubrics, white-label. Roadmap: short = API, web UI, on-demand ingest; medium = more sources, verticals, enterprise; long = regulatory/academic, beyond ageing, data products. **Ask:** support for production API + first paying pilots (compute, advisory, intros to longevity funds and pharma innovation). Vision: fast, transparent, reproducible evidence → capital to strongest evidence not loudest hype.

**TASK:** Produce 8–12 slides (title + problem, then Technical → Rationale → Innovation → Outlook, then thank-you/ask). Per slide: number, title, 3–5 bullets (use exact facts above), optional speaker note, optional [Visual: ...]. Call out novelty in Innovation. Professional, VC-ready. No content beyond the facts above.
```

---

### Prompt 1 — LONG (full context; use when window allows)

Use when your context window can fit the full prompt. All required evaluation criteria, project context, and pitch content are embedded so the model can produce the full deck in one run for best performance.

```
You are a pitch-deck designer for a hackathon VC track. Create a complete slide deck for a **5-minute pitch**. The following sections contain the full evaluation criteria, project context, and pitch content. Use only this information; do not invent facts.

---

### PART A — EVALUATION CRITERIA (you must satisfy these)

- **Format:** 5-minute pitch total; ideally one speaker per team. The same scoring criteria apply for track evaluations and the final public pitches.
- **Required content areas, in this order:**
  1. **Technical overview** — A clear breakdown of the solution.
  2. **Rationale** — The "why" behind the specific approach.
  3. **Innovation** — What makes the solution unique or groundbreaking?
  4. **Outlook** — If you had more time, how would you scale this or turn it into a company?

- **Judging emphasis — novelty:** Judges specifically look for **novelty**. Adding novel elements—including work that was **not** explicitly in the project tasks—is a positive differentiator. You must explicitly highlight and call out novel elements in the Innovation section.

- **Audience:** Track judges and possibly a VC mentor (e.g. from Heal Capital) for pitch feedback. Tone: professional, concise, evidence-based, suitable for VCs and biotech.

---

### PART B — PROJECT & CHALLENGE CONTEXT

- **Track / challenge:** Agentic AI (e.g. DeepMind track) — **Evidence Grading for Aging Interventions.**

- **Official objective:** Build an agentic system using the Gemini API (orchestration and planning) and MedGemma (medical reasoning) that retrieves, classifies, and synthesises scientific information on ageing interventions.

- **Official deliverable:** A working demo: given an intervention name (e.g. "rapamycin," "NAD+ precursors"), the agent must return a **structured evidence report with a transparent confidence score**.

- **Challenge goal:** Ageing research is growing fast; billions flow into longevity startups; supplements and social media amplify preliminary findings. It is hard even for scientists to differentiate interventions backed by rigorous clinical evidence from those supported only by cell culture or animal studies. The agent must: given any ageing-related intervention, automatically retrieve literature (and optionally other databases), classify studies by evidence level, identify gaps in the evidence hierarchy, and output a calibrated confidence score with a human-readable report. It should handle interventions from well-studied compounds (metformin, rapamycin) to emerging claims (NMN, hyperbaric oxygen, epigenetic reprogramming).

- **Why this matters:** The longevity sector has a due-diligence problem. Over **$5.2B in venture capital** flowed into longevity biotech between 2021 and 2024 (e.g. Altos Labs ~$3B, NewLimit, Retro Biosciences). Investors, pharma, and companies struggle to objectively assess evidence strength. Today assessment is manual: systematic reviews are expensive, take months, and are outdated by publication. VCs and biotech analysts routinely pay **six figures** for consultant-led due diligence that still boils down to experts reading papers. An automated evidence-grading agent could compress this into **minutes** and make reasoning **transparent and reproducible**.

- **Evidence hierarchy (standard):**
  - Level 1: Systematic reviews & meta-analyses (highest weight).
  - Level 2: Randomised controlled trials (RCTs).
  - Level 3: Observational / epidemiological studies.
  - Level 4: Animal model studies (in vivo).
  - Level 5: Cell culture / in vitro studies.
  - Level 6: In silico / computational predictions (lowest weight).
  A compound with only Level 5–6 evidence should get a very different confidence score than one with Level 1–2 evidence.

- **Example interventions:** Rapamycin/mTOR inhibitors, Metformin (TAME trial), NAD+ precursors (NMN/NR), Senolytics (e.g. dasatinib + quercetin), Young plasma/parabiosis, Hyperbaric oxygen therapy, Epigenetic reprogramming (Yamanaka factors). Data sources include PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge, NIH Reporter, Patents, FDA/DailyMed, Tavily (news), Reddit, Google Trends (11 sources in total in the built system).

---

### PART C — PITCH CONTENT (use this as the single source of truth for slide copy)

**One-liner:** An agentic system that turns any ageing intervention name into a structured evidence report with a transparent confidence score, gap analysis, social-hype context, and critical limitations—delivered as a PDF, with a path to API and SaaS.

**Problem:** Longevity biotech has a due-diligence problem: billions in capital, but evidence assessment is manual, slow, and expensive. Systematic reviews cost hundreds of thousands and take months; they are often outdated by publication. VCs and analysts pay six-figure sums for consultant-led due diligence that still boils down to experts reading papers. Consequences: inconsistent standards, slow turnaround, difficulty comparing interventions objectively, and risk of hype (social media, press) influencing decisions without a clear evidence baseline.

**Solution:** Automated, multi-source evidence grading + gap analysis + hype scoring + a critical **Judge** agent → one query, one report, in minutes. The system retrieves and normalises evidence from **11 sources**, classifies studies by evidence level (1–6), identifies gaps with "how to close" recommendations, scores social hype (Reddit, Google Trends) alongside evidence, and outputs a calibrated confidence score and a human-readable report (PDF or HTML) including a critical assessment of limitations. **50+ interventions** with alias resolution so queries like "rapamycin for longevity" map correctly.

**Technical (architecture):**
- **Orchestration:** LangGraph — explicit state machine, parallel execution where possible.
- **Six-step pipeline:** (1) **Retriever** — parses query, resolves to canonical intervention from 50+ interventions/aliases, validates corpus exists. (2) **Researcher Classifier** — evidence grader (MedGemma when available) over corpus: confidence rubric, tier contributions, gating penalties (human evidence, RCT, endpoints, safety), outputs confidence score. (3) **Gap Analyst** — deterministic gap analysis: human evidence, RCTs, endpoints, replication, older-adult populations, safety, trial duration, results posting, animal evidence; each gap has status and "how to close" text. (4) **Social Media Expert** — Reddit + Google Trends → 0–100 hype score and summary. (5) **Judge** — evaluation agent that **only** criticises the other agents’ outputs: limitations, inconsistencies (e.g. high confidence but large gaps), hype–evidence mismatch, data-quality caveats; no positive spin. (6) **Reporter** — assembles report (executive summary, limitations from Judge, recommendations, closing) and exports **structured PDF** (or HTML). Classifier, Gap Analyst, and Social run **in parallel** after Retriever; Judge and Reporter run sequentially after them.
- **LLMs:** Gemini for orchestration and narrative; MedGemma (optional, GPU) for medical reasoning. Deterministic rubric scoring remains source of truth; LLMs augment retrieval and text.
- **Data:** Unified Pydantic document schema; dual storage (JSON + SQLite). Ingest agents are "fast and dumb" (no LLM at ingest). **11 ingest sources:** PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge, NIH Reporter, Patents, FDA/DailyMed, Tavily, Reddit, Google Trends.
- **Tech stack:** Python 3.11+, Pydantic v2, LangGraph, Gemini API, optional MedGemma, ReportLab for PDF; FastAPI/Streamlit in structure; current demo is CLI and programmatic pipeline.

**Market:** Over **$5.2B VC** into longevity biotech (2021–2024). Primary: VCs and family offices (pipeline screening, deal memos, portfolio monitoring). Secondary: pharma/biotech BD and R&D (external assets, competitive landscape, evidence strength). Tertiary: research institutions, foundations, regulators. TAM: all organisations that commission or perform evidence synthesis in ageing/longevity. SAM: VCs and corporates with longevity focus and budget for data/tools. SOM: early adopters = longevity-focused funds, pharma innovation arms, research consortia. **Competition:** Incumbents = consulting and manual systematic-review providers (high-touch, slow, expensive). Emerging = generic AI search/summarisation (e.g. ChatGPT, Perplexity, Elicit) — they do not provide structured evidence hierarchy, reproducible scoring, gap analysis, or hype–evidence comparison in one auditable report. **Differentiation:** Multi-source ingest + rubric-driven confidence + deterministic gap analysis + social-hype scoring + critical Judge in one pipeline; unified schema; "evidence intelligence" not generic search.

**Rationale (why this approach):**
- Automating due diligence: report in minutes with explicit reasoning and limitations.
- Schema-first, reason later: unified document schema and ingest pipeline as backbone; all reasoning modules consume the same store; adding/swapping modules (rubrics, models) does not require re-ingesting; multiple use cases (VC, regulatory, academic) from one data layer.
- Multi-source evidence: confidence and gaps more meaningful when aggregating PubMed, ClinicalTrials.gov, Europe PMC, DrugAge, grants, patents, FDA, social/trends; 11 sources today, can add more without changing core pipeline.
- Transparent, reproducible confidence: deterministic rubric (tier weights, gating penalties); optional LLM augments retrieval and narrative but does not replace the arithmetic (audit/compliance).
- Critical self-check: Judge agent outputs only limitations and quality concerns; report always surfaces caveats and hype–evidence mismatch; reduces overclaim risk, builds trust with VCs and pharma.
- Why LangGraph: clear separation of steps and shared state; parallel execution for analysts; extensible (new nodes plug in without rewriting the flow).

**Innovation and novelty (judges look for this — emphasise explicitly):**
- **Dedicated Judge agent:** Only criticises other agents’ outputs; no positive spin. Deliberate product choice for calibration and trust (risk-aware users like VCs). *Novel: not in core project brief.*
- **Social hype vs evidence in one report:** Reddit + Google Trends in same pipeline (Social Media Expert) → Judge and final report. Users see "what the evidence says" vs "what social/media interest suggests." Addresses amplified preliminary findings. *Novel.*
- **End-to-end PDF report:** Single, structured PDF (executive summary, limitations, recommendations, closing); shareable with co-investors, boards, partners — not just JSON/console. *Novel.*
- **Deterministic + optional LLM:** Can run deterministic-only (reproducible, no GPU); MedGemma improves retrieval/narrative when available while core scores stay rubric-based; cost control and quality. *Novel.*
- **50+ interventions with aliases:** Curated list + name/alias resolution; natural queries resolve correctly; scales to hundreds and custom taxonomies. *Beyond minimum.*
- **Rubric-driven, auditable grading:** Versionable rubrics (e.g. VC vs FDA vs academic) without code changes. *Novel.*
- **Single query → full report:** One input → resolution, evidence score, gap analysis, social hype, limitations, PDF. No multi-step wizard.
- **Unified data layer:** One schema, one storage; ingest, evidence grading, gap analysis, social/hype all use same store; new sources or modules do not require a new data pipeline.
- **Reproducibility:** Same corpus + rubrics = same numbers; optional LLM only enriches retrieval and text (important for diligence and audit).

**Production readiness:** Core six-step pipeline is implemented, tested, runnable via CLI and programmatic API. Deterministic scoring can run without GPU/LLM. PDF (and HTML fallback) with consistent layout. Unified schema and dual storage in place; config via env and config (no hardcoded secrets). **Next for production at scale:** API (e.g. FastAPI POST /report), on-demand ingest, containerise (Docker), monitoring/observability, security/compliance as needed.

**Business & outlook:**
- **Positioning:** "Evidence intelligence for longevity and ageing interventions" — automated, transparent evidence grading and gap reports for investors, pharma, biotech; minutes not months; reasoning and limitations explicit.
- **Revenue potential:** SaaS/API (usage or subscription per report); custom rubrics and integrations for funds/pharma/regulators; white-label and data licensing; optional professional services (training, custom corpus, audit).
- **Go-to-market:** Early adopters = longevity-focused VCs, pharma BD, research consortia; pilot/free tier for case studies; direct outreach, partnerships with accelerators/associations, content for authority.
- **Roadmap:** Short term (0–6 months): API, web UI, on-demand ingest, more modules (trajectory, comparison). Medium (6–18 months): more sources, verticals, enterprise (SSO, audit logs, custom branding). Long term (18+): regulatory/academic variants, expansion beyond ageing (e.g. oncology, rare disease), data products for longevity market.
- **Ask:** Support to reach production API and first paying pilots — e.g. compute, advisory, introductions to longevity funds and pharma innovation units.

**Vision:** Make evidence assessment for longevity interventions **fast, transparent, and reproducible** — so capital and partnerships flow to the strongest evidence, not the loudest hype. Goal: become the default evidence layer for VCs, pharma, and researchers evaluating ageing-related interventions.

---

### PART D — YOUR TASK

Create the **full slide deck** for the 5-minute pitch using only the information in Parts A–C.

**Constraints:**
- Total: **8–12 slides** (including title and thank-you). Assume ~1 minute per 1–2 slides to fit 5 minutes.
- **Strict order:** Cover the four required areas in order — (1) Technical overview, (2) Rationale, (3) Innovation, (4) Outlook — with opening (title/problem) and closing (thank-you/ask) as needed.
- **Novelty:** In the Innovation section, explicitly state that these elements go beyond the core project brief where applicable (Judge agent, social hype in report, PDF, 50+ interventions, rubrics, deterministic+LLM).

**Output format for each slide:**
- **Slide number and title**
- **3–5 bullet points** (short, scannable; use exact numbers and names from Part C where relevant, e.g. $5.2B, 11 sources, 50+ interventions, six-step pipeline, Judge agent)
- **Speaker note (optional):** 1–2 sentences for the presenter
- Where a simple visual would help, add a line in square brackets, e.g. [Visual: pipeline diagram — Query → Retriever → (Classifier | Gap | Social) → Judge → Reporter → PDF]

**Deliverable:** A numbered list of all slides with title, bullets, optional speaker note, and optional [Visual] hint. Do not add slides that contradict or go beyond the content in Part C. Use professional, VC-ready language throughout.
```

---

## Prompt 2 — Slide-by-slide structure (skeleton first)

Use this to get a suggested slide flow, then use Prompt 3 per section to fill content.

```
Using PROJECT_CONTEXT.md, EVALUATION_CONTEXT.md, and PITCH_REPORT.md, propose a **slide structure** for a 5-minute pitch that satisfies the required criteria:

1. Technical overview
2. Rationale
3. Innovation
4. Outlook

For each section, give:
- Suggested number of slides for that section.
- One proposed slide title per slide.
- One sentence describing what that slide should convey.

Total: 8–12 slides including title and closing. Ensure novelty is explicitly called out in the Innovation section.
```

---

## Prompt 3 — Section-specific prompts (fill one section at a time)

Use these after you have a skeleton, or to generate one section’s slides in detail.

### 3a. Title + Hook (slides 1–2)

```
Based on PITCH_REPORT.md, create the opening 1–2 slides for a 5-minute VC pitch:

Slide 1 — Title slide: project name (LongevityLens / AGE-nt), tagline (e.g. "Evidence intelligence for ageing interventions"), and one punchy subline (e.g. "Automated, transparent due diligence in minutes").

Slide 2 — Problem / opportunity: 3–4 bullets that set up why this matters. Use the "Executive Summary" and "Market Analysis / Due-Diligence Pain Point" from the report. Include the $5.2B longevity VC figure and the six-figure consultant cost. End with the one-sentence opportunity: automated, transparent evidence grading in minutes.

Output: slide title, bullets, and a one-sentence speaker note per slide.
```

### 3b. Technical overview (slides 3–4)

```
Using the "Technical Overview" and "Multi-Agent Report Pipeline" sections of PITCH_REPORT.md, create 2 slides for the **Technical overview** part of a 5-minute pitch:

Slide A — What we built: 4–5 bullets covering (1) retrieve & normalise evidence, (2) classify by evidence level 1–6, (3) identify gaps with "how to close", (4) score social hype (Reddit + Trends), (5) output confidence score + PDF report. Mention 50+ interventions, 11 sources.

Slide B — How it works (architecture): 4–5 bullets: LangGraph six-step pipeline (Retriever → Researcher Classifier, Gap Analyst, Social Media Expert [parallel] → Judge → Reporter); Gemini + optional MedGemma; unified schema, dual storage (JSON + SQLite); rubric-driven deterministic scoring. Optionally suggest: "Simple diagram: one query → Retriever → 3 analysts in parallel → Judge → Reporter → PDF."

Output: slide title, bullets, and a one-sentence speaker note per slide. No invented details—only from the report.
```

### 3c. Rationale (slide 5)

```
Using the "Rationale" section of PITCH_REPORT.md, create **one slide** for the **Rationale** part of the pitch ("why this approach"):

- Title: e.g. "Why This Approach" or "Design Choices".
- 4–5 bullets: automating due diligence; schema-first / reason later; multi-source evidence; transparent reproducible confidence (deterministic rubric); critical self-check (Judge agent). Keep each bullet to one short line.
- One-sentence speaker note tying it to VC value: e.g. "We built for speed, transparency, and auditability—what investors and pharma need."

Output: slide title, bullets, speaker note. Use only content from the report.
```

### 3d. Innovation (slides 6–7)

```
Using the "Innovation and Novelty" section of PITCH_REPORT.md, create **2 slides** for the **Innovation** part. Judges specifically look for **novelty**—elements beyond the core project tasks. Make that explicit.

Slide A — Novel elements: 4–5 bullets. Dedicated Judge agent (critique-only, no positive spin); social hype vs evidence in one report (Reddit + Google Trends); end-to-end PDF; deterministic + optional LLM; 50+ interventions with aliases; rubric-driven, auditable grading. Label why each is "beyond the brief" where relevant.

Slide B — Unique value: 3–4 bullets. Single query → full report; unified data layer (one schema, one store); reproducibility (same corpus + rubrics = same numbers). Optional: one bullet on differentiation vs consultants vs generic AI tools (from Market Analysis / Competitive Context in the report).

Output: slide title, bullets, and a one-sentence speaker note per slide. Emphasise novelty in the bullets and speaker notes.
```

### 3e. Outlook (slides 8–9)

```
Using the "Future Roadmap," "Business Development," and "Summary for VC Slides" sections of PITCH_REPORT.md, create **2 slides** for the **Outlook** part (how we would scale or turn this into a company):

Slide A — Path to product: 4–5 bullets. Short-term: API (FastAPI), web UI, on-demand ingest, more modules (trajectory, comparison). Medium-term: more sources, verticals, enterprise features. Long-term: regulatory/academic variants, expansion beyond ageing, data products. Keep each to one line.

Slide B — Business and ask: 3–4 bullets. Positioning: "Evidence intelligence for longevity." Revenue: SaaS/API, custom rubrics, white-label. Early adopters: longevity VCs, pharma BD. **Ask:** support to reach production API and first paying pilots (compute, advisory, intros to longevity funds and pharma innovation units). One-sentence speaker note: e.g. "We’re ready to take this to production and first customers; we’re looking for [X]."

Output: slide title, bullets, speaker note per slide. Use only content from the report.
```

### 3f. Closing (slide 10)

```
Create the **closing slide** for a 5-minute pitch, using PITCH_REPORT.md:

- Title: e.g. "Thank you" or "LongevityLens — Evidence intelligence for ageing interventions."
- 2–3 bullets or one line: repeat the one-liner (one query → evidence report with confidence score, gap analysis, hype context, limitations → PDF); optional: "Demo available" or "Questions?"
- Short speaker note: thank the judges, invite questions, and optionally mention the team or where to find more info.

Output: slide title, bullets or single line, speaker note.
```

---

## Prompt 4 — Export format (for slide tools)

Use this after you have slide content, to get it in a format suitable for PowerPoint, Google Slides, or another tool.

```
I have the following slide content from a 5-minute pitch deck [paste your slide list]. Convert it into one of the following formats (choose one):

- **Markdown:** Each slide as a `## Slide N: Title` followed by bullet list and optional `Note:` line.
- **Outline for Google Slides / PowerPoint:** Plain text with "Slide N | Title" and indented bullets under each, so I can paste into outline view.
- **CSV:** Columns: slide_number, title, bullet_1, bullet_2, bullet_3, bullet_4, speaker_note. One row per slide.

Preserve all content exactly; only change the structure for the chosen format.
```

---

## Prompt 5 — Speaker script (optional)

Use this if you want a tight 5-minute script keyed to the slides.

```
Using the slide deck I will provide [paste slide list] and the content from PITCH_REPORT.md, write a **5-minute speaker script** (approx. 600–750 words) that:

- Follows the slide order and covers each bullet without reading them verbatim.
- Spends roughly: 30–45 s on title + problem, 1–1.25 min on technical overview, 45–60 s on rationale, 45–60 s on innovation (emphasising novelty), 45–60 s on outlook + ask, 15–20 s on thank-you.
- Uses conversational but professional language; includes one or two concrete numbers from the report (e.g. $5.2B, 11 sources, 50+ interventions, six-figure consultant cost).
- Marks [SLIDE: N] or [NEXT SLIDE] at each slide change so the speaker can stay in sync.

Output: the full script with [SLIDE] markers.
```

---

## Quick reference: where to find what

| Need in slides           | Source in PITCH_REPORT.md     |
|--------------------------|-------------------------------|
| One-liner, problem, ask  | Executive Summary; §8 Summary |
| Technical pipeline       | §1 Technical Overview         |
| Market size, pain point  | §2 Market Analysis            |
| Rationale                | §3 Rationale                  |
| Novelty                  | §4 Innovation and Novelty     |
| Roadmap, business, GTM  | §5–6 Production, Business    |
| Vision, mission          | §7 Future Roadmap and Vision  |

Use **PROJECT_CONTEXT.md** for challenge goal and evidence hierarchy if you want a one-slide "Challenge" context. Use **EVALUATION_CONTEXT.md** to double-check that all four required areas (Technical, Rationale, Innovation, Outlook) and the 5-minute / novelty emphasis are covered.
