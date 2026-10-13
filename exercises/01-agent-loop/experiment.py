"""Experiment: when does a tool actually earn its place?

Same loop as minimal.py (copied on purpose, so this file reads standalone),
but the `multiply` tool can be switched off. Two tools, two different reasons
to exist:

  get_stock  -> the model CANNOT know this; the data lives in our process
  multiply   -> the model CAN do this itself; the tool buys determinism

Switching `multiply` off shows the model doing the arithmetic in-head: one
iteration fewer, a number you cannot verify or reproduce.

    # tool available -> exact, traceable
    python exercises/01-agent-loop/experiment.py

    # no tool -> model computes it itself
    python exercises/01-agent-loop/experiment.py --no-multiply

    # harder numbers, no thinking: correctness starts depending on
    # a request parameter rather than on the task
    python exercises/01-agent-loop/experiment.py --no-multiply --no-thinking \
        --stock 48731 --price 1.7349617
"""

import argparse
import sys

import anthropic
from dotenv import load_dotenv

MODEL = "claude-haiku-5-5"


def get_stock(item, stock):
    return str(stock.get(item, 0))


def multiply(a, b):
    return str(a * b)


GET_STOCK_SCHEMA = {
    "name": "get_stock",
    "description": "How many units of an item are in the warehouse.",
    "input_schema": {
        "type": "object",
        "properties": {"item": {"type": "string"}},
        "required": ["item"],
    },
}

MULTIPLY_SCHEMA = {
    "name": "multiply",
    "description": "Multiply two numbers.",
    "input_schema": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-multiply", action="store_true", help="hide the multiply tool")
    parser.add_argument("--no-thinking", action="store_true", help="disable adaptive thinking")
    parser.add_argument("--stock", type=int, default=4873, help="apples in stock")
    parser.add_argument("--price", type=float, default=1.7349, help="price per apple")
    return parser.parse_args()


def main():
    args = parse_args()
    load_dotenv()

    stock = {"apples": args.stock}
    funcs = {
        "get_stock": lambda item: get_stock(item, stock),
        "multiply": multiply,
    }
    tools = [GET_STOCK_SCHEMA]
    if not args.no_multiply:
        tools.append(MULTIPLY_SCHEMA)

    # Haiku runs adaptive thinking by default; disabling it is allowed at
    # effort "high" or below. Thinking depth changes how reliable in-head
    # arithmetic is — which is the point of the --no-thinking run.
    extra = {"thinking": {"type": "disabled"}} if args.no_thinking else {}

    question = (
        f"How much do all the apples in stock cost at {args.price} each? "
        "Give the exact total."
    )
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]

    print(f"tools    = {[t['name'] for t in tools]}")
    print(f"thinking = {'disabled' if args.no_thinking else 'adaptive (default)'}")

    iterations = 0
    while True:
        iterations += 1
        response = client.messages.create(
            model=MODEL, max_tokens=1024, tools=tools, messages=messages, **extra
        )
        print(f"turn {iterations}: stop_reason = {response.stop_reason}")

        if response.stop_reason != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output = funcs[block.name](**block.input)
            print(f"  -> {block.name}({block.input})  <- {output}")
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": output}
            )
        messages.append({"role": "user", "content": results})

    answer = next((b.text for b in response.content if b.type == "text"), "")
    exact = args.stock * args.price
    print(f"\nanswer: {answer}")
    print(f"exact : {exact}")
    print(f"exact value present in answer: {f'{exact:,}' in answer or str(exact) in answer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
