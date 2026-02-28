# AGE-nt Architecture: Advantages & Disadvantages

## Analysis date: 2026-02-28

### Setup Summary
- **Data**: Discriminated-union Pydantic schema (Base + 11 subclasses), dual storage (JSON primary + SQLite structured), dedup by source_url/id
- **Tools**: Reasoning modules (stubs + Edison) that can involve LLM calls and can call other tools — nested/hierarchical but adaptive, not a static DAG
- **Orchestration**: MCP server (8 tools, SSE) + FastAPI + CLI scripts. No fixed workflow graph — the LLM (Claude/ChatGPT via MCP) decides tool call order at runtime

### Key insight from user
Tools can involve LLM calls and can also call other tools in some cases — so the orchestration is nested and hierarchical but **adaptive** and **not structured in a static graph**.

---

See main conversation for full advantages/disadvantages writeup.
