# 01 · Minimal agent loop — design

> Note on process: the ticket says design first, implementation second. I did it
> the other way round — code and experiments first, this document after. So it
> records the design I arrived at, not the one I planned.

## 1. Why a loop at all?

The loop is needed because the model does not call the tool itself — we do, and
we need to stay in control of that.

Mechanically: one HTTP request gets one response. The model stops with
`stop_reason: "tool_use"` and the connection closes. There is no way to hand it
the tool result except by sending a **new** request with the result appended.
That repetition is the loop.

## 2. Who decides what

The model decides which tool to call, and whether to call one at all.
Our code owns the implementation of each tool and the decision to break the loop.

One nuance worth being precise about: the *signal* that the task is finished
comes from the model (`stop_reason`), while the *mechanism* of stopping is ours.
The model cannot end the loop by itself, and our code does not judge whether the
task is actually done. Our code also validates the arguments the model generated
before anything is executed — the model writes them, we decide whether they are
safe to run.

## 3. Why `!= "tool_use"` and not `== "end_turn"`

So that every other signal does not need its own branch: if it is not
`tool_use`, the turn is over. The loop continues for exactly one reason — the
model is asking for work.

The concrete failure of the `== "end_turn"` version: a response stopped by
`max_tokens` (or `refusal`) would fall through into the body of the loop, where
there are no `tool_use` blocks at all. We would then append a `user` message
with an empty `content` list and get a 400 back from the API.

Known `stop_reason` values: `end_turn`, `tool_use`, `max_tokens`,
`stop_sequence`, `refusal`, `pause_turn`. Only `tool_use` continues the loop.
`pause_turn` is the one that would need a branch of its own ("resend to
continue") — it comes with server-side tools, which this exercise does not use.

## 4. Matching results to requests

By `tool_use_id`, not by tool name and not by position in the array.

I first assumed "by tool name" — the very first run disproves it: turn 1 asked
for two `web_search` calls in one response, so the name was identical for both.
Only the ids differed (`toolu_01Rdqkxee…`, `toolu_0148jK4j…`), and each
`tool_result` carries the id of the block that requested it.

Several `tool_use` blocks in one response are parallel calls. All their results
must go back in a **single** `user` message. Splitting them across separate
messages is wrong, and it also teaches the model to stop issuing parallel calls.

## 5. The iteration cap

`MAX_ITERATIONS = 20` protects against a model that loops without progress —
keeps calling a tool, gets the result, makes no progress, calls again, and never
handles the error it is being handed.

Hitting the cap is a **failure, not a normal exit**. Normal termination is the
model's `stop_reason`. So the code prints an explicit warning and returns `None`
instead of returning whatever half-finished text it has: an unfinished result
must not be passed off as a finished one. In normal operation this cap never
fires — if it does, something is wrong with the agent, the tools or the prompt.

## 6. No `eval()` — and what the input shape really costs

`eval(expression)` is out because the user can send code instead of values: the
user's text influences what the model writes, the model writes `expression`, and
`eval` would execute it. Arbitrary code execution driven by a prompt.

So `calculate` parses the string into an AST and walks it with an allowlist —
numbers, `+ - * / % **`, unary signs, nothing else. Any other node type
(`Call`, `Name`, …) is rejected before evaluation. Two extra guards: a cap on
the exponent (`9 ** 9 ** 9` is valid arithmetic that hangs the process) and an
explicit division-by-zero check so the model gets a readable message.

The more interesting half: if the tool took `a` and `b` as numbers instead of an
expression string, the JSON schema would guarantee they are numbers. Nothing to
parse, no `eval`, and the vulnerability would not exist at all — not "closed",
but absent. All ~50 lines of AST code exist because of one design choice.

**The shape of a tool's input determines both the amount of code I write and the
class of vulnerabilities I have to defend against.**

## 7. Failure modes — handled and not

**Tool raises inside itself** (division by zero, unparseable expression): we
catch specific exception types and pass the message back to the model, which
then tells the user where the error was. Verified: the `10 / 0` run came back
`[ERROR] Error: division by zero` and the model explained it, no crash.

**Unknown tool name.** My first instinct was that this cannot happen — the model
would just answer without a tool. It can happen, for two reasons:

- hallucinated names do occur (a typo, or a tool remembered from earlier context
  that is no longer in `tools`) — rarer, more likely in long sessions with many
  tools;
- **drift in my own code**: the schema in `TOOLS` and the function in
  `TOOL_REGISTRY` live in two separate places. Delete the function, forget the
  schema, and the model dutifully asks for a tool *we* advertised. Not its
  mistake, mine.

So the unknown-name guard is not protection against a capricious model, it is
protection against my own registry drifting out of sync.

**API errors** (network, 429, 5xx): the app dies. The SDK retries twice by
default, then the exception propagates out of `run_agent`. Acceptable for an
exercise; a real system needs a policy (AI-7).

Also handled: empty search result is *not* an error (`result_count: 0`, no
`is_error`); wrong argument types from the model (`TypeError`); runaway loop (the
cap); `max_tokens` / `refusal` (loop exits, reason printed).

Deliberately not handled: unexpected exceptions inside a tool are *not* caught —
a bug in my own code should crash loudly rather than be narrated to the model.
`pause_turn` is in a comment only (needs server-side tools). Tool output size is
unbounded — a tool returning a megabyte goes straight into the context (AI-10).
