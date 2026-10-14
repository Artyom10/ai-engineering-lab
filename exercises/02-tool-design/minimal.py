"""Routing measurement with nothing else in it.

One API call per prompt. We never execute a tool: all we want is the model's
*decision*, which lives in the tool_use blocks of its very first reply.

Descriptions here are deliberately vague — this is the "before" measurement.

Run: python exercises/02-tool-design/minimal.py
"""

import anthropic
from dotenv import load_dotenv

# --- 1. What the model sees: name + description + input_schema. Nothing else.

TOOLS = [
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

# --- 2. The test set: prompt + the tool I claim is correct -----------------

CASES = [
    ("How many hours are in 3 days?", "convert_units"),
    ("How many weeks is 90 days?", "convert_units"),
    ("How many days from 2026-01-01 to 2026-03-15?", "date_difference"),
    ("How many hours between 9:00 and 17:30?", "calculate"),
    ("Convert 5 km to miles", "convert_units"),
    ("What is 5 km to miles times 3?", "calculate"),
    ("What is 250 dollars minus 20 percent?", "calculate"),
]

# --- 3. Ask once per prompt, record the choice ------------------------------

load_dotenv()
client = anthropic.Anthropic()

correct = 0
for prompt, expected in CASES:
    response = client.messages.create(
        model="claude-haiku-5-5",
        max_tokens=1024,
        tools=TOOLS,
        messages=[{"role": "user", "content": prompt}],
    )
    chosen = [b.name for b in response.content if b.type == "tool_use"]
    actual = chosen[0] if chosen else "<no tool>"
    ok = actual == expected
    correct += ok
    print(f"{'ok ' if ok else 'BAD'} {prompt}")
    print(f"      expected {expected}, got {actual}  (stop_reason={response.stop_reason})")

print(f"\nrouting accuracy: {correct}/{len(CASES)}")
