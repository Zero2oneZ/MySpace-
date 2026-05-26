#!/usr/bin/env python3
"""Unit tests for chain.py parser. Runs without ollama or any network."""

import os
import sys
from pathlib import Path

# Locate chain.py via $CC_INSTALL_ROOT/lib/chain.py if set, else relative.
here = Path(__file__).resolve().parent
chain_lib = Path(os.environ.get("CC_INSTALL_ROOT", here.parent)) / "lib" / "chain.py"
if not chain_lib.exists():
    print(f"chain.py not found at {chain_lib}", file=sys.stderr)
    sys.exit(2)

# Load chain.py as a module without executing main(). Register in
# sys.modules first so dataclass forward-references (e.g. 'Expr') resolve.
import importlib.util
spec = importlib.util.spec_from_file_location("chain", chain_lib)
chain = importlib.util.module_from_spec(spec)
sys.modules["chain"] = chain
spec.loader.exec_module(chain)

PASS = 0
FAIL = 0


def pass_(name):
    global PASS
    PASS += 1
    print(f"  PASS: {name}")


def fail_(name, detail=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL: {name}")
    if detail:
        print(f"        {detail}")


def expect_steps(spec_text, expected_step_texts, name):
    try:
        expr = chain.parse(spec_text)
    except Exception as e:
        fail_(name, f"parse error: {e}")
        return
    actual = []

    def walk(node):
        if isinstance(node, chain.Step):
            actual.append(node.text)
        elif isinstance(node, chain.Group):
            walk(node.expr)
        elif isinstance(node, chain.Expr):
            for t in node.terms:
                walk(t)

    walk(expr)
    if actual == expected_step_texts:
        pass_(name)
    else:
        fail_(name, f"expected {expected_step_texts}, got {actual}")


def expect_ops(spec_text, expected_ops, name):
    try:
        expr = chain.parse(spec_text)
    except Exception as e:
        fail_(name, f"parse error: {e}")
        return
    # Collect ops from top-level Expr only (not from nested groups)
    if expr.ops == expected_ops:
        pass_(name)
    else:
        fail_(name, f"expected ops {expected_ops}, got {expr.ops}")


def expect_parse_error(spec_text, name):
    try:
        chain.parse(spec_text)
        fail_(name, "expected ChainParseError, parse succeeded")
    except chain.ChainParseError:
        pass_(name)
    except Exception as e:
        fail_(name, f"wrong exception type: {type(e).__name__}: {e}")


def expect_isolated(spec_text, name):
    """Verify there's at least one isolated cc-group somewhere in the tree."""
    try:
        expr = chain.parse(spec_text)
    except Exception as e:
        fail_(name, f"parse error: {e}")
        return
    found = [False]

    def walk(node):
        if isinstance(node, chain.Group):
            if node.isolated:
                found[0] = True
            walk(node.expr)
        elif isinstance(node, chain.Expr):
            for t in node.terms:
                walk(t)

    walk(expr)
    if found[0]:
        pass_(name)
    else:
        fail_(name, "no isolated (cc-) group found")


print("=== chain parser tests ===\n")

# Leaf step
expect_steps('{"hello"}', ["hello"], "single step")
expect_steps('  {"trim ok"}  ', ["trim ok"], "whitespace tolerance")

# Top-level wrapper braces
expect_steps('{{"A"} | {"B"}}', ["A", "B"], "outer wrapper { }")
expect_steps('{"A"} | {"B"}', ["A", "B"], "no outer wrapper")
expect_ops('{"A"} | {"B"}', ["|"], "single pipe op")

# Three operators
expect_steps('{"A"} | {"B"} + {"C"} - {"D"}', ["A", "B", "C", "D"], "mixed ops")
expect_ops('{"A"} | {"B"} + {"C"} - {"D"}', ["|", "+", "-"], "mixed ops ordering")

# Nested groups
expect_steps('{{"A"} | {{"B"} + {"C"}}}', ["A", "B", "C"], "nested group")

# Isolated cc-group
expect_isolated('{{"A"} | cc {{"B"} | {"C"}}}', "cc-group detected as isolated")
expect_steps('{{"A"} | cc {{"B"} | {"C"}}}', ["A", "B", "C"], "cc-group steps")

# Escapes in strings
expect_steps(r'{"hello \"world\""}', ['hello "world"'], "escaped quotes")
expect_steps(r'{"path\\to\\file"}', [r"path\to\file"], "escaped backslashes")

# Long prompt (the user's headline use case)
long_prompt = "Please write a detailed essay covering at least 500 words on the topic of deterministic AI agents. Include three distinct sections and a conclusion."
expect_steps(
    '{{"' + long_prompt + '"} | {"now translate that essay to French preserving structure"}}',
    [long_prompt, "now translate that essay to French preserving structure"],
    "long paragraph prompt",
)

# Parse errors
expect_parse_error('', "empty input is an error")
expect_parse_error('{"unterminated', "unterminated string")
expect_parse_error('{"A"} |', "operator without trailing term")
expect_parse_error('{"A"} {"B"}', "two adjacent steps without operator")

# cc{step} is documented permissive — it wraps the leaf in a trivial group.
# Just confirm it parses without error.
try:
    chain.parse('cc {"only"}')
    pass_("cc {step} is permissive (parsed)")
except chain.ChainParseError as err:
    fail_("cc {step} is permissive (parsed)", f"got error: {err}")

# Dry-run plan generation must not raise
try:
    plan = chain.render_plan(chain.parse('{{"A"} | {"B"} + cc {{"C"} | {"D"}}}'))
    if len(plan) > 0:
        pass_("render_plan produces output")
    else:
        fail_("render_plan output empty")
except Exception as e:
    fail_("render_plan raised", str(e))

print()
print("=================================")
print(f"  chain parser: {PASS} pass / {FAIL} fail")
print("=================================")
sys.exit(0 if FAIL == 0 else 1)
