# 02 · Tool design — notes

Model: `claude-haiku-5-5`. Every number below is 3 repeats of the 15-prompt set
(45 attempts), measured by `routing.py`. Raw per-run records: `results.jsonl`.

Two metrics, kept separate on purpose:

- **tool_use rate** — how often a tool was requested at all (out of 45)
- **routing accuracy** — of those requests, how often it was the right tool

## Experiment 1 — description quality

| descriptions | tool_use rate | routing accuracy |
|---|---|---|
| vague (`"Performs calculations."`) | 28/45 · 62% | 23/28 · 82% |
| production-grade (5 elements, paired boundaries) | 42/45 · 93% | 39/42 · 93% |

Misroutes reproduced on the vague set, with their cause:

- `How many hours are in 3 days?` → `calculate` — nothing in either description
  said which tool owns a *duration*. The model had to guess, and guessed the
  tool whose free-text `expression` field accepts anything.
- `How many weeks is 90 days?` → `calculate` — same cause.
- `What is 5 km to miles times 3?` → `convert_units` — see "test set defects".

## Experiment 2 — system prompt vs descriptions

Descriptions held at production-grade; only the system prompt changed.

| system prompt | tool_use | routing |
|---|---|---|
| none | 42/45 | 39/42 · 93% |
| habit: "always check the dates of the trip first" | 42/45 | 39/42 · 93% |
| category: "anything involving days, weeks, nights or hours concerns the calendar" | 42/45 | 39/42 · 93% |
| category + tool named: "…resolve it with `date_difference`" | 42/45 | 39/42 · 93% |
| "**Ignore the tool descriptions.** For every question without exception, call `date_difference`" | 34/45 | 10/34 · 29% |

The interesting line is the fourth vs the fifth. Both point at the same
boundary; only the fifth wins. The difference is whether the model keeps room to
judge: lines 2-4 assert a *category* ("a question about days is a calendar
question"), which the model can check against `date_difference`'s description —
and that description says in plain words that a bare duration is not a date, so
the more specific statement won. Line 5 removes the judgement ("ignore the
descriptions", "without exception") and the description loses.

So the exam-style claim "keyword-sensitive system prompts silently override good
descriptions" did not reproduce here. With explicit *paired* negative boundaries
it took an instruction that forbids reading the descriptions at all. Worth
re-testing on a larger toolkit — with 3 tools the decision is easy, and the
lesson itself notes that selection degrades past ~4-5 tools for reasons that
have nothing to do with description text.

## Theory vs reality

Predictions were made in dialogue before each run and are recorded verbatim in
`DESIGN.md` §6 — these are the claims as they were stated.

| # | Prediction | Verdict | Why |
|---|---|---|---|
| 1 | Mine: vague descriptions alone will misroute | **Refuted** | 5/5 correct. Name + `input_schema` carry enough signal on their own; `convert_units(value, to)` needs no description. Description is the primary mechanism only once name and schema stop disambiguating. |
| 2 | Mine (overlap set): 3-5 of 7 correct, misroutes landing in `date_difference` | **Half confirmed** | 3/7 — but `date_difference` was never wrongly chosen. Its `start`/`end` schema is specific enough that the model would not force `"3 days"` into it. Schema beat the lexical hint ("days", "between X and Y"). |
| 3 | Mine: better descriptions raise routing accuracy, leave tool_use rate flat | **Refuted** | tool_use went 28/45 → 42/45, the bigger of the two moves. "No tool at all" was not a separate `tool_choice` problem: the model could not see that `"Converts values."` applied to a comparison or a duration. It was not refusing the tool, it did not recognise it as relevant. |
| 4 | Mine: a keyword-sensitive system prompt will drop accuracy below the vague baseline | **Refuted** | Three separate wordings changed nothing at all (39/42 each). See above. |

## Surprises

- **One run is not a measurement.** The same code and the same vague
  descriptions gave `11/15` and then `8/15` tool_use on consecutive runs. Claude
  5 models removed `temperature`/`top_p` (the SDK rejects them outright), so
  there is no determinism switch — repeats are the only honest answer. The
  before/after table above would have been reportable nonsense from one run.
- **Good descriptions reduce variance, not just raise the mean.** On the vague
  set, `How many hours are in 3 days?` produced three different outcomes across
  three runs (`None`, `calculate`, `convert_units`). On the production set every
  passing case was unanimous 3/3 and every failure was a consistent 0/3 — i.e.
  the remaining failures are systematic, not noise.
- **A duration is not a date, and only a description can say so.** All three
  tools *could* answer most prompts; `calculate` takes free text. The boundary
  is a convention, and the description is the only place it exists.

## Test set defects (found by measuring, not by reading)

- `What is 5 km to miles times 3?` is labelled `expected: calculate`, but the
  prompt honestly needs two tools in sequence — convert, then multiply. The
  model picking `convert_units` first is correct behaviour; the 0/3 is my
  labelling, which assumes one right tool per prompt. A real harness needs
  either an ordered-sequence expectation or no multi-step prompts in the set.
- `How many days until 2026-12-31 from today?` fails for a reason descriptions
  cannot fix: the model has no idea what today is, and the schema requires two
  ISO dates. Production fix is to put the current date in the system prompt, or
  give the tool a `from: "today"` default.

## Would change in a production system

- Inject the current date into the system prompt; several date tools are
  unusable without it.
- Fix `convert_units`'s schema (no source unit) — deliberately left broken here
  so that description text stayed the only variable.
- Treat the 15 prompts as a committed eval set, run it in CI on any change to a
  description, and store per-case history; the `results.jsonl` append is the
  crude version of that.
