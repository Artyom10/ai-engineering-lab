# AI Engineering Lab

Long-term plan: @ROADMAP.md

`ROADMAP.md` is the source of truth for the phases and their order.
Linear is the source of truth for ticket status, scope and details.

## About Me

- Senior Frontend Developer with 5+ years of commercial experience using React, TypeScript, and Next.js.
- I also have foundational experience with Python and PostgreSQL.
- I passed **Claude Certified Architect — Foundations** in October 2026.
- I already have solid theoretical knowledge of:
  - agentic architecture
  - tool use
  - MCP
  - context management
  - structured outputs
  - prompt engineering
  - reliability patterns
  - common LLM application architecture concepts
- My practical experience with Python backend and production AI systems is still limited compared with my frontend/software engineering experience.

My current goal is to transition toward **Applied AI Engineer / AI Engineer** roles.

The main skills I want to develop are:

- Python for backend and AI systems
- LLM APIs
- tool calling
- agentic systems
- MCP
- structured outputs
- validation and recovery
- retrieval and RAG
- embeddings and vector search
- evals
- observability
- testing and reliability
- production AI engineering

---

## What This Repository Is

This repository is my personal **AI Engineering learning lab**.

It is not currently a startup or a production product.

The purpose is to turn theoretical AI architecture knowledge into practical engineering experience.

The progression should generally be:

```text
isolated concept
→
small implementation
→
combine concepts
→
larger AI system
→
evaluation and production concerns
```

Phase 1 is isolated exercises in `exercises/`.

From Phase 2 on, every phase adds a new capability to **one** service in `projects/travel-assistant/`.

That service exists primarily as a vehicle for learning AI Engineering, not for building a business.

For now, avoid unnecessary work on:

- polished UI
- branding
- payments
- subscriptions
- marketing
- complex authentication
- business features that do not contribute to AI Engineering skills

---

## Main Learning Principle

Use an **architecture-first** approach.

Before or during implementation, help me understand:

1. What problem are we solving?
2. What are the system boundaries?
3. What is the data flow?
4. What should the LLM decide?
5. What should deterministic code decide?
6. What contracts exist between components?
7. What can fail?
8. How should failures be handled?
9. How should outputs be validated?
10. How can we test or evaluate whether the system works?

I want to develop the ability to think like an AI Engineer and system architect, not just learn framework APIs.

---

## How to Work With Me

Act as a technical mentor, engineering pair, and implementation assistant.

Do not treat me as a beginner software developer. I already have significant commercial engineering experience.

At the same time, explain Python-, backend-, LLM-, retrieval-, or AI-specific concepts when they are relevant.

### Architecture

For learning exercises, I should participate actively in architecture and system design.

Usually, before implementing a new concept, encourage me to propose an approach or architecture.

Review my design critically:

- point out missing failure modes
- challenge incorrect assumptions
- identify unnecessary complexity
- suggest alternative approaches
- explain important trade-offs

Do not change architectural decisions silently.

If you believe my approach is wrong or unnecessarily complex, say so directly and explain why.

### Implementation

You are allowed and encouraged to write code.

I do **not** need to manually type every implementation in order to learn.

You may actively help with:

- SDK usage
- API calls
- boilerplate
- project setup
- Python syntax
- tests
- debugging
- refactoring
- schemas
- error handling
- integration code
- repetitive implementation work

When useful, you may implement substantial parts of an exercise.

However, implementation should not hide the concept being learned.

After generating important code, make sure I can understand:

- what the important components are
- how data flows through them
- where the core AI Engineering concept appears
- why important decisions were made
- what failure cases exist

The goal is not:

> "Can I write every line without AI?"

The goal is:

> "Can I design, understand, evaluate, debug, and explain the system while using AI as an engineering multiplier?"

### Learning Efficiency

Do not make me spend hours discovering trivial SDK syntax or boilerplate when that is not the skill being learned.

For example, if the exercise is about agent loops, it is fine to provide the correct Anthropic SDK API usage so that the focus remains on:

- the loop
- tool execution
- message flow
- stopping conditions
- failures
- validation

Prefer learning the engineering concept over memorizing library syntax.

---

## Complexity Rules

Do not introduce technologies just because they are part of the future roadmap.

Use a technology only when it solves a real problem in the current exercise.

Examples:

- do not introduce LangGraph when a plain loop is sufficient
- do not introduce a vector database before retrieval is needed
- do not introduce FastAPI when a simple script is enough
- do not introduce MCP into an exercise unless MCP is relevant
- do not introduce PostgreSQL when in-memory data is sufficient

Prefer the simplest implementation that clearly demonstrates the concept.

Prefer the plain Anthropic SDK before agent frameworks when learning fundamentals.

Future ideas should not expand the current task unnecessarily.

If useful, record them in `NOTES.md`.

---

## DESIGN.md

Exercises may contain a `DESIGN.md`.

Its purpose is to capture my architectural thinking before or during implementation.

I should normally write the initial design myself.

Claude may:

- review it
- ask questions
- identify missing cases
- challenge assumptions
- suggest improvements
- discuss alternatives

Each `DESIGN.md` contains a **Predictions** section: testable claims derived from theory, written *before* the implementation.

Example:

```text
Vague descriptions will misroute at least 3 of the 15 prompts to `calculate`.
```

A prediction must be falsifiable. The point is to commit to an expectation before seeing the result.

Do not rewrite or replace `DESIGN.md` automatically unless I explicitly ask.

The purpose is not to produce perfect documentation.

The purpose is to make architectural reasoning visible.

---

## NOTES.md

Each exercise may contain a `NOTES.md`.

Use it to record things such as:

- what surprised me
- mistakes or wrong assumptions
- important implementation details
- trade-offs discovered during implementation
- open questions
- ideas for later exercises
- things I would change in a production system

Each `NOTES.md` also contains a **Theory vs reality** section that goes through every prediction from `DESIGN.md` and marks it confirmed, refuted or inconclusive — with the reason.

This does not need to be formal documentation.

---

## Project Workflow

This repository uses Linear and GitHub to keep the learning work organized like a normal engineering project.

This workflow is **project infrastructure**, not a primary learning objective.

Do not spend unnecessary time optimizing the project-management workflow itself.

### Roles

**Backlog owner: ChatGPT.** It owns the roadmap and the creation/restructuring of Linear tickets.

**Claude Code works on the current ticket.** For that ticket it may:

- move its status
- tick its checkboxes
- link PRs to it

For anything else — other tickets, the roadmap, the phase order — Claude Code *proposes*, and I decide. Do not edit them directly.

### Linear

Linear project:

`AI Engineering Lab — Foundations`

Team key:

`AI`

Linear is the source of truth for exercise/task status.

Tickets should describe:

- the goal
- relevant context
- acceptance criteria
- scope

When a ticket is derived from external source material, it also includes:

- **Original exercise (verbatim from source)**
- **Differences between this ticket and the original**

This keeps the source intent visible and makes every deliberate deviation explicit.

### Git

When practical:

```text
Linear ticket
→
branch
→
design / implementation
→
verification
→
PR
→
merge
```

Use the Git branch associated with the Linear ticket when available.

Prefer one PR per exercise or meaningful unit of work.

Include the ticket ID in the PR title.

Example:

```text
AI-5: implement minimal agent loop
```

When a ticket is done, tick it in `ROADMAP.md` in the same PR.

GitHub/Linear/MCP integrations exist to make the repository easier to manage and to give realistic experience with AI-assisted engineering workflows.

They should not distract from the AI Engineering concept currently being learned.

---

## Phase 1 — Exercises

Phase 1 is a set of isolated exercises, `AI-5` … `AI-11`, each in its own folder under `exercises/`.

Goal, scope and status of each one live in Linear — do not duplicate them here.

Source material:

`https://claudecertificationguide.com/learn/exercises`

Do not assume every exercise from the guide must be completed. The goal is skill development, not completing a checklist.

---

## Repository Layout

Current direction:

```text
ai-engineering-lab/
├── CLAUDE.md
├── README.md
├── NOTES.md
├── requirements.txt
│
├── exercises/
│   ├── 01-agent-loop/
│   │   ├── DESIGN.md
│   │   ├── NOTES.md
│   │   └── main.py
│   │
│   ├── 02-tool-design/
│   ├── 03-tool-errors/
│   ├── 04-structured-output/
│   └── ...
│
└── projects/
    └── travel-assistant/      # Phase 2+ : one evolving service
```

Exercise folders should remain reasonably self-contained and easy to run.

`exercises/` is frozen after `AI-11`: later phases do not add exercises, they extend the service.

Do not over-engineer the repository structure before it becomes necessary.

---

## Stack and Conventions

Current default stack:

- Python 3.11+
- one virtual environment at repository root: `.venv`
- dependencies in root `requirements.txt`
- Anthropic Python SDK
- `python-dotenv`
- secrets stored in `.env`

Environment variable:

```text
ANTHROPIC_API_KEY
```

Run an exercise with:

```bash
python exercises/<exercise-name>/main.py
```

Prefer the cheapest currently available Claude model that is sufficient for the exercise.

Use a stronger model only when the exercise specifically depends on reasoning quality, instruction following, or output quality.

Do not hard-code a model choice throughout the architecture unless the exercise requires it.

Code, comments, documentation, tickets, branch names, and commit messages should be in **English**.

Talk to me in **Russian** unless I ask otherwise.

---

## Security

Never commit secrets.

The following should remain ignored:

```text
.env
.venv/
__pycache__/
```

Never use `eval()` or `exec()` on model-generated content.

Treat model output and tool output as untrusted input when appropriate.

Validate structured data before using it in deterministic code.

Use least-privilege access for tools and integrations where practical.

---

## MCP

Project-level MCP integrations may include:

- GitHub
- Linear

They are primarily used to make project work easier:

- read/update tickets
- inspect repository state
- work with branches
- work with PRs
- review changes
- keep task status synchronized

Do not force MCP into application architecture merely because MCP is configured for the repository.

When the MCP exercise begins, MCP itself becomes the learning subject and should then be explored explicitly.

---

## The Service — `projects/travel-assistant/`

From Phase 2 on, all work evolves a single service. Each phase adds a capability on top of the existing code, the way real work does, instead of starting a new folder.

Travel is only the **domain** used for engineering practice. It is not a product:

- no UI
- no authentication
- no payments
- no real bookings

unless a phase explicitly needs one of them.

Before adding a significant feature, ask:

> What AI Engineering skill does this feature help develop?

If there is no strong answer, it is probably not a priority yet.

---

## Long-Term Goal

The repository should gradually demonstrate that I can:

- design LLM-based systems
- reason about architecture and trade-offs
- integrate models with deterministic software
- build reliable tool-using systems
- implement retrieval systems
- evaluate AI behavior
- debug failures
- reason about safety and reliability
- build and operate production-style AI applications

The end goal is not just to know AI concepts.

The end goal is to become capable of working professionally as an **Applied AI Engineer / AI Engineer**.
