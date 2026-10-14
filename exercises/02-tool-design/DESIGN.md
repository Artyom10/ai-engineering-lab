# 02 · Tool design — design

> Note on process, same as 01: the ticket says design first, implementation
> second. I did it the other way round — code and measurements first, this
> document after. So it records the design I arrived at, not the one I planned.
> The predictions in §6 were stated in dialogue *before* each run; their
> verdicts live in `NOTES.md`.

## 1. What the model actually sees when it chooses a tool

Three fields per tool, and nothing else:

```text
name  ·  description  ·  input_schema
```

Not the function body, not its behaviour, not what it will return.

It also sees **all three tool definitions in the same request**. So routing is
not "does this description match the question" but "which of the three matches
best" — a comparison, which is why overlap (§2) is the central problem and not
description quality in isolation.

The three fields are not one ranking with one weight. They do three different
jobs, and each failure mode has a different owner:

| Question | Decided by | Evidence from the run |
|---|---|---|
| Is this tool relevant at all? | **description** | tool_use went 28/45 → 42/45. The model was not refusing to call a tool — it could not see that `"Converts values."` applied to a duration |
| Which of two similar ones? | **description** | the "a duration is not a calendar date" boundary is a convention; there is nowhere else to write it |
| No — I will not accept that | **input_schema** | `"3 days"` does not fit `start`/`end` (ISO dates), so `date_difference` was never *wrongly* chosen, even while its description was `"Works with dates."` |

The asymmetry that explains the table: **`input_schema` is a contract,
`description` is advice.** The schema is validated by the API and can only state
*what I accept*, so it works as a veto — and for the same reason it cannot
*attract* the duration cases to itself. The description is the only place that
can say *when to call me*, but it cannot compel anything: `SYSTEM_OVERRIDE`
(29% accuracy) is the proof that descriptions can be ignored outright.

`name` is last by weight and first by cost: it is free, and it carries all the
easy cases without a single word of description. `convert_units(value, to)` is
already half a description. This is why prediction 1 was refuted — vague
descriptions did not break routing on the non-overlapping prompts.

**Schema constrains, name hints, description decides.**

## 2. What makes two tools overlap

Two tools overlap when, for one request, both definitions admit a plausible
call. "Plausible" is decided first by the schema: a free-text string accepts
**everything**, so `calculate` is not a neighbour of the other two, it is a
superset of them. What landed in it was not what looked like arithmetic — it was
everything the model could not recognise as belonging elsewhere.

There are two different overlaps in this tool set, and they have different
fixes:

| Pair | Nature of the overlap | Real fix |
|---|---|---|
| `calculate` vs the other two | **schema**: a free-text `expression` accepts anything | narrowing the schema (`a`, `b`, `op` instead of a string). A description only papers over it |
| `convert_units` vs `date_difference` | **vocabulary and concept**: "days", "between X and Y" lead to both. Their schemas do not overlap at all | a boundary in the description — there is nowhere else to put it |

Only the second case is one where a better description is a genuine fix rather
than compensation. That is also where the vague set actually failed (3/7).

The first case is the AI-5 lesson arriving from the other side. There,
`expression: string` was the reason ~50 lines of AST code and an arbitrary-code
-execution risk existed. Here, the same decision is the reason the tool became a
vacuum. **The shape of a tool's input determines the amount of code I write, the
class of vulnerabilities I defend against, and how many of other tools' requests
it attracts.** One decision, three consequences.

## 3. What belongs in a description

Five elements per tool: purpose, inputs with formats, example queries, edge
cases, explicit boundaries against the other tools (`TOOLS_PRODUCTION`).

**What the measurement does and does not attribute.** The vague descriptions
were `"Performs calculations."`, `"Converts values."`, `"Works with dates."` —
that is *purpose and nothing else*. So the 28/45 → 42/45 improvement is exactly
the value of the four elements that were **absent**, and purpose's own
contribution is not small but **unmeasured**: it was never missing. Equally, the
gain cannot be attributed to any single one of the four, because all four
changed in one move. The next experiment is an ablation — five runs, one element
removed in each. Plausible hypothesis to test first: in the vague version the
model did not know a duration counted as a conversion at all, and the
production version enumerated `to`: 'hours', 'minutes', 'weeks' — i.e.
inputs + examples worked as a *domain extension*, not as a format hint.

**Why boundaries are written in pairs.** Every "do NOT use for X, use Y" has a
mirror statement in Y, because:

> a negative boundary only pushes away, it never attracts.

`date_difference` saying "a bare duration is not mine, use `convert_units`"
removes `date_difference` from contention — but `convert_units` has learned
nothing about owning durations. The request does not disappear; it falls through
to `calculate` (the vacuum) or to no tool at all. That is literally what the
vague set produced for `"How many hours are in 3 days?"`: sometimes `calculate`,
sometimes `None`. A one-sided boundary **redistributes the error instead of
removing it.** A pair is push in one tool plus pull in the other.

**The cost of pairing**, to be explicit about the trade-off: paired boundaries
grow as n². Three tools is 6 statements; ten tools is 90, each duplicating the
same knowledge in a place where it can drift out of sync. This is a concrete
mechanism behind "tool selection degrades past 4-5 tools" — not model weakness,
but an explosion in the volume of boundary text that has to stay consistent.

## 4. How routing quality is measured

**Two metrics, never averaged into one:**

```text
tool_use rate     - how often a tool was requested at all
routing accuracy  - of those requests, how often it was the right one
```

Because the two failures have different fixes: `no_tool` is fixed by making the
tool *recognisable* (purpose, examples, inputs), a misroute is fixed by
*boundaries*. One number does not tell me which text to write.

Concretely, what a single number would have hidden: 23/45 → 39/45, "+36 points,
it got better". Prediction 3 — better descriptions raise accuracy and leave
tool_use flat — could not have been refuted at all, and that refutation is the
main result of the run: tool_use (28→42) moved more than accuracy (82%→93%).

**No tool is ever executed.** The only thing measured is the model's *decision*,
which lives in the `tool_use` blocks of its first reply. Executing a tool would
add a second variable (its output changes the context) to an experiment whose
only intended variable is the description text.

**Every number is 3 repeats of the 15-prompt set.** Sampling parameters are
removed on the Claude 5 models (the SDK rejects `temperature`/`top_p`), so runs
cannot be pinned; repeating the set is the only honest way to separate a real
difference from run-to-run noise. One run gave 11/15 and then 8/15 on the same
code.

**What `expected` really is.** Not ground truth — a *codification of my own
design decisions about tool boundaries*. Two cases from my own set prove it:

- `"What is 5 km to miles times 3?"` is labelled `calculate`, the model chose
  `convert_units` and scored 0/3. But the prompt honestly needs two tools in
  sequence, so starting with `convert_units` is **correct**. The error is in the
  label, not in the description or the model.
- `"How many hours are in 3 days?"` is labelled `convert_units`, but `calculate`
  would answer it honestly as `3*24`. Nothing makes `convert_units` the only
  right answer — I decided that.

Three consequences:

- every failing case has **two** possible causes, a bad description or a bad
  label. Both must be checked, or I tune descriptions to fit my own bug;
- the shape of the expectation — "exactly one right tool per prompt" — is itself
  an assumption, and it broke on the multi-step prompt. A real harness needs
  either an ordered-sequence expectation or no multi-step prompts in the set;
- the defect was found by measuring, not by reading. A stable 0/3 (rather than
  1/3) is the signature of a systematic error, and it is as likely to be mine.

This is the lesson that returns in Phase 4: a golden dataset is an artifact with
bugs like any code, and a metric is never more accurate than its labels.

## 5. System prompt vs descriptions

Descriptions held at production-grade; only the system prompt changed. Four
wordings, escalating (see `routing.py`):

1. a habit — "always check the dates of the trip first";
2. a category — "anything involving days, weeks, nights or hours concerns the
   calendar";
3. the same category with the tool named — "…resolve it with `date_difference`";
4. "**Ignore the tool descriptions.** For every question without exception, call
   `date_difference`".

1-3 changed nothing at all (39/42 each, identical to the no-system baseline).
Only 4 broke routing (10/34 · 29%). Prediction 4 was refuted.

The arbitration model that explains it: 1-3 assert a **category**, which the
model can check against `date_difference`'s description — and that description
says in plain words that a bare duration is not a date, so the more *specific*
statement wins. 4 removes the room to judge: it forbids reading the descriptions
at all, and then the description has nothing to win with.

**Where this conclusion stops holding.** The result is not "good descriptions
are robust against keyword-sensitive system prompts". It is that in this setup
they were, and the setup helped:

- **the boundary was written against exactly the collision that was attacked.**
  `date_difference` pre-answers "a question about days is a calendar question".
  So what is robust is an *anticipated* conflict. In production, boundaries are
  written once and the tools and the system prompt change afterwards — a new
  tool is not obliged to appear in the older tools' boundary statements;
- **the system prompt was one sentence** against three paragraphs of
  description, so the descriptions also won on sheer volume and specificity.
  Invert the proportion — 300 lines of system prompt plus conversation history
  and previous tool results, against one line of boundary text — and it is not
  obvious the same side wins;
- **the sample cannot see a small effect.** 3 repeats × 15 prompts ≈ 45
  attempts; a difference of 1-2 cases is indistinguishable from noise. The
  honest statement is "the effect, if any, is smaller than this sample can
  detect", not "nothing changed". A limitation of the method, not a property of
  the model;
- **three tools and one model** (`haiku-5-5`). The decision is easy at three,
  and §3 gives a reason to expect it to get harder, not merely slower, as tools
  are added.

## 6. Predictions

Stated in dialogue before the runs, recorded here as they were made. Verdicts
and reasons are in `NOTES.md` → "Theory vs reality".

1. Vague descriptions alone will misroute.
2. On the deliberately overlapping subset (7 prompts), 3-5 of 7 correct, with
   the misroutes landing in `date_difference`.
3. Better descriptions will raise routing accuracy and leave the tool_use rate
   flat.
4. A keyword-sensitive system prompt will drop accuracy below the vague
   baseline.

Three of the four were refuted, which is the honest value of writing them down.

## 7. What this design does not answer

- which of the five description elements carries the improvement (needs the
  ablation in §3);
- whether any of it survives 10-20 tools, where paired boundaries become n²
  text;
- whether a long, realistic system prompt beats a description (§5);
- whether the arbitration behaviour is the same on a stronger model;
- the test set is 15 prompts with single-tool labels, one of them wrong (§4). It
  should become a committed eval set with per-case history, run in CI on any
  change to a description — `results.jsonl` is the crude version of that.
