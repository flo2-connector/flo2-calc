"""The computation graph: how it is written, how it is read, how it is evaluated.

A GRAPH is a list of named nodes and, optionally, which one is the result
(the last node when it is not named):

    {"nodes": [
       {"id": "cavity", "value": "2 mm", "source": {"design_node": "con:cavity-depth"}},
       {"id": "bend", "value": "1.4 mm", "source": "fiber datasheet, minimum bend radius"},
       {"id": "margin", "op": "sub", "args": ["cavity", "bend"]},
       {"id": "needed", "value": "0.5 mm", "source": "assumed"},
       {"id": "fits", "op": "ge", "args": ["margin", "needed"]}],
     "result": "fits"}

An INPUT node has a `value`: a number with its unit as text ("1.4 mm"), a
plain number ("0.1", or a JSON integer), or true/false. Its `source` says
where the value came from: free text, or {"design_node": "<id>"} naming a node
in a reflow2 design (with "design": "<design id>" when it is another design).
flo2-calc records a source and never resolves it. An exchange rate (a value
whose unit holds two currencies, "0.92 EUR/USD") must have one: flo2-calc
holds no rates, so the rate is the caller's, and must say where it came from.
A value is one number: text that holds arithmetic ("3 + 4") is refused as an
expression, to be built as nodes.

An OPERATION node has an `op` and `args`, the ids of the nodes it takes, in
order. `convert` also takes the `unit` to convert to. Any node may carry a
free-text `note`.

READING. A graph that cannot be read is a CallError naming the field: no
nodes, a repeated id, an unknown operator or field, the wrong number of
arguments, a reference to a node that is not there, a cycle, a value that is
not a number, an unknown unit, an expression typed as a value, an exchange
rate with no source.

EVALUATING. Nodes are evaluated in one fixed order: each as soon as every node
it takes is done, ties broken by the order they are listed in. The first node
that cannot be computed stops the evaluation with a Refusal naming that node,
its operation and why. Every value computed before it is still reported.
The whole-graph path and the node-by-node path (add_node) both end here, in
`evaluate`, which is why they give the same result.

LIMITS. `evaluate` runs under a limits.Guard, the host's limits for one call:
the deadline is checked before every node and after every step of an
operation with many arguments; every input, partial result and value is held
to the digits budget; a power is sized before it is computed. Passing one
stops the evaluation like a refusal, of kind "exceeds_limits" (limits.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from flo2_calc import limits as L
from flo2_calc import temperature as T
from flo2_calc import units as U
from flo2_calc.errors import CallError, LimitExceeded, Refusal, at
from flo2_calc.numbers import (
    EXACT_FOR_THESE_INPUTS,
    MAX_NUMBER_TEXT,
    NUMBER_THEN_REST,
    expression_problem,
    format_number,
    looks_like_expression,
    parse_number,
)

MAX_NODES = 500
MAX_ARGS = 100
MAX_NOTE = 2000
MAX_POWER_ARG = 1000
ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class Quantity:
    magnitude: Fraction
    unit: U.Unit = U.PLAIN


Value = Quantity | bool


# (family, fewest args, most args or None for "any number up to MAX_ARGS"), and what it does
OPS: dict[str, tuple[str, int, int | None, str]] = {
    "add": ("arithmetic", 2, None, "the sum; every unit must measure the same thing, and the result is in the first one's unit"),
    "sub": ("arithmetic", 2, 2, "the first minus the second, in the first one's unit"),
    "mul": ("arithmetic", 2, None, "the product; units multiply (mm * mm is mm^2)"),
    "div": ("arithmetic", 2, 2, "the first divided by the second; units divide; division by zero is refused"),
    "neg": ("arithmetic", 1, 1, "minus the value"),
    "abs": ("arithmetic", 1, 1, "the absolute value"),
    "pow": ("arithmetic", 2, 2, "the first raised to the second, which must be a plain whole number"),
    "min": ("arithmetic", 2, None, "the smallest, in the first one's unit"),
    "max": ("arithmetic", 2, None, "the largest, in the first one's unit"),
    "convert": ("arithmetic", 1, 1, 'the value in the node\'s "unit" ("" for a plain number); it must measure the same thing'),
    "and": ("logic", 2, None, "true when every argument is true"),
    "or": ("logic", 2, None, "true when any argument is true"),
    "not": ("logic", 1, 1, "true when the argument is false"),
    "nand": ("logic", 2, None, "not and"),
    "nor": ("logic", 2, None, "not or"),
    "xor": ("logic", 2, None, "true when an odd number of arguments are true"),
    "eq": ("comparison", 2, 2, "equal (numbers after converting to the first one's unit, or two true/false values)"),
    "ne": ("comparison", 2, 2, "not equal"),
    "lt": ("comparison", 2, 2, "the first is less than the second"),
    "le": ("comparison", 2, 2, "the first is less than or equal to the second"),
    "gt": ("comparison", 2, 2, "the first is greater than the second"),
    "ge": ("comparison", 2, 2, "the first is greater than or equal to the second"),
}

INPUT_KEYS = ("id", "value", "source", "note")
OP_KEYS = ("id", "op", "args", "unit", "note")
GRAPH_KEYS = ("nodes", "result")
SOURCE_KEYS = ("design_node", "design")


@dataclass(frozen=True)
class InputNode:
    id: str
    raw: str  # the value's text as given (a JSON integer or true/false made text)
    value: Value
    source: str | dict[str, str] | None
    note: str | None


@dataclass(frozen=True)
class OpNode:
    id: str
    op: str
    args: tuple[str, ...]
    unit: U.Unit | None  # convert's target
    unit_text: str | None
    note: str | None


Node = InputNode | OpNode


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...]
    result: str
    result_named: bool  # whether the graph named its result (else: the last node)

    def by_id(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}

    def to_json(self) -> dict[str, Any]:
        """The graph as flo2-calc read it, every value as text: the form a
        record keeps and add_node hands back."""
        out: list[dict[str, Any]] = []
        for n in self.nodes:
            if isinstance(n, InputNode):
                d: dict[str, Any] = {"id": n.id, "value": n.raw}
                if n.source is not None:
                    d["source"] = n.source
            else:
                d = {"id": n.id, "op": n.op, "args": list(n.args)}
                if n.unit_text is not None:
                    d["unit"] = n.unit_text
            if n.note is not None:
                d["note"] = n.note
            out.append(d)
        g: dict[str, Any] = {"nodes": out}
        if self.result_named:
            g["result"] = self.result
        return g


@dataclass
class Evaluation:
    graph: Graph
    guard: L.Guard
    order: list[str] = field(default_factory=list)
    values: dict[str, Value] = field(default_factory=dict)
    refusal: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None

    @property
    def stopped(self) -> bool:
        """Stopped at one of the host's limits, rather than refused for a reason in the graph."""
        return self.refusal is not None and self.refusal.get("kind") == "exceeds_limits"

    def result_value(self) -> Value | None:
        return self.values.get(self.graph.result) if self.ok else None


# ---------------------------------------------------------------- values as text


def value_json(v: Value) -> dict[str, str]:
    """A value as replies and records write it: {"value": "0.3 mm"}, plus
    "exact" when the text is rounded: the exact value FOR THESE INPUTS (the
    inputs as written, no more accurate than they are)."""
    if isinstance(v, bool):
        return {"value": "true" if v else "false"}
    text, exact = format_number(v.magnitude)
    unit = U.format_unit(v.unit)
    out = {"value": f"{text} {unit}" if unit else text}
    if exact is not None:
        out["exact"] = f"{exact} {unit}" if unit else exact
    return out


def value_text(v: Value) -> str:
    return value_json(v)["value"]


def parse_value(raw: Any, path: str) -> tuple[str, Value]:
    """(the value's text, the value) from what a call gave."""
    if isinstance(raw, bool):
        return ("true" if raw else "false"), raw
    if isinstance(raw, int):
        if abs(raw) >= L.ten_to(MAX_NUMBER_TEXT):
            raise CallError(path, f"a number is at most {MAX_NUMBER_TEXT} digits; this JSON integer is longer.")
        return str(raw), Quantity(Fraction(raw))
    if isinstance(raw, float):
        if raw.is_integer() and abs(raw) < 2**53:
            return str(int(raw)), Quantity(Fraction(int(raw)))
        raise CallError(
            path,
            f"{raw!r} arrived as a JSON number with a fraction part, which reaches flo2-calc as a binary "
            f'floating-point number whose exact value is already lost. Write it as text: "{raw!r}".',
        )
    if not isinstance(raw, str):
        raise CallError(path, 'a value is text: a number with its unit ("1.4 mm"), a plain number ("0.1"), or true/false.')
    text = raw.strip()
    if text in ("true", "false"):
        return raw, text == "true"
    m = NUMBER_THEN_REST.match(text)
    if not m:
        if looks_like_expression(text, whole=True):  # "(3+4)", "pi*2"
            raise CallError(path, expression_problem(raw))
        raise CallError(
            path,
            f'"{raw}" is not a value: write a number with its unit ("1.4 mm"), a plain number ("0.1" or "1/3"), or true/false.',
        )
    if looks_like_expression(m.group(2)):  # "3 + * 4", "3*4", "2^10", "1/2/3", "2 1/2"
        raise CallError(path, expression_problem(raw))
    try:
        number = parse_number(m.group(1))
        unit = U.parse_unit(m.group(2))
    except ValueError as e:  # UnitTextError is a ValueError
        raise CallError(path, str(e)) from None
    return raw, Quantity(number, unit)


# ---------------------------------------------------------------- reading a graph


def _note(obj: dict[str, Any], path: str) -> str | None:
    if "note" not in obj:
        return None
    note = obj["note"]
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise CallError(at(path, "note"), f"a note is text of at most {MAX_NOTE} characters.")
    return note


def _source(obj: dict[str, Any], path: str) -> str | dict[str, str] | None:
    if "source" not in obj:
        return None
    src = obj["source"]
    p = at(path, "source")
    if isinstance(src, str):
        if not src.strip() or len(src) > MAX_NOTE:
            raise CallError(p, f"a source is free text (1 to {MAX_NOTE} characters) or {{\"design_node\": \"<id>\"}}.")
        return src
    if isinstance(src, dict):
        unknown = [k for k in src if k not in SOURCE_KEYS]
        if unknown:
            raise CallError(at(p, unknown[0]), 'a design source has only "design_node" and, for another design, "design".')
        dn = src.get("design_node")
        if not isinstance(dn, str) or not re.fullmatch(r"\S{1,200}", dn):
            raise CallError(at(p, "design_node"), 'name the design node by its id, e.g. "con:cavity-depth" (no spaces).')
        out = {"design_node": dn}
        if "design" in src:
            d = src["design"]
            if not isinstance(d, str) or not re.fullmatch(r"\S{1,200}", d):
                raise CallError(at(p, "design"), "name the design by its id, with no spaces.")
            out["design"] = d
        return out
    raise CallError(p, 'a source is free text, or {"design_node": "<id>"} naming a node in a reflow2 design.')


def _node(obj: Any, path: str) -> Node:
    if not isinstance(obj, dict):
        raise CallError(path, 'a node is an object: {"id", "value"} for an input, or {"id", "op", "args"} for an operation.')
    nid = obj.get("id")
    if not isinstance(nid, str) or not ID.match(nid):
        raise CallError(
            at(path, "id"),
            "every node has an id: a letter or _, then up to 63 letters, digits, _ . or -, e.g. \"bend_radius\".",
        )
    if "value" in obj and "op" in obj:
        raise CallError(path, f'node "{nid}" has both "value" and "op": an input has a value, an operation has an op.')
    if "value" in obj:
        unknown = [k for k in obj if k not in INPUT_KEYS]
        if unknown:
            raise CallError(at(path, unknown[0]), f"an input node has only {', '.join(INPUT_KEYS)}.")
        raw, value = parse_value(obj["value"], at(path, "value"))
        source = _source(obj, path)
        if source is None and isinstance(value, Quantity) and len(U.currencies_in(value.unit)) > 1:
            raise CallError(
                at(path, "source"),
                f'"{raw}" is an exchange rate, and an exchange rate must say where it came from and when: give it a '
                '"source", for example "ECB reference rate, 2026-10-02". flo2-calc holds no rates of its own.',
            )
        return InputNode(nid, raw, value, source, _note(obj, path))
    if "op" not in obj:
        raise CallError(path, f'node "{nid}" has neither "value" (an input) nor "op" (an operation).')
    unknown = [k for k in obj if k not in OP_KEYS]
    if unknown:
        raise CallError(at(path, unknown[0]), f"an operation node has only {', '.join(OP_KEYS)}.")
    op = obj["op"]
    if not isinstance(op, str) or op not in OPS:
        raise CallError(
            at(path, "op"),
            f"{op!r} is not an operator flo2-calc has. The first increment has arithmetic "
            f"({', '.join(k for k, v in OPS.items() if v[0] == 'arithmetic')}), logic "
            f"({', '.join(k for k, v in OPS.items() if v[0] == 'logic')}) and comparison "
            f"({', '.join(k for k, v in OPS.items() if v[0] == 'comparison')}). Set operations come later.",
        )
    args = obj.get("args")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise CallError(at(path, "args"), f'"{op}" takes "args": a list of the ids of the nodes it works on, in order.')
    _family, least, most, _what = OPS[op]
    most_n = MAX_ARGS if most is None else most
    if not least <= len(args) <= most_n:
        want = f"exactly {least}" if least == most else f"{least} to {most_n}"
        raise CallError(at(path, "args"), f'"{op}" takes {want} argument(s); this node gives {len(args)}.')
    unit = unit_text = None
    if op == "convert":
        if "unit" not in obj or not isinstance(obj["unit"], str):
            raise CallError(at(path, "unit"), 'convert needs "unit": the unit to convert to, e.g. "mm" ("" for a plain number).')
        unit_text = obj["unit"]
        try:
            unit = U.parse_unit(unit_text)
        except ValueError as e:
            raise CallError(at(path, "unit"), str(e)) from None
    elif "unit" in obj:
        raise CallError(at(path, "unit"), f'only convert takes a "unit"; "{op}" keeps the units of what it takes.')
    return OpNode(nid, op, tuple(args), unit, unit_text, _note(obj, path))


def read_nodes(items: list[tuple[Any, str]], result: Any = None, result_path: str = "graph.result") -> Graph:
    """A graph from (node, field path) pairs. Raises CallError."""
    if not items:
        raise CallError("graph.nodes", "a graph needs at least one node.")
    if len(items) > MAX_NODES:
        raise CallError("graph.nodes", f"a graph has at most {MAX_NODES} nodes; this one has {len(items)}.")
    nodes: list[Node] = []
    seen: dict[str, str] = {}
    for obj, path in items:
        node = _node(obj, path)
        if node.id in seen:
            raise CallError(at(path, "id"), f'"{node.id}" is already the id of {seen[node.id]}; every id names one node.')
        seen[node.id] = path
        nodes.append(node)
    ids = set(seen)
    for (_obj, path), node in zip(items, nodes, strict=True):
        if isinstance(node, OpNode):
            for i, a in enumerate(node.args):
                if a not in ids:
                    raise CallError(at(at(path, "args"), i), f'"{a}" is not the id of any node in this graph.')
    if result is None:
        named = False
        result_id = nodes[-1].id
    else:
        named = True
        if not isinstance(result, str) or result not in ids:
            raise CallError(result_path, f"{result!r} is not the id of any node in this graph.")
        result_id = result
    graph = Graph(tuple(nodes), result_id, named)
    evaluation_order(graph)  # refuses a cycle now, as a malformed call
    return graph


def read_graph(obj: Any, path: str = "graph") -> Graph:
    if not isinstance(obj, dict):
        raise CallError(path, 'a graph is an object: {"nodes": [...], "result": "<id>"}.')
    unknown = [k for k in obj if k not in GRAPH_KEYS]
    if unknown:
        raise CallError(at(path, unknown[0]), 'a graph has only "nodes" and, optionally, "result".')
    nodes = obj.get("nodes")
    if not isinstance(nodes, list):
        raise CallError(at(path, "nodes"), "a graph's nodes are a list.")
    return read_nodes([(n, at(at(path, "nodes"), i)) for i, n in enumerate(nodes)], obj.get("result"), at(path, "result"))


def evaluation_order(graph: Graph) -> list[str]:
    """Each node as soon as every node it takes is done, ties broken by list
    order. Raises CallError naming a cycle."""
    deps = {n.id: set(n.args) if isinstance(n, OpNode) else set() for n in graph.nodes}
    done: list[str] = []
    done_set: set[str] = set()
    remaining = [n.id for n in graph.nodes]
    while remaining:
        nxt = next((nid for nid in remaining if deps[nid] <= done_set), None)
        if nxt is None:
            raise CallError("graph.nodes", f"these nodes depend on each other in a cycle: {_a_cycle(deps, remaining)}.")
        remaining.remove(nxt)
        done.append(nxt)
        done_set.add(nxt)
    return done


def _a_cycle(deps: dict[str, set[str]], remaining: list[str]) -> str:
    left = set(remaining)
    start = remaining[0]
    path = [start]
    while True:
        here = path[-1]
        nxt = sorted(d for d in deps[here] if d in left)[0]
        if nxt in path:
            loop = path[path.index(nxt):] + [nxt]
            return " -> ".join(loop)
        path.append(nxt)


# ---------------------------------------------------------------- evaluating


def _numbers(op: str, args: list[Value], names: tuple[str, ...]) -> list[Quantity]:
    for a, name in zip(args, names, strict=True):
        if isinstance(a, bool):
            raise Refusal(
                f'{op} takes numbers, and "{name}" is {"true" if a else "false"}.',
                kind="type_mismatch",
            )
    return args  # type: ignore[return-value]


def _booleans(op: str, args: list[Value], names: tuple[str, ...]) -> list[bool]:
    for a, name in zip(args, names, strict=True):
        if not isinstance(a, bool):
            raise Refusal(
                f'{op} takes true/false values, and "{name}" is the number {value_text(a)}.',
                kind="type_mismatch",
            )
    return args  # type: ignore[return-value]


def _in_unit_of(first: Quantity, other: Quantity, op: str) -> Fraction:
    """`other`'s magnitude in `first`'s unit, exactly. Refuses a mismatch."""
    return other.magnitude * U.conversion(other.unit, first.unit, op)


def _apply(node: OpNode, args: list[Value], guard: L.Guard) -> Value:
    op, names = node.op, node.args
    family = OPS[op][0]
    if family == "logic":
        bs = _booleans(op, args, names)
        if op == "and":
            return all(bs)
        if op == "or":
            return any(bs)
        if op == "not":
            return not bs[0]
        if op == "nand":
            return not all(bs)
        if op == "nor":
            return not any(bs)
        return sum(bs) % 2 == 1  # xor
    if op in ("eq", "ne") and isinstance(args[0], bool) and isinstance(args[1], bool):
        return (args[0] == args[1]) if op == "eq" else (args[0] != args[1])
    if op in ("eq", "ne") and (isinstance(args[0], bool) != isinstance(args[1], bool)):
        raise Refusal(f"{op} compares like with like, and one of {names[0]!r}, {names[1]!r} is true/false and the other a number.", kind="type_mismatch")
    qs = _numbers(op, args, names)
    if T.involved(op, [q.unit for q in qs], node.unit):  # a temperature on degC or degF: temperature.py
        out = T.apply(op, [(q.magnitude, q.unit) for q in qs], names, node.unit)
        return out if isinstance(out, bool) else Quantity(*out)
    first = qs[0]
    if family == "comparison":
        a, b = first.magnitude, _in_unit_of(first, qs[1], op)
        return {"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]
    if op == "add":
        total = first.magnitude
        for i, q in enumerate(qs[1:], 2):  # step by step, each partial sum held to the budget
            total = total + _in_unit_of(first, q, op)
            guard.check_number(total, "sum" if i == len(qs) else f"partial sum (of the first {i} arguments)")
        return Quantity(total, first.unit)
    if op == "sub":
        return Quantity(first.magnitude - _in_unit_of(first, qs[1], op), first.unit)
    if op in ("min", "max"):
        mags = [first.magnitude] + [_in_unit_of(first, q, op) for q in qs[1:]]
        return Quantity(min(mags) if op == "min" else max(mags), first.unit)
    if op == "neg":
        return Quantity(-first.magnitude, first.unit)
    if op == "abs":
        return Quantity(abs(first.magnitude), first.unit)
    if op == "mul":
        mag, unit = first.magnitude, first.unit
        for i, q in enumerate(qs[1:], 2):  # step by step, each partial product held to the budget
            unit, scale = U.multiply(unit, q.unit)
            mag = mag * q.magnitude * scale
            guard.check_number(mag, "product" if i == len(qs) else f"partial product (of the first {i} arguments)")
        return Quantity(mag, unit)
    if op == "div":
        divisor = qs[1]
        if divisor.magnitude == 0:
            raise Refusal(f'div: "{names[1]}" is zero ({value_text(divisor)}), and division by zero has no value.', kind="division_by_zero")
        unit, scale = U.multiply(first.unit, U.invert(divisor.unit))
        return Quantity(first.magnitude / divisor.magnitude * scale, unit)
    if op == "pow":
        exponent = qs[1]
        if exponent.unit != U.PLAIN or exponent.magnitude.denominator != 1:
            raise Refusal(
                f'pow: the exponent "{names[1]}" is {value_text(exponent)}; it must be a plain whole number, '
                "because any other power of a number is not exact in general.",
                kind="bad_exponent",
            )
        n = exponent.magnitude.numerator
        if abs(n) > MAX_POWER_ARG:
            raise Refusal(f"pow: an exponent is at most {MAX_POWER_ARG} either way; this one is {n}.", kind="too_large")
        if first.magnitude == 0 and n < 0:
            raise Refusal(f'pow: "{names[0]}" is zero, and a negative power of zero divides by zero.', kind="division_by_zero")
        if first.magnitude == 0 and n == 0:
            raise Refusal("pow: zero to the power zero has no single agreed value, so flo2-calc does not pick one.", kind="undefined")
        unit, scale = U.power(first.unit, n)
        base = first.magnitude
        if scale != 1:
            # A folded "%" (U.fold_percent): m^n * (1/100)^(k*n) is (m / 100^k)^n. Folding
            # it into the base first keeps the base in lowest terms, so the size check
            # below is of the power actually computed.
            k = dict(first.unit)[U.PERCENT]
            assert scale == Fraction(1, 100) ** (k * n)
            base = base * Fraction(1, 100) ** k
        guard.check_power(base, n)  # BEFORE computing: a huge power stalls inside one operation
        return Quantity(base**n, unit)
    if op == "convert":
        assert node.unit is not None
        return Quantity(first.magnitude * U.conversion(first.unit, node.unit, op), node.unit)
    raise AssertionError(f"operator {op} has no evaluation")  # pragma: no cover


def evaluate(graph: Graph, guard: L.Guard | None = None) -> Evaluation:
    """Evaluate under `guard` (by default, a fresh one with the laptop limits)."""
    guard = guard if guard is not None else L.Guard()
    ev = Evaluation(graph, guard)
    nodes = graph.by_id()
    order = evaluation_order(graph)
    for i, nid in enumerate(order):
        node = nodes[nid]
        try:
            guard.at(nid, node.op if isinstance(node, OpNode) else None, i, len(order))
            ev.order.append(nid)
            if isinstance(node, InputNode):
                if isinstance(node.value, Quantity):
                    guard.check_number(node.value.magnitude, "value")
                ev.values[nid] = node.value
                continue
            value = _apply(node, [ev.values[a] for a in node.args], guard)
            if isinstance(value, Quantity):
                guard.check_number(value.magnitude)
        except LimitExceeded as e:
            ev.refusal = e.refusal
            return ev
        except Refusal as r:
            ev.refusal = {"node": nid, "op": node.op, "kind": r.kind, "reason": r.reason}
            if r.units:
                ev.refusal["units"] = list(r.units)
            return ev
        except OverflowError as e:
            ev.refusal = {"node": nid, "op": node.op, "kind": "too_large", "reason": f"{node.op}: {e}."}
            return ev
        ev.values[nid] = value
    guard.past_nodes()
    return ev


STOPPED_NEXT = (
    "This passed a limit of this host, not a rule of the math: nothing is wrong with the computation. "
    "record_computation returns it as a not-yet-computed record, which flo2-calc on a machine with more room "
    "(a higher limit) completes."
)


def values_json(ev: Evaluation) -> list[dict[str, str]]:
    """Every value computed, in evaluation order, as replies write them. Writing
    out a large value takes time and room, so each is counted against the
    deadline and the reply budget as it is written (LimitExceeded)."""
    out = []
    for nid in ev.order:
        if nid in ev.values:
            entry = {"node": nid, **value_json(ev.values[nid])}
            ev.guard.spend_reply(sum(len(v) for v in entry.values()) + 32)
            out.append(entry)
    return out


def evaluation_json(ev: Evaluation) -> dict[str, Any]:
    """What a reply says about an evaluation. An answer too large for the
    host's reply budget, or one whose writing passes the deadline, is itself
    stopped there: a refusal of kind exceeds_limits, with no values."""
    if ev.ok:
        try:
            values = values_json(ev)
        except LimitExceeded as e:
            return {"status": "refused", "refused": e.refusal, "result": None, "values": None, "next": STOPPED_NEXT}
        return {
            "status": "ok",
            "result": {"node": ev.graph.result, **value_json(ev.values[ev.graph.result])},
            "values": values,
            "exactness": EXACT_FOR_THESE_INPUTS,
        }
    try:
        values = values_json(ev)
    except LimitExceeded:
        values = None  # the values before the stop are too large to send: the refusal says why
    answer = {"status": "refused", "refused": ev.refusal, "result": None, "values": values}
    if ev.stopped:
        answer["next"] = STOPPED_NEXT
    return answer
