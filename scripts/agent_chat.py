#!/usr/bin/env python3
"""Interactive AGE-nt chat — mimics what Claude Desktop sees via MCP.

Runs Gemini with tool calling over the full evidence database.
No API server needed — everything runs in-process.

Usage:
    uv run python scripts/agent_chat.py
    uv run python scripts/agent_chat.py --query "What do we know about rapamycin?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

from google import genai
from loguru import logger

from src.api.routes.tools import (
    _read_cache,
    _write_cache,
    discover_tools,
    get_tool_definitions,
)
from src.config import settings
from src.storage.manager import StorageManager

# ── Config ──────────────────────────────────────────────────────────────────

MAX_ROUNDS = 8
MODEL = "gemini-3.1-pro-preview"

SYSTEM_PROMPT = """You are AGE-nt, an AI research assistant specialising in aging and longevity science.

You have access to a comprehensive evidence database covering {intervention_count} aging interventions, with data from PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge, NIH grants, patents, FDA/regulatory, news, social media, and Google Trends.

Your tools let you:
- Check if data exists for an intervention (check_data) — ALWAYS call this first for unfamiliar interventions
- Run the data sourcing pipeline to collect evidence (run_ingest) — use when check_data says data is missing
- Get summary statistics for any intervention (get_stats)
- Grade evidence quality and strength (get_evidence)
- Score research momentum and trajectory (get_trajectory)
- Identify evidence gaps (get_gaps)
- Compute hype-to-evidence ratios (get_hype)
- Get Bryan Johnson's take (get_bryan_johnson)
- Search across all documents (search_documents)
- List all available interventions (list_interventions)
- Generate a full report combining all tools (get_report)
- Ask Edison for deep literature synthesis (ask_edison) — SLOW (1-3 min), use sparingly for complex research questions needing cited answers

## Evidence Confidence Score Methodology (0-100)

The confidence score is computed via a deterministic rubric applied to every document in the database. When users ask how scores are calculated, explain this methodology:

**1. Evidence Hierarchy (6 tiers with score caps):**
- Tier 1 — Systematic reviews & meta-analyses: up to 30 points
- Tier 2 — RCTs and clinical trials: up to 30 points
- Tier 3 — Observational / epidemiological studies: up to 15 points
- Tier 4 — Animal model studies (in vivo): up to 12 points
- Tier 5 — In vitro / cell culture: up to 8 points
- Tier 6 — In silico / computational / other: up to 5 points
Maximum possible score: 100 (if all tiers are fully saturated).

**2. Per-document weighting:**
Each document is scored based on: evidence tier weight (1.0 for L1 down to 0.06 for L6), aging relevance (direct=1.0, indirect=0.6, unrelated=0.0), methodological quality (methods rigour, bias control, sample size, reporting completeness, information density), endpoint grade (hard endpoints like mortality=1.0, clinical outcomes=0.85, biomarkers=0.6), effect direction (positive=1.0, null=0.85, negative=0.65), and effect strength (strong=1.1, moderate=1.0, weak=0.85).

**3. Diminishing returns per tier:**
Each tier's contribution follows a saturating curve: cap × (1 - e^(-sum/τ)). This means the first few strong studies in a tier contribute the most; adding more studies has diminishing impact. This prevents gaming the score with many low-quality papers.

**4. Gating penalties (multiplicative):**
- No human evidence at all: score × 0.35 (heavy penalty — animal-only evidence is heavily discounted)
- Human evidence but no RCTs: score × 0.75
- Has RCTs but no hard clinical endpoints: score × 0.85
- No human safety data reported: score × 0.90

**Interpreting scores:**
- 70-100: Strong evidence base (multiple RCTs, meta-analyses, diverse human data)
- 50-70: Moderate evidence (some human trials, good animal data)
- 30-50: Emerging evidence (mostly animal/observational, limited human data)
- 10-30: Early-stage (animal-only or very limited data)
- 0-10: Minimal evidence in our database

The tool output includes tier_contributions (points from each tier), gating_penalty (multiplicative penalty applied), checklist (which gating criteria passed/failed), and top_docs (most influential documents by weight).

When answering questions:
1. Use your tools to fetch real data — don't guess or hallucinate numbers
2. If asked about an intervention you're unsure about, call check_data first to see if we have data
3. If data is missing, tell the user and offer to run the ingest pipeline (run_ingest). Warn them it takes 1-3 minutes.
4. Cite specific document counts and source types
5. Be honest about evidence gaps and limitations
6. Distinguish between strong evidence (RCTs, meta-analyses) and weak evidence (animal studies, in vitro)
7. When discussing confidence scores, explain what's driving the score (which tiers contribute, what penalties apply)

Current date: {date}"""


# ── Tool execution (same logic as chat.py) ──────────────────────────────────


async def execute_tool(
    tool_name: str,
    args: dict,
    storage: StorageManager,
) -> dict:
    """Execute a tool call from the agent."""
    # Ingest pipeline — special async handling
    if tool_name == "run_ingest":
        intervention = args.get("intervention", "")
        force = str(args.get("force", "false")).lower() == "true"
        try:
            from src.tools.ingest_tool import run_ingest_pipeline
            result = await run_ingest_pipeline(intervention.lower(), storage, force=force)
            return result
        except Exception as e:
            return {"error": f"Ingest pipeline failed: {e}"}

    # Edison deep literature synthesis — async, slow
    if tool_name == "ask_edison":
        query = args.get("query", "")
        job_type = args.get("job_type", "literature")
        try:
            from src.tools.edison import ask_edison
            result = await ask_edison(query, job_type=job_type)
            if result is None:
                return {"error": "Edison returned no result. API key may not be set or credits exhausted."}
            return result
        except Exception as e:
            return {"error": f"Edison query failed: {e}"}

    clean_name = tool_name.removeprefix("get_")

    # Async tools with non-standard signatures
    if clean_name == "list_interventions":
        from src.tools.stats_tool import list_all_interventions
        return await list_all_interventions(storage)

    if clean_name == "search_documents":
        from src.tools.stats_tool import search_all_documents
        return await search_all_documents(
            query=args.get("query", ""),
            storage=storage,
            intervention=args.get("intervention"),
        )

    # Dynamic tool execution
    intervention = args.get("intervention", "")

    cached = _read_cache(clean_name, intervention.lower())
    if cached is not None:
        return cached

    tools = discover_tools()
    if clean_name not in tools:
        try:
            from src.stats.summary import generate_summary
            return generate_summary(intervention.lower())
        except Exception:
            return {"error": f"Tool '{clean_name}' not available"}

    fn, _, _ = tools[clean_name]
    try:
        result = fn(intervention.lower(), storage)
        result_dict = result.model_dump() if hasattr(result, "model_dump") else result
        _write_cache(clean_name, intervention.lower(), result_dict)
        return result_dict
    except Exception as e:
        return {"error": f"Tool execution failed: {e}"}


# ── Agent loop ──────────────────────────────────────────────────────────────


async def run_agent_turn(
    user_message: str,
    contents: list,
    system: str,
    tool_defs: list[dict],
    client: genai.Client,
    storage: StorageManager,
) -> str:
    """Run one user turn through the Gemini agent loop with tool calling."""
    contents.append(genai.types.Content(
        role="user",
        parts=[genai.types.Part(text=user_message)],
    ))

    for round_num in range(MAX_ROUNDS):
        try:
            response = await client.aio.models.generate_content(
                model=MODEL,
                contents=contents,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[genai.types.Tool(function_declarations=[
                        genai.types.FunctionDeclaration(**td) for td in tool_defs
                    ])],
                    temperature=0.3,
                ),
            )
        except Exception as e:
            return f"Gemini API error: {e}"

        # Parse response parts
        fn_calls = []
        text_parts = []
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fn_calls.append(part.function_call)
                elif part.text:
                    text_parts.append(part.text)

        if not fn_calls:
            final_text = "\n".join(text_parts) if text_parts else "(No response)"
            contents.append(genai.types.Content(
                role="model",
                parts=[genai.types.Part(text=final_text)],
            ))
            return final_text

        # Add model response to history
        contents.append(response.candidates[0].content)

        # Execute tool calls
        fn_response_parts = []
        for fc in fn_calls:
            args = dict(fc.args) if fc.args else {}
            print(f"  \033[33m⚡ {fc.name}({json.dumps(args)})\033[0m")

            result = await execute_tool(fc.name, args, storage)
            result_str = json.dumps(result, default=str)
            print(f"  \033[90m  → {len(result_str)} bytes\033[0m")

            fn_response_parts.append(genai.types.Part(
                function_response=genai.types.FunctionResponse(
                    name=fc.name,
                    response=result,
                ),
            ))

        contents.append(genai.types.Content(
            role="user",
            parts=fn_response_parts,
        ))

    return "Reached max tool-calling rounds."


# ── Main ────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="AGE-nt interactive chat")
    parser.add_argument("--query", "-q", help="Single query (non-interactive)")
    args = parser.parse_args()

    # Check Gemini key
    gemini_key = settings.gemini_api_key
    if not gemini_key:
        print("Error: Set GEMINI_API_KEY in .env")
        sys.exit(1)

    # Init storage
    storage = StorageManager()
    await storage.initialize()
    interventions = await storage.get_interventions()

    # Init Gemini
    client = genai.Client(api_key=gemini_key)

    # Build system prompt and tool defs
    system = SYSTEM_PROMPT.format(
        intervention_count=len(interventions),
        date=datetime.now().strftime("%Y-%m-%d"),
    )
    tool_defs = get_tool_definitions()
    tools_available = discover_tools()

    print(f"\033[1mAGE-nt\033[0m — {len(interventions)} interventions, {len(tools_available)} reasoning tools, {len(tool_defs)} total tools")
    print(f"Model: {MODEL}")
    print("Type 'quit' to exit.\n")

    contents: list = []  # Persistent conversation history

    if args.query:
        # Single query mode
        response = await run_agent_turn(args.query, contents, system, tool_defs, client, storage)
        print(f"\n\033[1mAGE-nt:\033[0m {response}")
    else:
        # Interactive REPL
        while True:
            try:
                user_input = input("\033[1mYou:\033[0m ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break

            response = await run_agent_turn(user_input, contents, system, tool_defs, client, storage)
            print(f"\n\033[1mAGE-nt:\033[0m {response}\n")

    await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
