"""The agent loop with nothing else in it.

Same concept as main.py, stripped down: no safe expression parser, no error
handling, no trace formatting. Read this first, then diff it against main.py.

Run: python exercises/01-agent-loop/minimal.py
"""

import anthropic
from dotenv import load_dotenv

# --- 1. The tools: ordinary Python functions ------------------------------

STOCK = {"apples": 12, "pears": 40}


def get_stock(item):
    return str(STOCK.get(item, 0))


def multiply(a, b):
    return str(a * b)


TOOL_FUNCS = {"get_stock": get_stock, "multiply": multiply}

# --- 2. What the model sees about them ------------------------------------

TOOLS = [
    {
        "name": "get_stock",
        "description": "How many units of an item are in the warehouse.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
        },
    },
    {
        "name": "multiply",
        "description": "Multiply two numbers.",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
]

# --- 3. The loop ----------------------------------------------------------

load_dotenv()
client = anthropic.Anthropic()

messages = [{"role": "user", "content": "How much do all the apples in stock cost at 1.75 each?"}]

while True:
    response = client.messages.create(
        model="claude-haiku-5-5",
        max_tokens=1024,
        tools=TOOLS,
        messages=messages,
    )
    print(f"stop_reason = {response.stop_reason}")

    if response.stop_reason != "tool_use":
        break

    messages.append({"role": "assistant", "content": response.content})

    results = []
    for block in response.content:
        if block.type == "tool_use":
            print(f"  -> {block.name}({block.input})")
            output = TOOL_FUNCS[block.name](**block.input)
            print(f"  <- {output}")
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": output}
            )

    messages.append({"role": "user", "content": results})

print([b.text for b in response.content if b.type == "text"][0])
