"""Generate Bryan Johnson quotes for each intervention using LLM + web search.

Uses the OpenAI Responses API with web_search tool to find real,
sourced quotes with URLs, then structures them into JSON.

Usage:
    uv run python scripts/generate_bj_quotes.py
    uv run python scripts/generate_bj_quotes.py --interventions rapamycin metformin
    uv run python scripts/generate_bj_quotes.py --batch-size 3
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import openai
from loguru import logger

from src.config import PROJECT_ROOT, settings

DATA_PATH = PROJECT_ROOT / "data" / "bryan_johnson.json"

SEARCH_PROMPT = """Search for Bryan Johnson's real, documented position on {intervention} ({description}).

Look for:
- His X/Twitter posts (@bryan_johnson) mentioning {intervention}
- His Blueprint protocol website (blueprint.bryanjohnson.com)
- YouTube videos and podcast appearances where he discusses {intervention}
- News articles or interviews quoting him on this topic

I need:
1. His actual quotes (verbatim or very close paraphrases) with source URLs
2. Whether he currently uses this in his Blueprint protocol
3. Any specific dosage he mentions
4. His overall stance (advocate, skeptic, former user, etc.)

Provide as many real, sourced quotes as you can find (2-4 ideal). Include the URL for each source."""

STRUCTURE_INSTRUCTIONS = """You are a structured data extractor. Given research about Bryan Johnson's position on an aging intervention, output valid JSON.

Output this exact JSON structure:
{
  "stance": "strong_advocate|advocate|interested|neutral|cautious|skeptical|former_user|experimenter",
  "quotes": [
    {
      "text": "The actual quote or very close paraphrase",
      "source": "Brief source description (e.g. 'X post, Jan 2024' or 'Blueprint protocol page')",
      "url": "Full URL to source, or null if not found",
      "verified": true or false
    }
  ],
  "protocol_status": "active|discontinued|monitoring|not_included|via_diet|cornerstone|experimental|watching_research|uses_alternative",
  "dosage_mentioned": "dosage string if known, null otherwise",
  "summary": "One sentence summary of his overall position"
}

Rules:
- verified=true ONLY if the quote text is close to verbatim from a specific source
- verified=false for paraphrases or inferred positions
- Include the actual URL where you found each quote (from the search results)
- If he hasn't publicly commented, set stance to "neutral" and explain in summary
- protocol_status must reflect his CURRENT usage"""


INTERVENTION_DESCRIPTIONS = {
    "rapamycin": "mTOR inhibitor, most replicated lifespan-extending drug in animal models. He has publicly discussed taking it.",
    "metformin": "Diabetes drug studied for longevity (TAME trial). He publicly stopped taking it due to exercise interference concerns.",
    "NMN": "NAD+ precursor supplement. Common in longevity protocols.",
    "NR": "Nicotinamide riboside, alternative NAD+ precursor.",
    "resveratrol": "Polyphenol, sirtuin activator. Was hyped after David Sinclair's research.",
    "exercise": "Physical activity — he has an extremely regimented daily exercise protocol.",
    "caloric restriction": "He eats a precisely measured diet. Blueprint protocol is built around this.",
    "spermidine": "Autophagy inducer found in wheat germ, aged cheese.",
    "dasatinib quercetin": "Senolytic combination (D+Q) that clears senescent cells.",
    "senolytics": "Class of drugs that clear senescent cells.",
    "fisetin": "Natural flavonoid with senolytic properties.",
    "curcumin": "Anti-inflammatory from turmeric.",
    "omega-3 fatty acids": "Fish oil / EPA / DHA supplements.",
    "CoQ10": "Coenzyme Q10, mitochondrial support.",
    "lithium": "Microdosed lithium for neuroprotection.",
    "epigenetic reprogramming": "Yamanaka factors / partial reprogramming to reverse aging.",
    "epigenetic clocks": "Biological age measurement — Horvath, GrimAge, DunedinPACE.",
    "GLP-1 agonists": "Semaglutide/Ozempic class drugs for metabolic health.",
    "young plasma": "Parabiosis / plasma exchange. He famously did blood exchange with his son.",
    "hyperbaric oxygen therapy": "HBOT for telomere lengthening and tissue repair.",
    "cold exposure": "Cold plunge / cryotherapy for hormesis.",
    "sauna": "Heat therapy for heat shock proteins.",
    "ketogenic diet": "High-fat, low-carb diet for metabolic switching.",
    "stem cell therapy": "Mesenchymal stem cells for regeneration.",
    "thymus regeneration": "TRIIM trial — growth hormone + DHEA + metformin for thymus regrowth.",
    "taurine": "Amino acid shown to extend lifespan in mice (Science 2023 paper).",
    "alpha-ketoglutarate": "TCA cycle intermediate, declines with age.",
    "berberine": "Natural AMPK activator, 'nature's metformin'.",
    "aspirin": "Low-dose aspirin for cardiovascular / anti-inflammatory.",
    "sulforaphane": "NRF2 activator from broccoli sprouts.",
    "urolithin A": "Mitophagy activator (Mitopure/Amazentis).",
    "acarbose": "Alpha-glucosidase inhibitor, strong ITP results for lifespan.",
    "glycine": "Amino acid for collagen, sleep, methylation.",
    "methylene blue": "Mitochondrial electron carrier, neuroprotective at low doses.",
    "klotho": "Longevity protein, overexpression extends lifespan in mice.",
    "telomerase activation": "TA-65, telomerase gene therapy, telomere maintenance.",
    "quercetin": "Flavonoid with senolytic and anti-inflammatory properties.",
    "NAD+ precursors": "Class overview: NMN, NR, niacin for boosting NAD+ levels.",
    "CD38 inhibitors": "Apigenin, 78c — preserve NAD+ by inhibiting CD38 enzyme.",
    "navitoclax": "BCL-2 inhibitor senolytic (ABT-263).",
    "UBX0101": "Unity Biotechnology MDM2 inhibitor senolytic.",
    "FOXO4-DRI": "Peptide senolytic targeting FOXO4-p53 interaction.",
    "SRT1720": "Synthetic sirtuin activator.",
    "trehalose": "Sugar that induces mTOR-independent autophagy.",
    "GDF11": "Growth differentiation factor 11, blood factor from parabiosis research.",
    "deprenyl": "Selegiline, MAO-B inhibitor for neuroprotection.",
    "pioglitazone": "PPAR-gamma agonist for metabolic health.",
    "canagliflozin": "SGLT2 inhibitor, showed lifespan extension in ITP.",
    "everolimus": "mTOR inhibitor, rapamycin analogue.",
    "niacin": "Vitamin B3, NAD+ precursor.",
    "17-alpha-estradiol": "Non-feminizing estrogen, extended male mouse lifespan in ITP.",
}


def _extract_citations(response) -> list[dict]:
    """Extract citation URLs from Responses API output annotations."""
    citations = []
    for item in response.output:
        if not hasattr(item, "content"):
            continue
        for content_block in item.content:
            if not hasattr(content_block, "annotations"):
                continue
            for ann in content_block.annotations:
                if hasattr(ann, "url") and ann.url:
                    citations.append({
                        "url": ann.url,
                        "title": getattr(ann, "title", None),
                    })
    return citations


def generate_quotes_for_intervention(
    client: openai.OpenAI,
    intervention: str,
    description: str,
) -> dict | None:
    """Generate quotes for a single intervention using web search + structuring."""
    try:
        # Step 1: Web search for real quotes and sources
        search_input = SEARCH_PROMPT.format(
            intervention=intervention,
            description=description,
        )

        logger.debug(f"  [{intervention}] Searching web...")
        search_resp = client.responses.create(
            model=settings.openai_model,
            tools=[{"type": "web_search"}],
            input=search_input,
        )

        search_text = search_resp.output_text
        citations = _extract_citations(search_resp)
        logger.debug(f"  [{intervention}] Found {len(citations)} citations")

        # Step 2: Structure the research into our JSON format
        structure_input = (
            f"Here is research about Bryan Johnson's position on {intervention}:\n\n"
            f"{search_text}\n\n"
            f"Source URLs found:\n"
            + "\n".join(f"- {c['url']} ({c.get('title', 'no title')})" for c in citations)
            + "\n\nPlease structure this into the required JSON format."
        )

        struct_resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": STRUCTURE_INSTRUCTIONS},
                {"role": "user", "content": structure_input},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        raw = struct_resp.choices[0].message.content or "{}"
        result = json.loads(raw)

        # Inject any citation URLs that the structuring step may have missed
        if citations and result.get("quotes"):
            for quote in result["quotes"]:
                if not quote.get("url"):
                    # Try to find a matching citation
                    for c in citations:
                        if c.get("title") and c["title"].lower() in quote.get("source", "").lower():
                            quote["url"] = c["url"]
                            break

        return result

    except Exception as e:
        logger.error(f"Failed to generate quotes for {intervention}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate Bryan Johnson quotes with web search")
    parser.add_argument("--interventions", nargs="+", help="Specific interventions to generate (default: all)")
    parser.add_argument("--batch-size", type=int, default=3, help="Concurrent requests (default: 3)")
    args = parser.parse_args()

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not set. Cannot generate quotes.")
        return

    client = openai.OpenAI(api_key=settings.openai_api_key)

    # Load existing data to preserve entries we're not regenerating
    existing = json.loads(DATA_PATH.read_text()) if DATA_PATH.exists() else {}
    existing_interventions = existing.get("interventions", {})

    # Select which interventions to process
    if args.interventions:
        targets = {k: v for k, v in INTERVENTION_DESCRIPTIONS.items() if k in args.interventions}
        if not targets:
            logger.error(f"None of {args.interventions} found in intervention list")
            return
    else:
        targets = INTERVENTION_DESCRIPTIONS

    logger.info(f"Generating Bryan Johnson quotes for {len(targets)} interventions using {settings.openai_model} + web search...")
    logger.info(f"Batch size: {args.batch_size}")

    results: dict[str, dict] = dict(existing_interventions)  # Start with existing
    failed: list[str] = []

    # Process with thread pool (Responses API is sync)
    interventions = list(targets.items())
    for i in range(0, len(interventions), args.batch_size):
        batch = interventions[i : i + args.batch_size]
        batch_num = i // args.batch_size + 1
        total_batches = (len(interventions) + args.batch_size - 1) // args.batch_size
        logger.info(f"Batch {batch_num}/{total_batches}...")

        with ThreadPoolExecutor(max_workers=args.batch_size) as pool:
            futures = {
                pool.submit(generate_quotes_for_intervention, client, name, desc): name
                for name, desc in batch
            }
            for future in as_completed(futures):
                name = futures[future]
                result = future.result()
                if result:
                    results[name] = result
                    n_quotes = len(result.get("quotes", []))
                    n_urls = sum(1 for q in result.get("quotes", []) if q.get("url"))
                    logger.info(f"  {name}: {result.get('stance', '?')} ({n_quotes} quotes, {n_urls} with URLs)")
                else:
                    failed.append(name)
                    logger.warning(f"  {name}: FAILED")

        # Brief pause between batches to be polite to the API
        if i + args.batch_size < len(interventions):
            time.sleep(1)

    # Build final JSON
    output = {
        "_meta": {
            "description": "Bryan Johnson quotes and positions on aging interventions.",
            "generation_method": f"Generated via {settings.openai_model} with web search (OpenAI Responses API).",
            "last_updated": "2026-02-28",
            "note": "Quotes sourced via web search. Check 'verified' field — true means close to verbatim from a found source, false means paraphrased. URLs link to original sources where found.",
        },
        "interventions": results,
    }

    DATA_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    logger.info(f"Written {len(results)} intervention profiles to {DATA_PATH}")
    if failed:
        logger.warning(f"Failed interventions ({len(failed)}): {failed}")


if __name__ == "__main__":
    main()
