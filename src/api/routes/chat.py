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
    model: str = "gemini-3.1-pro-preview"


# ── System prompt ────────────────────────────────────────────────────────────

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


# ── Tool execution ───────────────────────────────────────────────────────────

async def _execute_tool(
    tool_name: str,
    args: dict,
    storage: StorageManager,
) -> dict:
    """Execute a tool call from the chat agent."""
    # Strip "get_" prefix if present (Gemini sends "get_evidence", we map to "evidence")
    clean_name = tool_name.removeprefix("get_")

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

    # Check cache first
    cached = _read_cache(clean_name, intervention.lower())
    if cached is not None:
        return cached

    # Try running the tool
    tools = discover_tools()
    if clean_name not in tools:
        # Fall back to raw summary data — Gemini can reason over it
        try:
            from src.stats.summary import generate_summary
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
                model="gemini-3.1-pro-preview",
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
