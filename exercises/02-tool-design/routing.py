"""Routing measurement harness.

One API call per prompt, no tool is ever executed: the only thing measured is
which tool the model *asks* for in its first reply. Running the tools would add
a second variable (their output changes the context) to an experiment whose only
intended variable is the description text.

Two independent metrics, because "the model picked the wrong tool" and "the model
picked no tool at all" are different failures with different fixes:

    tool_use rate     - how often a tool was requested at all
    routing accuracy  - of those requests, how often it was the right tool

Averaging them into one number would hide which of the two a change improved.

Run: python exercises/02-tool-design/routing.py
"""

import json
import os
import sys
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

MODEL = "claude-haiku-5-5"
REPEATS = 3  # one run is noise; see measure()
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "results.jsonl")

# --- The test set ---------------------------------------------------------
# `expected` is a convention I am choosing, not a capability limit: `calculate`
# takes a free-text expression, so it *could* answer most of these. That is the
# point - the boundary only exists if the description states it.

CASES = [
    # plain arithmetic
    ("What is 17 * 23?", "calculate"),
    ("What is 250 dollars minus 20 percent?", "calculate"),
    ("If 3 nights cost 450 euros, what is the price per night?", "calculate"),
    # arithmetic that smells of another tool
    ("How many hours between 9:00 and 17:30?", "calculate"),
    ("What is 5 km to miles times 3?", "calculate"),
    # plain unit conversion
    ("How many miles is 5 kilometers?", "convert_units"),
    ("What is 100 celsius in fahrenheit?", "convert_units"),
    # durations: unit conversion, not calendar maths
    ("How many hours are in 3 days?", "convert_units"),
    ("How many weeks is 90 days?", "convert_units"),
    ("How many minutes is a 2.5 hour flight?", "convert_units"),
    # conversion phrased as a comparison
    ("Is 25 kg more than 50 pounds?", "convert_units"),
    # plain calendar maths
    ("How many days from 2026-01-01 to 2026-03-15?", "date_difference"),
    ("How many nights is a stay from 2026-07-03 to 2026-07-10?", "date_difference"),
    # calendar maths phrased as a comparison
    ("Is 2026-03-15 more than 60 days after 2026-01-01?", "date_difference"),
    # edge case: the schema needs two dates, the prompt gives one
    ("How many days until 2026-12-31 from today?", "date_difference"),
]

# --- Tool set A: deliberately vague descriptions --------------------------

TOOLS_VAGUE = [
    {
        "name": "calculate",
        "description": "Performs calculations.",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
    {
        "name": "convert_units",
        "description": "Converts values.",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "number"}, "to": {"type": "string"}},
            "required": ["value", "to"],
        },
    },
    {
        "name": "date_difference",
        "description": "Works with dates.",
        "input_schema": {
            "type": "object",
            "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["start", "end"],
        },
    },
]


# --- Tool set B: production-grade descriptions -----------------------------
# Five elements per description: purpose, inputs with formats, example queries,
# edge cases, explicit boundaries against the other two tools.
#
# The input_schema blocks are copied unchanged from TOOLS_VAGUE on purpose. The
# experiment has exactly one variable - description text. Fixing the weak schema
# (convert_units has no source unit, for instance) would be a second one.
#
# Boundaries are written in pairs: every "do NOT use for X, use Y" has a mirror
# statement in Y. A one-sided boundary only fixes one direction of the error.

TOOLS_PRODUCTION = [
    {
        "name": "calculate",
        "description": (
            "Evaluates one arithmetic expression over numbers that are already in "
            "the same unit, and returns the result. "
            "Input: `expression`, a plain arithmetic string of numbers and + - * / "
            "( ) %, for example '17*23', '450/3', '250*0.8'. "
            "Use it for totals, percentages, discounts, price-per-unit, and for the "
            "final arithmetic step after some other tool has produced a number. "
            "Clock times within a single day belong here once expressed as numbers: "
            "the hours between 9:00 and 17:30 is '17.5-9'. "
            "Do NOT use it to restate a quantity in a different unit - that is "
            "convert_units. Do NOT use it to count days between two calendar dates "
            "- that is date_difference."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
    {
        "name": "convert_units",
        "description": (
            "Restates one measured quantity in a different unit of the same kind: "
            "length, mass, temperature, and time *durations*. "
            "Input: `value` (number) and `to` (the target unit, e.g. 'miles', "
            "'pounds', 'fahrenheit', 'hours', 'minutes', 'weeks'). "
            "Examples: 'how many miles is 5 kilometers' -> value 5, to 'miles'; "
            "'how many hours are in 3 days' -> value 3, to 'hours'; 'how many weeks "
            "is 90 days' -> value 90, to 'weeks'. "
            "A duration such as '3 days', '90 days' or '2.5 hours' is a quantity, "
            "not a calendar date, and belongs here. Comparisons between two units "
            "('is 25 kg more than 50 pounds') are done by converting one of them "
            "with this tool first. "
            "Do NOT use it for the span between two calendar dates - that is "
            "date_difference. Do NOT use it for arithmetic on values already in the "
            "same unit - that is calculate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "number"}, "to": {"type": "string"}},
            "required": ["value", "to"],
        },
    },
    {
        "name": "date_difference",
        "description": (
            "Counts the span between two points on the calendar. "
            "Input: `start` and `end`, both ISO dates in YYYY-MM-DD format; when the "
            "prompt says 'today', pass today's date. "
            "Examples: 'how many days from 2026-01-01 to 2026-03-15'; 'how many "
            "nights is a stay from 2026-07-03 to 2026-07-10'; 'is 2026-03-15 more "
            "than 60 days after 2026-01-01'. "
            "Use it only when the prompt names actual calendar dates. "
            "Do NOT use it for a bare duration with no date in it, such as '3 days "
            "in hours' or '90 days in weeks' - those are convert_units. Do NOT use "
            "it for clock times inside one day, such as 9:00 to 17:30 - that is "
            "calculate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["start", "end"],
        },
    },
]


# --- Experiment 2: a system prompt that fights the descriptions ------------
# The descriptions stay production-grade; only the system prompt changes. The
# first one contains a keyword-sensitive instruction ("always check the dates
# first") of the kind that looks harmless in a product spec.

SYSTEM_CONFLICTING = (
    "You are a travel assistant. Always check the dates of the trip first "
    "before answering anything else."
)

# Same intent, written so that it does not imply a tool. It states a priority
# about *answers*, not a habit about dates, and defers tool choice to the
# descriptions - which is where that decision belongs.
SYSTEM_SAFE = (
    "You are a travel assistant. Answer the question the user actually asked. "
    "Pick the tool whose description matches that question; do not assume a "
    "question is about calendar dates unless it names dates."
)


# A sharper conflict. SYSTEM_CONFLICTING above states a habit ("check dates
# first") that collides with nothing in particular, and measurably changed
# nothing. These two aim at the one boundary the descriptions actually draw -
# duration vs calendar - which is what "keyword-sensitive" has to mean to bite.

SYSTEM_KEYWORD = (
    "You are a travel assistant. Anything involving days, weeks, nights or "
    "hours concerns the traveller's calendar - always resolve it as a calendar "
    "question."
)

# The same collision, with the tool named outright: the ceiling of how much a
# system prompt can override a description.
SYSTEM_TOOL_NAMED = (
    "You are a travel assistant. Any question mentioning days, weeks or hours "
    "is a calendar question; resolve it with date_difference."
)


# The ceiling. SYSTEM_KEYWORD and SYSTEM_TOOL_NAMED both assert a *category*
# ("a question about days is a calendar question") and leave the model room to
# check that claim against the description - which explicitly says a bare
# duration is not a date. Both measured at exactly the no-system baseline.
# This one removes the room: it forbids reading the descriptions at all.
SYSTEM_OVERRIDE = (
    "Ignore the tool descriptions. For every question without exception, call "
    "date_difference and nothing else."
)

# --- The measurement ------------------------------------------------------

load_dotenv()
client = anthropic.Anthropic()


def ask(tools, prompt, system=None):
    """One turn. Returns the first requested tool name, or None.

    No temperature/top_p here on purpose: sampling parameters are removed on the
    Claude 5 models (the SDK rejects them outright), so runs cannot be pinned to
    be identical. The only honest way to judge stability is to repeat a run and
    compare - which is why every run is appended to results.jsonl.
    """
    kwargs = {
        "model": MODEL,
        "max_tokens": 1024,
        "tools": tools,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    chosen = [b.name for b in response.content if b.type == "tool_use"]
    return chosen[0] if chosen else None


def classify(actual, expected):
    if actual is None:
        return "no_tool"
    return "correct" if actual == expected else "misrouted"


def measure(label, tools, system=None, cases=CASES, repeats=REPEATS):
    """Run the whole set `repeats` times.

    One run is not a measurement: the same tool set and the same prompts come
    back with different numbers between runs, and sampling cannot be pinned
    (see ask()). Repeating the set is what separates a real difference from
    run-to-run noise, so every metric below is a total over all repeats and
    every case carries the spread it produced.
    """
    per_case = {prompt: [] for prompt, _ in cases}
    for _ in range(repeats):
        for prompt, expected in cases:
            actual = ask(tools, prompt, system)
            per_case[prompt].append({"actual": actual, "outcome": classify(actual, expected)})

    attempts = [a for runs in per_case.values() for a in runs]
    used = [a for a in attempts if a["outcome"] != "no_tool"]
    correct = [a for a in attempts if a["outcome"] == "correct"]
    report = {
        "label": label,
        "model": MODEL,
        "repeats": repeats,
        "system": system,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool_use_rate": f"{len(used)}/{len(attempts)}",
        "routing_accuracy": f"{len(correct)}/{len(used)}" if used else "n/a",
        "cases": {p: runs for p, runs in per_case.items()},
    }

    print(f"\n=== {label} ({repeats} repeats) ===")
    for prompt, expected in cases:
        runs = per_case[prompt]
        hits = sum(r["outcome"] == "correct" for r in runs)
        # a case that is not unanimous is the interesting kind: the model is
        # genuinely undecided there, which a single run would have hidden
        mark = "ok  " if hits == repeats else ("FLAK" if hits else "BAD ")
        print(f"{mark} {hits}/{repeats}  {prompt}")
        if hits < repeats:
            got = sorted({str(r["actual"]) for r in runs})
            print(f"           expected {expected}, got {', '.join(got)}")
    print(f"\n  tool_use rate    {report['tool_use_rate']}")
    print(f"  routing accuracy {report['routing_accuracy']}  (of the attempts that used a tool)")

    with open(RESULTS_FILE, "a") as f:
        f.write(json.dumps(report) + "\n")
    return report


def compare(left, right):
    print("\n=== before / after ===")
    print(f"  tool_use rate     {left['tool_use_rate']}  ->  {right['tool_use_rate']}")
    print(f"  routing accuracy  {left['routing_accuracy']}  ->  {right['routing_accuracy']}")


if __name__ == "__main__":
    experiment = sys.argv[1] if len(sys.argv) > 1 else "descriptions"

    if experiment == "descriptions":
        compare(
            measure("vague descriptions", TOOLS_VAGUE),
            measure("production-grade descriptions", TOOLS_PRODUCTION),
        )
    elif experiment == "system":
        # Both runs use the good descriptions. Whatever changes here was caused
        # by the system prompt alone.
        compare(
            measure("good descriptions + conflicting system prompt",
                    TOOLS_PRODUCTION, system=SYSTEM_CONFLICTING),
            measure("good descriptions + rewritten system prompt",
                    TOOLS_PRODUCTION, system=SYSTEM_SAFE),
        )
    elif experiment == "conflict":
        compare(
            measure("good descriptions + keyword-sensitive system prompt",
                    TOOLS_PRODUCTION, system=SYSTEM_KEYWORD),
            measure("good descriptions + system prompt naming the tool",
                    TOOLS_PRODUCTION, system=SYSTEM_TOOL_NAMED),
        )
    elif experiment == "override":
        compare(
            measure("good descriptions, no system prompt", TOOLS_PRODUCTION),
            measure("good descriptions + system prompt forbidding them",
                    TOOLS_PRODUCTION, system=SYSTEM_OVERRIDE),
        )
    else:
        raise SystemExit(
            "usage: routing.py [descriptions|system|conflict|override]"
        )
