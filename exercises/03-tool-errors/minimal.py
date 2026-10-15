"""The error contract with nothing else in it (exercise 03 / AI-7).

One idea only: a tool has **three** outcomes, and the model must be able to tell
them apart structurally — not by the wording of a sentence.

    ok     -> is_error=false, content is a result
    empty  -> is_error=false, content is a result that happens to be empty
    error  -> is_error=true,  content is an error payload; there is no result

`is_error` says *how to read the content*. The category says *what to do next*,
so it lives in the body: one bit cannot distinguish "retry" from "ask a human".

Deliberately NOT here (that is `errors.py`): retry budget, backoff, business
rules, the comparison runs. Note what their absence costs — with a transient
failure that never heals, nothing stops the model from retrying except
MAX_ITERATIONS, which is a fuse, not a decision.

Run: python exercises/03-tool-errors/minimal.py [scenario ...]
"""

from __future__ import annotations

import ast
import json
import operator
import re
import sys

import anthropic
from dotenv import load_dotenv

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 1024
MAX_ITERATIONS = 6  # fuse only — see the module docstring

# --- 1. The three outcome shapes -------------------------------------------
# Every tool returns (content_json, is_error). The tool layer decides both; the
# model only reads them.

def ok(**fields) -> tuple[str, bool]:
    return json.dumps({"result_count": 1, **fields}), False


def empty(message: str) -> tuple[str, bool]:
    # The query ran. Finding nothing IS the answer, so is_error stays false.
    # `result_count` + an explicit message make it an assertion; a bare `[]`
    # would be an absence, and an absence invites a pointless retry.
    return json.dumps({"result_count": 0, "results": [], "message": message}), False


def failure(category: str, is_retryable: bool, message: str) -> tuple[str, bool]:
    return json.dumps(
        {
            "error_category": category,
            "is_retryable": is_retryable,
            "message": message,
        }
    ), True


# --- 2. The data tool: all three outcomes live here ------------------------

BOOKINGS = {
    "ABC123": {"reference": "ABC123", "owner": "me", "route": "LIS -> BER", "date": "2026-11-03"},
    "XYZ789": {"reference": "XYZ789", "owner": "someone-else", "route": "BER -> TLL", "date": "2026-12-20"},
}

REFERENCE_FORMAT = re.compile(r"^[A-Z]{3}[0-9]{3}$")


def lookup_booking(reference: str, failure_mode: str | None = None) -> tuple[str, bool]:
    if failure_mode == "timeout":
        # Transient: the query never ran. Retrying the same call can work.
        return failure("transient", True, "Booking service timed out. The query did not run.")

    if not REFERENCE_FORMAT.match(reference):
        # Validation: retrying as-is cannot help; the arguments must change.
        return failure(
            "validation",
            False,
            f"Reference {reference!r} is malformed. Expected 3 letters + 3 digits, e.g. ABC123.",
        )

    booking = BOOKINGS.get(reference)

    if booking is None:
        # Not an error: a well-formed reference that matches nothing.
        return empty(f"Query executed successfully. No booking matches reference {reference}.")

    if booking["owner"] != "me":
        # Permission: the row exists, the caller may not see it. Never retryable.
        return failure(
            "permission",
            False,
            f"Booking {reference} belongs to another traveller. Access requires their authorisation.",
        )

    return ok(results=[booking])


# --- 3. The working tool, reused from 02/01 --------------------------------
# Its job in this exercise: prove that one failing tool does not kill the run.

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


def calculate(expression: str) -> tuple[str, bool]:
    # Never eval() model-generated text: that is arbitrary code execution
    # driven by a prompt.
    try:
        return ok(expression=expression, result=_eval(ast.parse(expression.replace(",", ""), mode="eval").body))
    except (SyntaxError, ValueError) as exc:
        return failure("validation", False, f"Could not evaluate {expression!r}: {exc}")


# --- 4. What the model sees ------------------------------------------------

TOOLS = [
    {
        "name": "lookup_booking",
        "description": (
            "Look up a travel booking by its reference in the bookings database. "
            "Returns the booking when found, or result_count 0 when the reference "
            "matches nothing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Booking reference: 3 letters + 3 digits, e.g. ABC123.",
                },
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
        "name": "calculate",
        "description": (
            "Evaluate an arithmetic expression over plain numbers and return the "
            "exact result. Supports + - * / and parentheses. Numbers only — no "
            "units, no currency symbols."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "e.g. '(240 * 3) / 4'"}},
            "required": ["expression"],
        },
    },
]

REGISTRY = {"lookup_booking": lookup_booking, "calculate": calculate}

# How to read the contract. Precedence is stated because the model will
# otherwise pick for itself which field wins.
SYSTEM = (
    "You are a travel assistant with tools.\n"
    "A tool result marked is_error carries a JSON error payload, not data.\n"
    "Act on its fields: is_retryable is authoritative — when it is false, do not "
    "call that tool again; take another path or tell the user what they must do.\n"
    "error_category tells you which path: transient = retry the same call; "
    "validation = correct the arguments; business = a human must decide; "
    "permission = the user must obtain access.\n"
    "A result with result_count 0 is NOT an error: the query ran and matched "
    "nothing. That is the answer — never retry it.\n"
    "If one tool fails, still report everything the other tools did produce.\n"
    "Never mention tool names, error categories or internal field names to the user."
)


# --- 5. The loop -----------------------------------------------------------

SCENARIOS = {
    "ok": "Find my booking ABC123 and tell me the route.",
    "empty": "What is in my booking QQQ111?",
    "validation": "Look up booking number 12345.",
    "permission": "Show me the details of booking XYZ789.",
    "transient": "Find booking ABC123 — use failure_mode 'timeout' to simulate an outage.",
    "composite": "Find my booking ABC123, and also compute 3 nights at 240 per night.",
}


def run(label: str, question: str, client: anthropic.Anthropic) -> None:
    print(f"\n{'=' * 70}\n{label}: {question}\n{'=' * 70}")
    messages: list[dict] = [{"role": "user", "content": question}]

    for turn in range(1, MAX_ITERATIONS + 1):
        response = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM, tools=TOOLS, messages=messages
        )
        print(f"\n-- turn {turn} (stop_reason={response.stop_reason})")

        if response.stop_reason != "tool_use":
            text = next((b.text for b in response.content if b.type == "text"), "")
            print(f"   final: {text}")
            return

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"   calls  {block.name}({json.dumps(block.input)})")
            try:
                content, is_error = REGISTRY[block.name](**block.input)
            except TypeError as exc:
                # The model invented an argument. Tell it; do not crash the run.
                content, is_error = failure("validation", False, f"Invalid arguments: {exc}")
            print(f"   {'ERROR ' if is_error else 'result'} {content}")
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})

    print(f"\n   ! hit MAX_ITERATIONS={MAX_ITERATIONS} without end_turn — a runaway, not a result")


def main() -> int:
    load_dotenv()
    wanted = sys.argv[1:] or list(SCENARIOS)
    client = anthropic.Anthropic()
    for label in wanted:
        if label not in SCENARIOS:
            print(f"unknown scenario {label!r}; available: {', '.join(SCENARIOS)}", file=sys.stderr)
            return 1
        run(label, SCENARIOS[label], client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
