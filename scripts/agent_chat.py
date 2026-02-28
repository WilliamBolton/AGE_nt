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
from src.stats.summary import generate_summary
from src.storage.manager import StorageManager

# ── Config ──────────────────────────────────────────────────────────────────

MAX_ROUNDS = 8
MODEL = "gemini-2.0-flash"

SYSTEM_PROMPT = """You are AGE-nt, an AI research assistant specialising in aging and longevity science.

You have access to a comprehensive evidence database covering {intervention_count} aging interventions, with data from PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge, NIH grants, patents, FDA/regulatory, news, social media, and Google Trends.

Your tools let you:
- Get summary statistics for any intervention (get_stats)
- Grade evidence quality and strength (get_evidence)
- Score research momentum and trajectory (get_trajectory)
- Identify evidence gaps (get_gaps)
- Compute hype-to-evidence ratios (get_hype)
- Search across all documents (search_documents)
- List all available interventions (list_interventions)

When answering questions:
1. Use your tools to fetch real data — don't guess or hallucinate numbers
2. Cite specific document counts and source types
3. Be honest about evidence gaps and limitations
4. Distinguish between strong evidence (RCTs, meta-analyses) and weak evidence (animal studies, in vitro)
5. When asked about an intervention, start with get_stats to understand the data landscape, then use the other tools to deepen your analysis

Current date: {date}"""


# ── Tool execution (same logic as chat.py) ──────────────────────────────────


async def execute_tool(
    tool_name: str,
    args: dict,
    storage: StorageManager,
) -> dict:
    """Execute a tool call from the agent."""
    clean_name = tool_name.removeprefix("get_")

    if clean_name == "stats":
        intervention = args.get("intervention", "")
        try:
            return generate_summary(intervention.lower())
        except Exception as e:
            return {"error": f"Failed to get stats: {e}"}

    if clean_name == "list_interventions":
        interventions = await storage.get_interventions()
        result = []
        for name in interventions:
            count = await storage.count_documents(name)
            result.append({"name": name, "document_count": count})
        return {"interventions": result, "total": len(result)}

    if clean_name == "search_documents":
        query_text = args.get("query", "")
        intervention = args.get("intervention")
        docs = storage.get_documents(intervention.lower()) if intervention else []
        if not intervention:
            all_interventions = await storage.get_interventions()
            for name in all_interventions:
                docs.extend(storage.get_documents(name))
        matches = []
        for doc in docs:
            text = f"{doc.title} {doc.abstract}".lower()
            if query_text.lower() in text:
                matches.append({
                    "title": doc.title,
                    "source_type": doc.source_type.value,
                    "intervention": doc.intervention,
                    "date_published": doc.date_published.isoformat(),
                })
                if len(matches) >= 20:
                    break
        return {"query": query_text, "results": matches, "count": len(matches)}

    # Dynamic tool execution
    intervention = args.get("intervention", "")

    cached = _read_cache(clean_name, intervention.lower())
    if cached is not None:
        return cached

    tools = discover_tools()
    if clean_name not in tools:
        try:
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
