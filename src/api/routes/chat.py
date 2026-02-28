"""Gemini-powered chat endpoint with server-side tool access.

The chat agent dynamically discovers available tools and lets Gemini
call them server-side. Tool definitions are generated from discover_tools()
so new tools are immediately available without code changes.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from google import genai
from loguru import logger
from pydantic import BaseModel, Field

from src.api.dependencies import get_storage
from src.config import settings
from src.api.routes.tools import (
    _read_cache,
    _write_cache,
    discover_tools,
    get_tool_definitions,
)
from src.stats.summary import generate_summary
from src.storage.manager import StorageManager

router = APIRouter(tags=["chat"])

MAX_ROUNDS = 5

# ── Request / Response models ────────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ToolCallRecord(BaseModel):
    name: str
    args: dict
    result_preview: str = ""  # first 200 chars of result


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    model: str = "gemini-2.0-flash"


# ── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are AGE-nt, an AI research assistant specialising in aging and longevity science.

You have access to a comprehensive evidence database covering {intervention_count} aging interventions, with data from PubMed, ClinicalTrials.gov, Europe PMC, Semantic Scholar, DrugAge, NIH grants, patents, FDA/regulatory, news, social media, and Google Trends.

Your tools let you:
- Get summary statistics for any intervention
- Grade evidence quality and strength
- Score research momentum and trajectory
- Identify evidence gaps
- Compute hype-to-evidence ratios
- Search across all documents
- List all available interventions

When answering questions:
1. Use your tools to fetch real data — don't guess or hallucinate numbers
2. Cite specific document counts and source types
3. Be honest about evidence gaps and limitations
4. Distinguish between strong evidence (RCTs, meta-analyses) and weak evidence (animal studies, in vitro)
5. When asked about an intervention, start with get_stats to understand the data landscape

Current date: {date}"""


# ── Tool execution ───────────────────────────────────────────────────────────

async def _execute_tool(
    tool_name: str,
    args: dict,
    storage: StorageManager,
) -> dict:
    """Execute a tool call from the chat agent."""
    # Strip "get_" prefix if present (Gemini sends "get_evidence", we map to "evidence")
    clean_name = tool_name.removeprefix("get_")

    # Built-in tools that don't need discovery
    if clean_name == "stats":
        intervention = args.get("intervention", "")
        try:
            summary = generate_summary(intervention.lower())
            return summary
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
        query = args.get("query", "")
        intervention = args.get("intervention")
        docs = storage.get_documents(intervention.lower()) if intervention else []
        if not intervention:
            all_interventions = await storage.get_interventions()
            for name in all_interventions:
                docs.extend(storage.get_documents(name))
        matches = []
        for doc in docs:
            text = f"{doc.title} {doc.abstract}".lower()
            if query.lower() in text:
                matches.append({
                    "title": doc.title,
                    "source_type": doc.source_type.value,
                    "intervention": doc.intervention,
                    "date_published": doc.date_published.isoformat(),
                })
                if len(matches) >= 20:
                    break
        return {"query": query, "results": matches, "count": len(matches)}

    # Dynamic tool execution
    intervention = args.get("intervention", "")

    # Check cache first
    cached = _read_cache(clean_name, intervention.lower())
    if cached is not None:
        return cached

    # Try running the tool
    tools = discover_tools()
    if clean_name not in tools:
        # Fall back to raw summary data — Gemini can reason over it
        try:
            return generate_summary(intervention.lower())
        except Exception:
            return {"error": f"Tool '{clean_name}' not available and no summary data found"}

    fn, _, _ = tools[clean_name]
    try:
        result = fn(intervention.lower(), storage)
        result_dict = result.model_dump() if hasattr(result, "model_dump") else result
        _write_cache(clean_name, intervention.lower(), result_dict)
        return result_dict
    except Exception as e:
        logger.error(f"Tool {clean_name} failed: {e}")
        return {"error": f"Tool execution failed: {e}"}


# ── Gemini agent loop ────────────────────────────────────────────────────────

async def _run_agent(
    messages: list[ChatMessage],
    gemini_key: str,
    storage: StorageManager,
) -> ChatResponse:
    """Run the Gemini agent with tool calling."""
    client = genai.Client(api_key=gemini_key)

    # Build system prompt with intervention count
    interventions = await storage.get_interventions()
    system = SYSTEM_PROMPT.format(
        intervention_count=len(interventions),
        date=datetime.now().strftime("%Y-%m-%d"),
    )

    # Get dynamic tool definitions
    tool_defs = get_tool_definitions()

    # Build Gemini contents from message history
    contents = []
    for msg in messages:
        role = "user" if msg.role == "user" else "model"
        contents.append(genai.types.Content(
            role=role,
            parts=[genai.types.Part(text=msg.content)],
        ))

    tool_calls_record: list[ToolCallRecord] = []

    for round_num in range(MAX_ROUNDS):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
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
            logger.error(f"Gemini API error (round {round_num}): {e}")
            return ChatResponse(
                response=f"I encountered an error communicating with the AI model: {e}",
                tool_calls=tool_calls_record,
            )

        # Check for function calls
        fn_calls = []
        text_parts = []
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fn_calls.append(part.function_call)
                elif part.text:
                    text_parts.append(part.text)

        if not fn_calls:
            # No tool calls — return the text response
            final_text = "\n".join(text_parts) if text_parts else "(No response generated)"
            return ChatResponse(
                response=final_text,
                tool_calls=tool_calls_record,
            )

        # Add the model's response to contents
        contents.append(response.candidates[0].content)

        # Execute each function call
        fn_response_parts = []
        for fc in fn_calls:
            args = dict(fc.args) if fc.args else {}
            logger.info(f"Chat tool call: {fc.name}({args})")

            result = await _execute_tool(fc.name, args, storage)
            result_str = json.dumps(result, default=str)

            tool_calls_record.append(ToolCallRecord(
                name=fc.name,
                args=args,
                result_preview=result_str[:200],
            ))

            fn_response_parts.append(genai.types.Part(
                function_response=genai.types.FunctionResponse(
                    name=fc.name,
                    response=result,
                ),
            ))

        # Send tool results back to Gemini
        contents.append(genai.types.Content(
            role="user",
            parts=fn_response_parts,
        ))

    return ChatResponse(
        response="I reached the maximum number of tool-calling rounds. Please try a more specific question.",
        tool_calls=tool_calls_record,
    )


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    request: ChatRequest,
    x_gemini_key: str | None = Header(None),
    storage: StorageManager = Depends(get_storage),
) -> ChatResponse:
    """Gemini-powered chat with server-side tool access.

    Send messages and get AI responses grounded in real evidence data.
    Requires a Gemini API key in the X-Gemini-Key header.
    """
    gemini_key = x_gemini_key or settings.gemini_api_key
    if not gemini_key:
        raise HTTPException(
            status_code=401,
            detail="Gemini API key required. Add it in Settings or set GEMINI_API_KEY in .env.",
        )

    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    return await _run_agent(request.messages, gemini_key, storage)
