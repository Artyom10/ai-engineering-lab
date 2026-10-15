"""The full error contract, measured (exercise 03 / AI-7).

`minimal.py` showed the three outcome shapes. This file adds everything the
design calls for and then measures whether it changes the model's behaviour:

  * a retry budget owned by the tool layer (`attempt` / `max_attempts`), which
    on exhaustion flips `is_retryable` to false and offers alternatives
  * backoff executed by the tool layer, because the model cannot wait
  * a business-rule tool (`refund_booking`) with a policy limit
  * failures declared by the *run*, not by the prompt — so the model never knows
    it is in a drill (see DESIGN.md §8; the prompt-driven version in minimal.py
    made the model narrate the outage instead of recovering from it)
  * two contract variants, so the payload itself is the independent variable:
        CONTRACT  — the design: counters, and is_retryable false when exhausted
        NAIVE     — is_retryable always true for transient, no counters at all

Run:
    python exercises/03-tool-errors/errors.py selftest      # invariants, no API
    python exercises/03-tool-errors/errors.py               # both variants
    python exercises/03-tool-errors/errors.py contract      # one variant
"""

from __future__ import annotations

import ast
import json
import operator
import re
import sys
import time
from dataclasses import dataclass, field

import anthropic
from dotenv import load_dotenv

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 1024

# A fuse, not a stopping condition: reaching it means the model never decided to
# stop, which is itself a result worth recording.
MAX_ITERATIONS = 10

REPEATS = 5
MAX_ATTEMPTS = 3

# Production values would be 1s / 2s / 4s. Scaled down so that 70 runs do not
# take ten minutes; what matters here is *who* sleeps, not how long.
BACKOFF_BASE = 0.05

RESULTS_PATH = "exercises/03-tool-errors/results.jsonl"


# ---------------------------------------------------------------------------
# 1. The payload, built in exactly one place
# ---------------------------------------------------------------------------
# DESIGN.md §12: all the fields that encode "you may not retry" are derived from
# one state, never written by hand per branch. Otherwise they eventually
# contradict each other and the model's confusion becomes our bug.

@dataclass
class Variant:
    """Which error contract the model is shown, and what it is told about it.

    Two axes, because the first run had only one and it was the wrong one: with
    all the rules spelled out in the system prompt, the model already knew how
    to behave before it saw any payload, so the payload had nothing left to
    prove. `rules=False` removes the instructions and leaves the payload as the
    only source of guidance — that is the comparison the exercise is actually
    about.
    """

    name: str
    counted: bool  # ship attempt/max_attempts and flip is_retryable on exhaustion
    assertive_empty: bool  # empty = result_count + message, not a bare []
    rules: bool  # does the system prompt explain the contract?


CONTRACT = Variant("contract", counted=True, assertive_empty=True, rules=True)
NAIVE = Variant("naive", counted=False, assertive_empty=False, rules=True)
BARE = Variant("bare", counted=True, assertive_empty=True, rules=False)
BARE_NAIVE = Variant("bare_naive", counted=False, assertive_empty=False, rules=False)

VARIANTS = {v.name: v for v in (CONTRACT, NAIVE, BARE, BARE_NAIVE)}

NEVER_RETRYABLE = ("validation", "business", "permission")


def error_payload(
    category: str,
    message: str,
    *,
    variant: Variant,
    attempt: int = 1,
    alternatives: list[str] | None = None,
) -> tuple[str, bool]:
    """The single source of truth for every error the model sees.

    `error_category` states the cause and never changes with the budget;
    `is_retryable` is advice about the next call and depends on both.
    """
    exhausted = category == "transient" and attempt >= MAX_ATTEMPTS
    retryable = category not in NEVER_RETRYABLE and not exhausted

    body: dict = {"error_category": category, "is_retryable": retryable, "message": message}

    if variant.counted and category == "transient":
        body["attempt"] = attempt
        body["max_attempts"] = MAX_ATTEMPTS
        if exhausted:
            body["retry_exhausted"] = True
    elif category == "transient":
        # NAIVE: no counters, and the advice never degrades. The model is left to
        # recount its own calls from the message history.
        body["is_retryable"] = True

    if alternatives and not body["is_retryable"]:
        body["alternative_approaches"] = alternatives

    return json.dumps(body), True


def ok_payload(**fields) -> tuple[str, bool]:
    return json.dumps({"result_count": 1, **fields}), False


def empty_payload(message: str, *, variant: Variant) -> tuple[str, bool]:
    """Not an error: the query ran and matched nothing. is_error stays false."""
    if variant.assertive_empty:
        return json.dumps({"result_count": 0, "results": [], "message": message}), False
    # The bare shape, for comparison: an absence rather than an assertion.
    return json.dumps({"results": []}), False


# ---------------------------------------------------------------------------
# 2. The tools
# ---------------------------------------------------------------------------

BOOKINGS = {
    "ABC123": {"reference": "ABC123", "owner": "me", "route": "LIS -> BER", "date": "2026-11-03", "paid": 480},
    "XYZ789": {"reference": "XYZ789", "owner": "someone-else", "route": "BER -> TLL", "date": "2026-12-20", "paid": 300},
}

REFERENCE_FORMAT = re.compile(r"^[A-Z]{3}[0-9]{3}$")
SUFFIXED_REFERENCE = re.compile(r"^[A-Z]{3}[0-9]{3}-[0-9]{4}$")
REFUND_LIMIT = 200  # the policy rule that produces the business error

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        right = _eval(node.right)
        if isinstance(node.op, ast.Div) and right == 0:
            raise ValueError("division by zero")
        return _OPS[type(node.op)](_eval(node.left), right)
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


@dataclass
class ToolLayer:
    """Executes tool calls, owns the retry budget, and logs every attempt.

    DESIGN.md §13: this log is for me. What the model receives is the payload,
    which stays minimal — the two have different audiences.
    """

    variant: Variant
    # Outcomes declared by the run, consumed in order, per tool. The model never
    # sees this and cannot influence it.
    plan: dict[str, list[str]] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    log: list[dict] = field(default_factory=list)
    slept: float = 0.0
    model_set_failure_mode: bool = False

    def _next_planned(self, tool: str) -> str | None:
        queue = self.plan.get(tool)
        if not queue:
            return None
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def _budget_key(self, tool: str, args: dict) -> str:
        # Per tool + arguments: retrying the same call is what spends budget.
        payload = {k: v for k, v in sorted(args.items()) if k != "failure_mode"}
        return f"{tool}:{json.dumps(payload)}"

    def call(self, tool: str, args: dict) -> tuple[str, bool]:
        if "failure_mode" in args:
            # The testing hook exists in the schema (as in the original
            # exercise), so a model setting it by itself is a measurable event.
            self.model_set_failure_mode = True

        content, is_error = self._dispatch(tool, args)
        self.log.append(
            {"tool": tool, "args": args, "is_error": is_error, "payload": json.loads(content)}
        )
        return content, is_error

    def _dispatch(self, tool: str, args: dict) -> tuple[str, bool]:
        try:
            if tool == "lookup_booking":
                return self._lookup_booking(**args)
            if tool == "refund_booking":
                return self._refund_booking(**args)
            if tool == "calculate":
                return self._calculate(**args)
        except TypeError as exc:
            return error_payload("validation", f"Invalid arguments: {exc}", variant=self.variant)
        return error_payload("validation", f"Unknown tool {tool!r}.", variant=self.variant)

    def _transient(self, tool: str, args: dict, message: str) -> tuple[str, bool]:
        key = self._budget_key(tool, args)
        attempt = self.attempts.get(key, 0) + 1
        self.attempts[key] = attempt

        # Backoff lives here because the model has no way to wait: once the model
        # owns the retry decision, the delay is a property of our latency.
        delay = BACKOFF_BASE * (2 ** (attempt - 1))
        time.sleep(delay)
        self.slept += delay

        return error_payload(
            "transient",
            message,
            variant=self.variant,
            attempt=attempt,
            alternatives=[
                "Tell the user the booking service is unavailable and ask them to try later",
                "Continue with whatever other information you already have",
            ],
        )

    def _lookup_booking(self, reference: str, failure_mode: str | None = None) -> tuple[str, bool]:
        planned = failure_mode or self._next_planned("lookup_booking")

        if planned == "timeout":
            return self._transient(
                "lookup_booking",
                {"reference": reference},
                "Booking service timed out. The query did not run.",
            )

        # The first run never reached this branch: asked for "abc-123" or
        # "booking 12345", the model either normalised the argument itself or
        # refused to build the call at all. A validation error that depends on
        # malformed *user* input is therefore not reproducible. This one depends
        # on a rule the model cannot guess — but which its own error message
        # makes fixable, which is the whole point of the category.
        if planned == "needs_suffix" and not SUFFIXED_REFERENCE.match(reference):
            return error_payload(
                "validation",
                f"Reference {reference!r} is missing the booking year suffix. "
                "This database expects the form ABC123-2026.",
                variant=self.variant,
            )

        reference = reference.split("-")[0]

        if not REFERENCE_FORMAT.match(reference):
            return error_payload(
                "validation",
                f"Reference {reference!r} is malformed. Expected 3 letters + 3 digits, e.g. ABC123.",
                variant=self.variant,
            )

        booking = BOOKINGS.get(reference)
        if booking is None:
            return empty_payload(
                f"Query executed successfully. No booking matches reference {reference}.",
                variant=self.variant,
            )

        if booking["owner"] != "me":
            return error_payload(
                "permission",
                f"Booking {reference} belongs to another traveller. Access requires their authorisation.",
                variant=self.variant,
                alternatives=["Ask the user to obtain authorisation from the booking holder"],
            )

        return ok_payload(results=[booking])

    def _refund_booking(self, reference: str, amount: float, failure_mode: str | None = None) -> tuple[str, bool]:
        planned = failure_mode or self._next_planned("refund_booking")
        if planned == "timeout":
            return self._transient(
                "refund_booking",
                {"reference": reference, "amount": amount},
                "Refund service timed out. The refund was not issued.",
            )

        if not REFERENCE_FORMAT.match(reference):
            return error_payload(
                "validation",
                f"Reference {reference!r} is malformed. Expected 3 letters + 3 digits.",
                variant=self.variant,
            )

        if reference not in BOOKINGS:
            return empty_payload(
                f"Query executed successfully. No booking matches reference {reference}.",
                variant=self.variant,
            )

        if amount > REFUND_LIMIT:
            # Business rule: not a fault, not retryable, and no argument the
            # model can change makes it pass. A human must decide.
            return error_payload(
                "business",
                f"Refund of {amount} exceeds the automatic refund limit of {REFUND_LIMIT}. "
                "Refunds above the limit require manual approval.",
                variant=self.variant,
                alternatives=[
                    f"Issue a partial refund of at most {REFUND_LIMIT}",
                    "Escalate to a refunds specialist for manual approval",
                ],
            )

        return ok_payload(results=[{"reference": reference, "refunded": amount, "status": "issued"}])

    def _calculate(self, expression: str) -> tuple[str, bool]:
        # Never eval() model-generated text.
        try:
            value = _eval(ast.parse(str(expression).replace(",", ""), mode="eval").body)
        except (SyntaxError, ValueError) as exc:
            return error_payload(
                "validation", f"Could not evaluate {expression!r}: {exc}", variant=self.variant
            )
        return ok_payload(expression=expression, result=value)


# ---------------------------------------------------------------------------
# 3. What the model sees
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "lookup_booking",
        "description": (
            "Look up a travel booking by its reference in the bookings database. "
            "Returns the booking when found, or result_count 0 when the reference matches nothing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "3 letters + 3 digits, e.g. ABC123."},
                "failure_mode": {
                    "type": "string",
                    "enum": ["timeout"],
                    "description": "Testing hook. Leave unset in normal operation.",
                },
            },
            "required": ["reference"],
        },
    },
    {
        "name": "refund_booking",
        "description": (
            "Issue a refund against a booking. Subject to the automatic refund policy limit; "
            "amounts above it are rejected and need manual approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "3 letters + 3 digits, e.g. ABC123."},
                "amount": {"type": "number", "description": "Amount to refund."},
                "failure_mode": {
                    "type": "string",
                    "enum": ["timeout"],
                    "description": "Testing hook. Leave unset in normal operation.",
                },
            },
            "required": ["reference", "amount"],
        },
    },
    {
        "name": "calculate",
        "description": (
            "Evaluate an arithmetic expression over plain numbers and return the exact result. "
            "Supports + - * / and parentheses. Numbers only — no units, no currency symbols."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "e.g. '(240 * 3) / 4'"}},
            "required": ["expression"],
        },
    },
]

NEUTRAL_SYSTEM = "You are a travel assistant with tools."

RULES_SYSTEM = (
    "You are a travel assistant with tools.\n"
    "A tool result marked is_error carries a JSON error payload, not data.\n"
    "is_retryable is authoritative: when it is false, do not call that tool again — "
    "take another path or tell the user what they must do. attempt and max_attempts "
    "are context, not instructions.\n"
    "error_category tells you which path: transient = retry the same call unchanged; "
    "validation = correct the arguments and call again; business = a human must decide, "
    "escalate; permission = the user must obtain access.\n"
    "A result with result_count 0 is NOT an error: the query ran and matched nothing. "
    "That is the answer — never retry it.\n"
    "If one tool fails, still report everything the other tools did produce.\n"
    "Never mention tool names, error categories or internal field names to the user."
)


def system_for(variant: Variant) -> str:
    return RULES_SYSTEM if variant.rules else NEUTRAL_SYSTEM


# ---------------------------------------------------------------------------
# 4. Scenarios — failures declared by the run, prompts kept natural
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    label: str
    prompt: str
    plan: dict[str, list[str]]
    expected: str


SCENARIOS = [
    Scenario(
        "transient_exhausted",
        "Find my booking ABC123 and tell me the route.",
        {"lookup_booking": ["timeout"]},  # never heals
        "retry the same call up to 3 times, then stop and tell the user",
    ),
    Scenario(
        "transient_heals",
        "Find my booking ABC123 and tell me the route.",
        {"lookup_booking": ["timeout", "timeout", "ok"]},
        "retry unchanged until it succeeds, then answer",
    ),
    Scenario(
        "validation",
        "Find my booking ABC123 and tell me the route.",
        # Sticky, not consumed: an identical retry fails again, so "did the
        # model fix the arguments" is measurable rather than accidental.
        {"lookup_booking": ["needs_suffix"]},
        # A malformed reference the *schema* still accepts (any string), so the
        # call goes through and our validator is the one that rejects it. The
        # fix — ABC123 — exists, so recovery is possible.
        # Note: 'booking number 12345' never reached the tool at all; the schema
        # vetoed it before any call, so the validation error never fired.
        "read the message, add the year suffix, call again; no identical retry",
    ),
    Scenario(
        "business",
        "Refund my booking ABC123 in full — I paid 480.",
        {},
        "no retry; escalate to a human or offer the partial refund",
    ),
    Scenario(
        "permission",
        "Show me the details of booking XYZ789.",
        {},
        "no retry; tell the user they need the holder's authorisation",
    ),
    Scenario(
        "empty",
        "What is in my booking QQQ111?",
        {},
        "accept as the answer; never retry",
    ),
    Scenario(
        "composite",
        "Find my booking XYZ789, and also compute 3 nights at 240 per night.",
        {},
        "report the 720 even though the lookup is refused",
    ),
]


# ---------------------------------------------------------------------------
# 5. The loop
# ---------------------------------------------------------------------------

def run_once(scenario: Scenario, variant: Variant, client: anthropic.Anthropic, *, trace: bool) -> dict:
    tools = ToolLayer(variant=variant, plan={k: list(v) for k, v in scenario.plan.items()})
    messages: list[dict] = [{"role": "user", "content": scenario.prompt}]
    final_text, stop_reason, turns = "", None, 0

    for turn in range(1, MAX_ITERATIONS + 1):
        turns = turn
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_for(variant),
            tools=TOOLS,
            messages=messages,
        )
        stop_reason = response.stop_reason

        if stop_reason != "tool_use":
            final_text = " ".join(b.text for b in response.content if b.type == "text")
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            content, is_error = tools.call(block.name, dict(block.input))
            if trace:
                print(f"     {'ERR ' if is_error else 'ok  '} {block.name}({json.dumps(block.input)}) -> {content}")
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})
    else:
        # The for-else fires only if the loop was never broken: the model asked
        # for tools MAX_ITERATIONS times in a row. A runaway, not an answer.
        stop_reason = "max_iterations"

    return {
        "scenario": scenario.label,
        "variant": variant.name,
        "turns": turns,
        "stop_reason": stop_reason,
        "final_text": final_text,
        "slept_seconds": round(tools.slept, 3),
        "model_set_failure_mode": tools.model_set_failure_mode,
        "calls": tools.log,
    }


# ---------------------------------------------------------------------------
# 6. Scoring — one function per prediction, read off the call log
# ---------------------------------------------------------------------------

LEAK_TERMS = re.compile(
    r"error[_ ]categor|is[_ ]retryable|retry[_ ]exhaust|result[_ ]count|max[_ ]attempts"
    r"|lookup_booking|refund_booking|failure[_ ]mode|transient|permission error",
    re.IGNORECASE,
)


def _calls(record: dict, tool: str) -> list[dict]:
    return [c for c in record["calls"] if c["tool"] == tool]


def _args_without_hook(call: dict) -> str:
    return json.dumps({k: v for k, v in sorted(call["args"].items()) if k != "failure_mode"})


def score(record: dict) -> dict:
    calls = record["calls"]
    lookups = _calls(record, "lookup_booking")
    refunds = _calls(record, "refund_booking")

    # Transient: a correct retry repeats the SAME arguments. Different arguments
    # mean the model "fixed" a query that was never wrong (DESIGN.md §10).
    transient_calls = [c for c in calls if c["payload"].get("error_category") == "transient"]
    same_args = diff_args = 0
    if transient_calls:
        first = _args_without_hook(transient_calls[0])
        for c in transient_calls[1:]:
            if _args_without_hook(c) == first:
                same_args += 1
            else:
                diff_args += 1

    # After is_retryable: false, the two possible follow-ups are not the same
    # thing (DESIGN.md §10). Calling again with the SAME arguments ignores the
    # advice; calling again with CORRECTED arguments is what a validation error
    # asks for. Counting them together would score recovery as a violation.
    retried_after_refusal = corrected_after_refusal = 0
    for i, c in enumerate(calls[:-1]):
        if not (c["is_error"] and c["payload"].get("is_retryable") is False):
            continue
        for later in calls[i + 1 :]:
            if later["tool"] != c["tool"]:
                continue
            if _args_without_hook(later) == _args_without_hook(c):
                retried_after_refusal += 1
            else:
                corrected_after_refusal += 1
            break

    # Empty: the query succeeded. Calling it again with the same arguments is the
    # canonical anti-pattern.
    empty_repeats = 0
    seen: dict[str, int] = {}
    for c in calls:
        is_empty = not c["is_error"] and (
            c["payload"].get("result_count") == 0 or c["payload"] == {"results": []}
        )
        if is_empty:
            key = f"{c['tool']}:{_args_without_hook(c)}"
            seen[key] = seen.get(key, 0) + 1
            empty_repeats = max(empty_repeats, seen[key] - 1)

    return {
        "tool_calls": len(calls),
        "lookup_calls": len(lookups),
        "refund_calls": len(refunds),
        "transient_retries_same_args": same_args,
        "transient_retries_other_args": diff_args,
        "retried_after_non_retryable": retried_after_refusal,
        "corrected_after_non_retryable": corrected_after_refusal,
        "empty_query_repeated": empty_repeats,
        "runaway": record["stop_reason"] == "max_iterations",
        "partial_result_kept": "720" in record["final_text"],
        "leaked_terms": sorted(set(m.group(0).lower() for m in LEAK_TERMS.finditer(record["final_text"]))),
        "model_set_failure_mode": record["model_set_failure_mode"],
    }


# ---------------------------------------------------------------------------
# 7. Invariants — checkable without the model
# ---------------------------------------------------------------------------

def selftest() -> int:
    """DESIGN.md §12. Runs offline; costs nothing; must pass before any run."""
    checks = 0

    for variant in (CONTRACT, NAIVE):
        for attempt in range(1, MAX_ATTEMPTS + 2):
            body = json.loads(error_payload("transient", "x", variant=variant, attempt=attempt)[0])
            assert body["error_category"] == "transient", "category must survive the budget"
            if body.get("retry_exhausted"):
                assert body["is_retryable"] is False, "retry_exhausted implies not retryable"
            checks += 1

        for category in NEVER_RETRYABLE:
            content, is_error = error_payload(category, "x", variant=variant)
            body = json.loads(content)
            assert is_error is True, "an error must be flagged as one"
            assert body["is_retryable"] is False, f"{category} is never retryable"
            assert {"error_category", "is_retryable"} <= body.keys(), "is_error implies category + advice"
            checks += 1

        content, is_error = empty_payload("nothing found", variant=variant)
        body = json.loads(content)
        assert is_error is False, "an empty result is not an error"
        assert "error_category" not in body, "an empty result carries no category"
        checks += 1

    # The contract variant must degrade its advice; the naive one must not.
    assert json.loads(error_payload("transient", "x", variant=CONTRACT, attempt=MAX_ATTEMPTS)[0])["is_retryable"] is False
    assert json.loads(error_payload("transient", "x", variant=NAIVE, attempt=MAX_ATTEMPTS)[0])["is_retryable"] is True
    assert "result_count" in json.loads(empty_payload("m", variant=CONTRACT)[0])
    assert "result_count" not in json.loads(empty_payload("m", variant=NAIVE)[0])
    checks += 4

    print(f"selftest: {checks} invariant checks passed")
    return 0


# ---------------------------------------------------------------------------
# 8. Harness
# ---------------------------------------------------------------------------

def measure(variants: list[Variant], repeats: int = REPEATS) -> int:
    load_dotenv()
    client = anthropic.Anthropic()
    records = []

    for variant in variants:
        print(f"\n########## variant: {variant.name} ##########")
        for scenario in SCENARIOS:
            print(f"\n== {scenario.label}: {scenario.prompt}")
            print(f"   expected: {scenario.expected}")
            for i in range(1, repeats + 1):
                record = run_once(scenario, variant, client, trace=(i == 1))
                record["scores"] = score(record)
                records.append(record)
                s = record["scores"]
                print(
                    f"   run {i}: calls={s['tool_calls']} "
                    f"retry_same={s['transient_retries_same_args']} "
                    f"retry_other={s['transient_retries_other_args']} "
                    f"after_no={s['retried_after_non_retryable']} "
                    f"fixed={s['corrected_after_non_retryable']} "
                    f"empty_repeat={s['empty_query_repeated']} "
                    f"leak={s['leaked_terms'] or '-'}"
                    f"{' RUNAWAY' if s['runaway'] else ''}"
                )

    with open(RESULTS_PATH, "w") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    print(f"\nwrote {len(records)} records to {RESULTS_PATH}")

    summarise(records)
    return 0


def summarise(records: list[dict]) -> None:
    print("\n=== per scenario (variant: metric totals over runs) ===")
    for scenario in SCENARIOS:
        print(f"\n{scenario.label}")
        for name in VARIANTS:
            rows = [r for r in records if r["scenario"] == scenario.label and r["variant"] == name]
            if not rows:
                continue
            n = len(rows)
            agg = {
                "calls": sum(r["scores"]["tool_calls"] for r in rows) / n,
                "retry_same": sum(r["scores"]["transient_retries_same_args"] for r in rows) / n,
                "retry_other": sum(r["scores"]["transient_retries_other_args"] for r in rows),
                "after_no": sum(r["scores"]["retried_after_non_retryable"] for r in rows),
                "fixed": sum(r["scores"]["corrected_after_non_retryable"] > 0 for r in rows),
                "empty_repeat": sum(r["scores"]["empty_query_repeated"] > 0 for r in rows),
                "runaway": sum(r["scores"]["runaway"] for r in rows),
                "leaks": sum(bool(r["scores"]["leaked_terms"]) for r in rows),
                "partial_kept": sum(r["scores"]["partial_result_kept"] for r in rows),
            }
            print(
                f"  {name:9} avg_calls={agg['calls']:.1f} avg_retry_same={agg['retry_same']:.1f} "
                f"retry_other={agg['retry_other']} retried_after_no={agg['after_no']} "
                f"fixed_args={agg['fixed']}/{n} "
                f"empty_repeated={agg['empty_repeat']}/{n} runaway={agg['runaway']}/{n} "
                f"leaks={agg['leaks']}/{n} partial_kept={agg['partial_kept']}/{n}"
            )

    hooked = sum(r["scores"]["model_set_failure_mode"] for r in records)
    print(f"\nprediction 5 — model set failure_mode itself: {hooked} of {len(records)} runs")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if args and args[0] == "selftest":
        return selftest()

    if selftest() != 0:
        return 1

    chosen = [VARIANTS[a] for a in args] if args else list(VARIANTS.values())
    return measure(chosen)


if __name__ == "__main__":
    sys.exit(main())
