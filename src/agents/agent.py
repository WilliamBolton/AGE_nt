from typing import TypedDict, Dict

import google.genai as genai
from langgraph.graph import StateGraph, START, END

from config import GOOGLE_API_KEY
from my_agent.tools import search_pubmed


class BioState(TypedDict):
    """Shared state for the LangGraph bio pipeline."""

    query: str
    raw_findings: str
    analysis: str


client = genai.Client(api_key=GOOGLE_API_KEY)


def researcher_node(state: BioState) -> BioState:
    """
    Researcher node:
    Uses the PubMed tool to fetch articles related to the user's query.
    """
    query = state["query"]
    findings = search_pubmed(query)
    new_state: Dict = dict(state)
    new_state["raw_findings"] = findings
    return new_state  # type: ignore[return-value]


def analyst_node(state: BioState) -> BioState:
    """
    Analyst node:
    Summarises the raw PubMed findings into a scientific-style report.
    """
    prompt = (
        "You are a biomedical researcher.\n"
        "Summarise the following PubMed findings into a concise, structured "
        "scientific report for the given query.\n\n"
        f"User query:\n{state['query']}\n\n"
        f"PubMed findings:\n{state['raw_findings']}"
    )

    result = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[prompt],
    )

    text_parts = []
    for candidate in getattr(result, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            if hasattr(part, "text"):
                text_parts.append(part.text)

    analysis = "\n".join(text_parts) if text_parts else str(result)

    new_state: Dict = dict(state)
    new_state["analysis"] = analysis
    return new_state  # type: ignore[return-value]


# Build LangGraph pipeline equivalent to the old SequentialAgent
builder = StateGraph(BioState)
builder.add_node("researcher", researcher_node)
builder.add_node("analyst", analyst_node)

builder.add_edge(START, "researcher")
builder.add_edge("researcher", "analyst")
builder.add_edge("analyst", END)

bio_pipeline = builder.compile()


