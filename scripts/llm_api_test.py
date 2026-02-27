"""LLM-powered Q&A script that queries the LongevityLens API.

Uses OpenAI tool-calling to let the LLM decide which API endpoints to
call, then synthesizes a natural language answer from the data.

Usage:
    # Start the API first:
    uv run uvicorn src.api.main:app --port 8000

    # Then ask questions:
    uv run python scripts/llm_api_test.py "What do we know about rapamycin?"
    uv run python scripts/llm_api_test.py "How many clinical trials exist for rapamycin?"
    uv run python scripts/llm_api_test.py "What sources have data on rapamycin?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
import openai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings

API_BASE = "http://localhost:8000"

# Tools the LLM can call — each maps to an API endpoint
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_interventions",
            "description": "List all interventions that have stored documents, with document counts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_documents",
            "description": "Get documents for an intervention with optional filters. Returns full document data from the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intervention": {
                        "type": "string",
                        "description": "Intervention name (e.g. rapamycin, metformin)",
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Filter by source type: pubmed, clinicaltrials, europe_pmc, semantic_scholar, drugage, nih_grant, patent, regulatory, news, social",
                    },
                    "evidence_level": {
                        "type": "string",
                        "description": "Comma-separated evidence levels (1=systematic review, 2=RCT, 3=observational, 4=animal, 5=in vitro, 6=in silico)",
                    },
                    "limit": {"type": "integer", "description": "Max results to return (default 20)"},
                },
                "required": ["intervention"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": "Get aggregate statistics for an intervention: total documents, counts by source type, date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intervention": {
                        "type": "string",
                        "description": "Intervention name",
                    },
                },
                "required": ["intervention"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeline",
            "description": "Get temporal aggregation: documents per year, grouped by source type and evidence level.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intervention": {
                        "type": "string",
                        "description": "Intervention name",
                    },
                },
                "required": ["intervention"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trends",
            "description": "Get Google Trends interest-over-time data for an intervention.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intervention": {
                        "type": "string",
                        "description": "Intervention name",
                    },
                },
                "required": ["intervention"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Text search across all document titles and abstracts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search text to look for in titles and abstracts",
                    },
                    "intervention": {
                        "type": "string",
                        "description": "Limit to specific intervention (optional)",
                    },
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": ["query"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are a research assistant for LongevityLens, a system that aggregates scientific evidence on aging interventions.

You have access to a database of documents from multiple sources: PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge (animal lifespan studies), NIH grants, patents, FDA regulatory records, news articles, and Reddit discussions.

When the user asks a question:
1. Use the available tools to query the API for relevant data
2. Synthesize a clear, accurate answer from the data
3. Cite specific numbers and sources when possible
4. If data is missing or limited, say so honestly

Keep answers concise but informative. Use markdown formatting for readability."""


async def call_api(tool_name: str, args: dict) -> dict:
    """Execute an API call based on the tool name and arguments."""
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
        if tool_name == "list_interventions":
            resp = await client.get("/interventions")

        elif tool_name == "get_documents":
            params = {}
            if args.get("source_type"):
                params["source_type"] = args["source_type"]
            if args.get("evidence_level"):
                params["evidence_level"] = args["evidence_level"]
            params["limit"] = args.get("limit", 20)
            intervention = args["intervention"]
            resp = await client.get(f"/interventions/{intervention}/documents", params=params)

        elif tool_name == "get_stats":
            resp = await client.get(f"/interventions/{args['intervention']}/stats")

        elif tool_name == "get_timeline":
            resp = await client.get(f"/interventions/{args['intervention']}/timeline")

        elif tool_name == "get_trends":
            resp = await client.get(f"/interventions/{args['intervention']}/trends")

        elif tool_name == "search_documents":
            params = {"query": args["query"]}
            if args.get("intervention"):
                params["intervention"] = args["intervention"]
            params["limit"] = args.get("limit", 10)
            resp = await client.post("/interventions/search", params=params)

        else:
            return {"error": f"Unknown tool: {tool_name}"}

        if resp.status_code != 200:
            return {"error": f"API returned {resp.status_code}: {resp.text}"}

        data = resp.json()

        # Truncate large responses to stay within token limits
        if tool_name == "get_documents" and "documents" in data:
            for doc in data["documents"]:
                # Remove raw_response and source_metadata to save tokens
                doc.pop("raw_response", None)
                doc.pop("source_metadata", None)
                # Truncate long abstracts
                if doc.get("abstract") and len(doc["abstract"]) > 300:
                    doc["abstract"] = doc["abstract"][:300] + "..."

        if tool_name == "get_trends" and "data_points" in data:
            # Keep only every 4th data point for trends
            data["data_points"] = data["data_points"][::4]

        return data


async def ask(question: str) -> str:
    """Ask a question using the LLM with tool-calling loop."""
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    # Tool-calling loop (max 5 rounds)
    for _ in range(5):
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        choice = resp.choices[0]

        # If no tool calls, return the final answer
        if not choice.message.tool_calls:
            return choice.message.content or "(no response)"

        # Process tool calls
        messages.append(choice.message)
        for tool_call in choice.message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            print(f"  -> Calling {fn_name}({json.dumps(fn_args, indent=None)})")

            result = await call_api(fn_name, fn_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, default=str),
            })

    return "(max tool calls reached — partial answer)"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ask questions about LongevityLens data")
    parser.add_argument("question", help="Natural language question")
    parser.add_argument("--api-base", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    global API_BASE
    API_BASE = args.api_base

    # Verify API is reachable
    try:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=5.0) as client:
            resp = await client.get("/health")
            if resp.status_code != 200:
                print(f"Error: API at {API_BASE} returned {resp.status_code}")
                sys.exit(1)
    except httpx.ConnectError:
        print(f"Error: Cannot connect to API at {API_BASE}")
        print("Start the API first: uv run uvicorn src.api.main:app --port 8000")
        sys.exit(1)

    print(f"\nQuestion: {args.question}\n")
    answer = await ask(args.question)
    print(f"\n{answer}")


if __name__ == "__main__":
    asyncio.run(main())
