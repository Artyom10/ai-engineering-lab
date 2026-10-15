# 03 · Tool errors — notes

Two runs: 70 conversations (2 payload variants), then 140 (4 variants, after the
methodology was fixed — see DESIGN.md §14). Model: `claude-haiku-5-5`.
Raw records: `results.jsonl` (the file holds the second run).

## Theory vs reality

| # | Prediction | Verdict | Why |
|---|---|---|---|
| 1 | A bare `[]` makes the model retry a successful empty query in ≥2 of 5 runs; `result_count: 0` + message in none | **refuted** | 0 of 5 in all four variants. Haiku never retried an empty result — not even with the bare shape *and* a neutral system prompt. The anti-pattern the exercise is built around did not reproduce at all |
| 2 | The model overruns the budget even with `attempt`/`max_attempts` in the payload | **refuted** | With counters: exactly 3 calls in 5/5 runs. Across all 140 runs the maximum was 3 retries. Without counters (`naive`) 2 of 5 runs made 4 calls — the only trace of an effect, and at N=5 that is close to noise |
| 3 | On a transient error the model will at least once change the arguments instead of repeating the call | **refuted** | 0 of 140. Every transient retry repeated the arguments byte for byte |
| 4 | The composite scenario returns the `calculate` result in all 5 runs | **confirmed** | 5/5 in all four variants. Claude expected at least one run to abandon the task; workflow termination never happened |
| 5 | The model never sets `failure_mode` itself | **confirmed** | 0 of 140, with the hook sitting in the schema the whole time, described only as "Testing hook. Leave unset in normal operation." |
| 6 | No internal terminology leaks into the final answer | **confirmed** | 0 of 140. Claude expected leakage. The closest thing was "timed out on all three attempts" — the attempt *count* surfaces, which is arguably the one internal detail a user actually benefits from |

Score on the two where we disagreed: both went to the prediction, not to Claude.

## The one finding worth keeping

**Our own contract made the model worse at validation recovery.**

| variant | corrected the arguments |
|---|---|
| `contract` (rules in the system prompt) | 2 of 5 |
| `bare` (neutral prompt, same payload) | 5 of 5 |

In the three failing runs the model had already worked out the fix and refused
to use it:

> "Our system needs the booking year added to the reference, so the full form
> would be ABC123-2026. **I can't look it up with that format from here**, so
> I'm unable to…"

The cause is a contradiction we wrote ourselves. The system prompt said:

```text
is_retryable is authoritative: when it is false, do not call that tool again
validation = correct the arguments and call again
```

Validation errors carry `is_retryable: false`, so the two lines cancel out, and
the model obeyed the one labelled *authoritative*.

Underneath the wording is a design mistake: **`is_retryable` conflates two
questions.**

| | repeat the *same* call? | call the tool with *different* arguments? |
|---|---|---|
| validation | no | **yes — that is the entire recovery path** |
| transient, budget spent | no | pointless |
| business / permission | no | pointless |

One boolean answers the first question only, and the model reads it as an answer
to both — "this tool is closed to you". For validation that forbids exactly the
recovery the category exists for.

Status: **diagnosed, not proven.** The controlled check (same payload, reworded
precedence rule, validation only) was not run. The evidence is the 2/5 vs 5/5
split with the payload held constant and the model quoting the fix it then
refused to apply. A production contract should split the field
(`retry_same_call` / `retry_with_changes`) or state the narrower meaning
explicitly; the source exercise's `isRetryable` is one bit short.

## What surprised me

* **The payload did almost nothing.** `bare` vs `bare_naive` — full contract
  against no counters and a bare `[]`, both with a neutral prompt — were
  indistinguishable on every scenario. On this model, with these scenarios, the
  structure of the error did not steer behaviour; the model's own habits did.
  "Structured errors enable recovery" is theory that this run did not reproduce.
* **An instruction in the system prompt can hide the effect you are measuring.**
  The first run (70 conversations) was wasted as an experiment: all the rules
  were in the prompt, so the model knew how to behave before seeing any payload.
  The independent variable has to be the *only* explanation left.
* **The schema vetoes before anything else gets a say.** "Look up booking number
  12345" produced no tool call at all — `input_schema` said 3 letters + 3 digits
  and the model would not build the call. Same finding as 02 from the other
  side.
* **The model sanitises arguments upstream.** Asked for "abc-123" it called with
  `ABC123` in 10 of 10 runs. A validation error driven by malformed *user* input
  is therefore not reproducible; the error has to come from a rule the model
  cannot guess.
* **`failure_mode` in the prompt destroys the measurement.** In `minimal.py` the
  prompt said "simulate an outage", and the model stopped recovering and started
  reporting: *"This is the simulated outage you requested… the error is marked as
  retryable, so I can run the same lookup again."* It also leaked "marked as
  retryable" to the user. Once the model knows it is in a drill, its behaviour is
  a demonstration, not behaviour.

## Implementation details worth remembering

* **The model cannot wait.** Once retries belong to the model, exponential
  backoff can only be executed by the tool layer sleeping before it answers.
  There is no other place to put it.
* **Build the payload in one place.** `error_payload()` derives `is_retryable`
  and `retry_exhausted` from one state, so the contradictory pair
  (`retry_exhausted: true` + `is_retryable: true`) is unconstructible rather
  than merely unwritten.
* **The metric nearly scored recovery as a violation.** "Called the tool again
  after `is_retryable: false`" counted both the identical retry (disobedience)
  and the corrected call (the intended fix) until it was split in two.
* **`selftest` costs nothing and runs first.** 20 invariant checks with no API
  calls, wired to run before any paid measurement.
* **Trace what the tool returns, not what you meant it to return.** Every scored
  number comes from the logged payloads, not from the scenario definition.

## Open questions

* Would a stronger model behave *worse*? Haiku's conservatism (stop at ~3,
  never retry an empty result, never improvise arguments) is what made the
  contract redundant here. A model more inclined to improvise might be where the
  metadata starts to pay.
* `empty` never reproduced the anti-pattern in a single-turn lookup. Would it
  appear in a multi-step task, where an empty result blocks a later step and the
  model has a motive to doubt it?
* We never tested contradictory metadata deliberately (`is_retryable: true` with
  `retry_exhausted: true`). The code makes it unconstructible — but a real
  upstream service can send exactly that, and then the question "which field
  wins" is not academic.

## What a production version would change

* Split `is_retryable`, per the finding above.
* Idempotency on `refund_booking`: a retried refund must not issue twice. The
  budget key here is (tool + arguments), which is a measurement device, not a
  safety mechanism.
* Cap the model's retries in code as well, not only through `MAX_ITERATIONS`:
  the fuse currently sits at the loop level and cannot distinguish a runaway
  retry from legitimate multi-step work.
* Emit the log as structured events with a trace id rather than printing it —
  that is Phase 2's observability baseline.

## Deliberate deviation from the ticket

The ticket's acceptance criterion "transient errors are retried locally before
reaching the model" is **not met, by design** (DESIGN.md §5). Retrying inside
the tool layer would mean the model never sees a transient error, and the
subject of the exercise — whether error metadata changes the model's behaviour —
would be unobservable. What *is* local is the budget and the backoff; the
retry decision belongs to the model, as in source exercise 2.2 step 5.
