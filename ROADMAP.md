# Roadmap

Agreed 2026-10-14. Tickets are created in Linear only for the **next phase**, never the whole roadmap at once. The order may change as I learn — update this file when it does.

Priorities come from 10 analysed AI Engineer vacancies: Python backend, agents, RAG, evals, APIs, observability, production.

## Principles
- **Phase 1 is isolated** (`exercises/`). From Phase 2 on, everything evolves **one service** (`projects/travel-assistant/`) — new capability on top of existing code, like real work.
- Travel is the *domain*, not a startup: no UI, auth, payments, real bookings unless a phase needs it.
- Build by hand first, frameworks later — and only to compare against what I already built.
- Cross-cutting concerns appear **where their risk appears**: security with RAG and HITL, CI from the start of Phase 2, basic observability before RAG.
- Every phase ends with something measurable, not just "it works".

## Phase 1 — Foundations (isolated) · Linear: AI Engineering Lab — Foundations
- [x] AI-5 Agent loop
- [x] AI-6 Tool design & routing
- [x] AI-7 Tool errors & recovery
- [ ] AI-8 Structured output
- [ ] AI-9 Validation & retry
- [ ] AI-10 Context management
- [ ] AI-11 MCP basics (own server, resources, Inspector)

## Phase 2 — One evolving AI service
- Wrap the agent in FastAPI: Pydantic contracts, `POST /trip-assistant`, error contract, tests. Mock travel tools → structured itinerary.
- Stream agent execution (SSE): text deltas, tool start/result, final, error. *Small ticket.*
- Async integrations (httpx, timeouts, retries) + PostgreSQL.
- Engineering baseline: Docker, CI (ruff + pytest), structured logging, request/trace id, latency, tokens, cost.

## Phase 3 — Retrieval / RAG (no frameworks)
- Minimal semantic retrieval: embeddings, similarity, top-k, in memory. Note: Anthropic has no embeddings model — use a separate provider or a local model.
- Production-style retrieval: chunking experiments, metadata, pgvector.
- Better retrieval: hybrid search, reranking, citations.
- RAG security: prompt injection via documents, data vs instructions, can retrieved content trigger tools?
- Optional: rebuild one pipeline with LangChain and compare.

## Phase 4 — Evals (CI becomes AI CI)
- Golden dataset.
- Retrieval evals: Recall@K, MRR.
- Answer evals: correctness, groundedness, citation quality; LLM-as-judge checked against my own labels.
- Regression evals in CI.

## Phase 5 — Advanced agent architecture
- Persistent state / sessions.
- Human-in-the-loop: approvals, tool permissions, destructive actions.
- Deterministic workflow vs agent decisions — where should the LLM *not* decide?
- Parallel tools / planner-executor.

## Phase 6 — Multi-agent
- Coordinator + specialist.
- Context handoff and failure propagation.
- **Single-agent vs multi-agent benchmark** (quality, latency, tokens, cost, failure rate, complexity). "Single agent wins" is a valid result.

## Phase 7 — LangGraph
- Rebuild one existing workflow; add checkpoints/HITL; compare direct SDK vs LangGraph.

## Phase 8 — Deeper production
- LLM tracing platform, dashboards, quality monitoring, deployment.

## Working agreement
- **One backlog owner** writes and changes Linear tickets; the other AI only proposes. I approve changes.
- New phase tickets are created when the current phase is nearly done (e.g. at AI-10/AI-11).