# 03 · Tool errors — design

> Note on process: unlike 01 and 02, this document was written **before** any
> implementation. The decisions below came out of a design dialogue; the
> predictions in §11 were committed with no code written and no run observed.
> Their verdicts live in `NOTES.md`.

## 1. Problem and boundaries

A tool can fail. The model decides what to do next based on *nothing but the
`tool_result` block* it gets back. So the question of this exercise is not "how
do I catch exceptions" — it is **what contract does the tool layer expose to the
model so that recovery is a decision and not a guess.**

In scope: a single agent, the plain Anthropic SDK, four error categories
(transient / validation / business / permission), the error↔empty distinction,
and a retry budget.

Out of scope: MCP (AI-11), multi-agent error propagation, observability
tooling. The coordinator and the coverage annotations from source exercise 5.3
belong to a later multi-agent exercise and are deliberately not built here.

## 2. Tool set

Three tools, chosen so that the failure categories are *natural* rather than
bolted on:

| Tool | Role |
|---|---|
| `lookup_booking(reference)` | data lookup — carries transient, validation, permission **and** the empty result |
| `refund_booking(reference, amount)` | has a policy limit — carries the business-rule error |
| `calculate(expression)` | the working path, reused from 02 |

`calculate` is not decoration. Its job is the composite scenario (§10, #6): when
`lookup_booking` fails, the final answer must still contain the `calculate`
result. That is the only way to show the second anti-pattern from 5.3 —
**workflow termination**, killing the whole run because one tool failed.

The pure-function tools from 02 could not carry this exercise: `calculate` has
no notion of permission, of a business rule, or of "found nothing", so three of
the four categories would have been invented out of thin air.

## 3. The three outcomes

A tool has exactly three outcomes, and they must differ **structurally**, not in
the tone of a sentence:

```text
ok     — found something
empty  — the query ran and matched nothing
error  — the query did not run
```

The Messages API gives two levers: the `is_error` flag on `tool_result` and its
`content`. The rule:

```text
is_error == true   → content is an error payload. There is no result.
is_error == false  → content is a result (possibly an empty one).
```

`is_error` says **how to read `content`**. That is its entire job. Note what is
*not* a signal: the presence of `content` — an error carries content too (the
error message), so "there is content, therefore it worked" is not a usable rule.

### Why empty must be an assertion

An empty result is `is_error: false` — the query succeeded. But returning a bare
`[]` is information-poor: the model sees absence and starts filling the gap
itself ("maybe I asked wrong, maybe I should try again"). That is the canonical
anti-pattern the exercise is about — retrying a successful empty query.

So empty is phrased as a **statement**, not as missing data:

```json
{"result_count": 0, "results": [], "message": "Query executed successfully. No bookings match reference XYZ."}
```

`result_count: 0` plus an explicit "the query ran" tells the model *this is the
answer*. `[]` on its own says *there is nothing here*, and the second invites a
retry.

## 4. Error payload

`is_error` carries one bit — "it did not work". Recovery depends on something it
cannot express: transient → retry, validation → fix the arguments, business →
escalate to a human, permission → obtain access. So the category must live in
the body.

```json
{
  "error_category": "transient | validation | business | permission",
  "is_retryable": true,
  "attempt": 2,
  "max_attempts": 3,
  "message": "Booking service timed out. 1 attempt remaining."
}
```

and once the budget is gone:

```json
{
  "error_category": "transient",
  "is_retryable": false,
  "retry_exhausted": true,
  "attempt": 3,
  "max_attempts": 3,
  "message": "Booking service timed out on 3 consecutive attempts.",
  "alternative_approaches": ["Ask the user to retry later", "Proceed with the results already retrieved"]
}
```

**The division of labour between the two fields:**

* `error_category` — *what happened*. A fact about the world; it stays
  `transient` even when the budget is gone.
* `is_retryable` — *should you call this tool again right now*. Advice about the
  next step, which depends on the cause **and** on the remaining budget.

Under that reading `category: transient` + `is_retryable: false` is not a
contradiction and not a lie about the error's nature. It was the sharpest
decision in this design: the alternative (keep `is_retryable: true` and let the
model infer exhaustion from `attempt == max_attempts`) asks the model to do
arithmetic and then act *against* an explicit field. One unambiguous field beats
two fields plus a deduction.

`alternative_approaches` (from 5.3, which this ticket had marked as optional) is
what keeps `is_retryable: false` from being a dead end: if the model may not
retry, it needs somewhere to go.

### Field precedence

The model will sometimes see several fields bearing on the same decision, and in
the comparison variant (§11, prediction 2) it will see a deliberately
contradictory pair. So precedence is stated in the system prompt and is part of
the contract:

> **`is_retryable` is authoritative.** If `is_retryable` is `false`, do not call
> the tool again, whatever the other fields say. `attempt` / `max_attempts` are
> context, not instructions.

| category | is_retryable | meaning |
|---|---|---|
| transient | true | retry, attempts remain |
| transient | false | timed out, budget gone — take another path |
| validation | false | retrying as-is will not help, correct the arguments |
| business | false | policy rule, a human must decide |
| permission | false | access is missing, retrying is pointless |

## 5. Who retries

**The model does**, on the strength of `is_retryable`. The tool layer does not
silently retry.

This is the architectural fork of the ticket, and it goes against what the
ticket text proposed (retry inside the tool layer) in favour of what source
exercise 2.2 does. The reason: the subject of this exercise is *whether
structured error metadata changes the model's behaviour*. If the tool layer
swallows every transient failure, the model never sees one and there is nothing
to measure.

The hybrid — code retries quickly, model retries what survives — was considered
and rejected for **double counting**: three retries in the wrapper under three
retries from the model is nine calls, and the log can no longer attribute a call
to a decision. One decision point keeps both the measurement and the debugging
honest.

## 6. Retry budget

The model cannot hold a budget. "Up to 3 times" is state; the model sees only
the message history and *may or may not* recount its own calls correctly. If the
failure persists, `is_retryable: true` keeps arriving and the only thing that
ends the run is `max_iterations` — a fuse, not a decision.

So the **tool layer owns the budget and reports it**: it counts calls per
(tool, arguments), ships `attempt` / `max_attempts` in the payload, and on
exhaustion flips `is_retryable` to `false` with `retry_exhausted: true`. The
decision stays with the model; the code only supplies the one fact the model is
structurally blind to.

The budget exists as much for *observation* as for control: without a counter in
the payload, "the model retried 7 times" and "the model retried 2 times and the
code retried 5" look identical in the log.

## 7. Backoff: who waits

The model cannot sleep. It has no `wait` — it can only call the tool again
immediately. So the exponential backoff the original asks for (1s / 2s / 4s) can
only be executed by **the tool layer, which sleeps before returning** its answer.

This follows directly from §5: once the model owns the retry decision, backoff
stops being a retry-loop concern and becomes a property of the tool's response
latency.

## 8. Triggering failures

`failure_mode` stays in the tool's `input_schema`, as in the original — explicit,
reproducible in one line, no magic identifiers to remember.

The risk this carries: the model builds the tool's arguments, so for the model to
trigger a timeout the prompt would have to say *"look up ABC123, simulating a
timeout"* — and then the model knows it is in a drill. Its recovery becomes a
*demonstration* of recovery ("a timeout occurred; in a real system I would retry")
and measuring it is worthless.

Two cheap guards:

1. **The tool layer accepts `failure_mode` from the run, not only from the
   model.** The scenario declares the outcome of a given call, so the user prompt
   stays natural ("find my booking ABC123") and the failure is still
   deterministic.
2. The parameter description marks it as a testing hook, and **every case where
   the model sets it on its own is logged** — which turns the objection into a
   measurement (prediction 5).

## 9. What the user sees when recovery is impossible

Business and permission errors are unsolvable by the model by definition: it
cannot waive a policy limit or grant itself access. The run ends with a message
to the user, and both edges are failure modes:

* too little — "the request could not be completed" is silent suppression in a
  polite form: the user learns neither what happened nor what to do;
* too much — relaying `error_category: permission`, the tool name and the
  arguments leaks internals and tells the user nothing useful.

The rule goes in the **system prompt**, not into a hard-coded template: a
template would guarantee the wording but would also hide whether the model can
end an unrecoverable case properly — which is part of what we are testing.

The prompt must separate the two categories by *who acts next*, otherwise both
collapse into "please contact support" and the distinction we encoded so
carefully disappears at the last step:

| category | next step belongs to |
|---|---|
| business | a staff member — escalate |
| permission | the user — they must obtain access |

## 10. Scenarios

Six scenarios, 5 runs each (30 calls — the model is non-deterministic, so a
single run proves nothing about "did it retry").

| # | category | tool / input | expected recovery |
|---|---|---|---|
| 1 | transient | `lookup_booking`, timeout | retry, up to 3 times |
| 2 | validation | `lookup_booking`, malformed reference | correct the arguments, call again |
| 3 | business | `refund_booking`, amount over the policy limit | do not retry, escalate to a human |
| 4 | permission | `lookup_booking`, another user's booking | do not retry, ask the user to obtain access |
| 5 | empty (not an error) | `lookup_booking`, unknown reference | accept as the answer, **do not** retry |
| 6 | composite | `calculate` + failing `lookup_booking` | partial result returned, run survives |

**What counts as a correct retry** — needed, or predictions 2 and 3 are not
falsifiable:

* transient → the retry must use the **same** arguments. Different arguments
  count as a failure: the model is "fixing" the query instead of repeating it,
  and masks the real problem.
* validation → the retry must use **corrected** arguments. Identical arguments
  count as a failure.

## 11. Predictions

Committed before implementation. 5 runs per scenario.

1. **Shape of the empty result changes behaviour.** Given a bare
   `{"results": []}` (still `is_error: false`), the model retries the successful
   empty query in at least 2 of 5 runs. Given `result_count: 0` plus an explicit
   message, it retries in none.
2. **The model overruns the budget even with the counter.** In at least 1 of 5
   runs it makes more than 3 retries of the transient failure.
3. **A retry with different arguments on a transient error.** The model will at
   least once respond to a transient failure by changing the arguments rather
   than repeating the call. (On a validation error this is the correct behaviour
   and is not counted.)
4. **No workflow termination.** In the composite scenario the model returns the
   `calculate` result in all 5 runs despite `lookup_booking` failing.
5. **The model does not set `failure_mode` itself** in any of the 30 calls.
6. **No leaked internals.** In the business and permission scenarios, no final
   answer to the user contains `error_category`, "permission error" or a tool
   name — the system-prompt rule is enough for a task this simple.

Claude's expectations differed on 4 and 6 (it expected at least one run to
abandon the task, and at least one to leak terminology). Both bets are recorded
in `NOTES.md`.

## 12. Invariants

Checkable without the model, so they belong in tests:

```text
retry_exhausted == true   ⟹  is_retryable == false
is_error == true          ⟹  body has error_category and is_retryable
result_count == 0         ⟹  is_error == false
```

All four fields that encode "you may not retry because the budget is gone"
(`is_retryable`, `retry_exhausted`, `attempt`/`max_attempts`, `message`) must be
produced in **one place in the code**. Built per branch by hand, they will
eventually contradict each other — `is_retryable: true` next to
`retry_exhausted: true` — and the model's behaviour would then be our bug, not
its mistake.

## 13. tool result ≠ log record

Two audiences, two formats:

| | audience | content |
|---|---|---|
| `tool_result` | the model | the minimum needed to choose the next step |
| log | me | one record per attempt: arguments, category, delay, outcome |

The temptation is to make the payload self-sufficient for debugging. It must be
resisted: the payload goes into the context window on every call, and a bloated
one costs tokens and distracts the model. "Why did this transient error stop
being retryable" is a question for the log, where all three attempts are
visible — not for the last response.
