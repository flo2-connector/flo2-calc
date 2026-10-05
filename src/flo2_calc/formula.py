"""The computation shown back: its formula, and its step-by-step working.

dec:idea-show-a-computation-in-math-notation (a) and
dec:idea-what-sets-flo2-calc-apart-from-other-math-mcps (b), design
0bee0c00b35845f6. Under rule:the-agent-reasons-flo2-calc-calculates, the
agent's translation of a problem into a graph is the weak point, and a formula
shown back is the cheapest check a person can read. Both are rendered from the
graph that was evaluated and the values it gave, never written separately, so
they cannot drift from the answer. Each line is plain text, with LaTeX beside
it.

THE FORMULA is one equation per named node, in evaluation order: every result,
and every operation that is not folded into the one that uses it. An operation
is folded into its user (and so needs no name of its own) when exactly one
node uses it, it is not a result, and its text is at most FOLD_AT characters;
pi and e are always folded. So a small graph reads as one equation
("in_h = convert(capacity / draw, h) = 450/13 h"), and a large one as named
sub-expressions. A result's line ends with its value: "=" for an exact value
(its exact fraction where its decimal does not end), "≈" for a rounded one.

THE WORKING is every node as a numbered step, in evaluation order: an input
as given, then each operation with its arguments by name, the same with their
values written in (when each is at most SUBSTITUTE_AT characters), and its
value, with its label (given, exact, or rounded with its digits and bound).
Where the evaluation was refused, the working stops at the refused step, which
says so. A record holds every step; a reply shows a readable view of them
(`view`): a run of steps of the same shape is collapsed to its first and last,
and past VIEW_STEPS entries the middle is left out, saying how many steps and
where they are.

A value longer than SHOW_VALUE_AT characters is not repeated in a line: the
line says how long it is, and "values" holds it. An ARRAY (arrays.py) is named
in a line by its description ("array 6 (exact, s)"), never written in element
by element, and a step that takes one shows its arguments by name only; its
elements are in "values". A float64 value ends its line with "≈" and its label
says "float64" with its bound. The array operators have renderings of their
own: sum and product as sigma and pi, mean as a bar, fft as script F, an
element as a subscript, and the rest as named functions.

The renderings are part of the record's format (schema version 4): a change
to them is a change of schema version, because a record re-runs to exactly the
fields it holds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from flo2_calc import units as U

FOLD_AT = 80
SUBSTITUTE_AT = 40
SHOW_VALUE_AT = 80
VIEW_STEPS = 40
VIEW_TAIL = 10
RUN_AT = 4  # a run of this many steps of one shape, or more, is collapsed in a view

OR, XOR, AND, NOT, CMP, ADD, MUL, NEG, FRAC, POW, CALL, ATOM = 10, 15, 20, 30, 40, 50, 60, 70, 75, 80, 90, 100


@dataclass(frozen=True)
class Shown:
    """A value as a reply shows it."""

    text: str  # with its unit
    exact: str | None = None  # its exact fraction, where its text is rounded
    rounded: dict[str, Any] | None = None  # its rounded label
    float64: dict[str, Any] | None = None  # its float64 label (arrays.py)
    array: bool = False  # an array: named by its description, never written in


@dataclass(frozen=True)
class Expr:
    text: str
    tprec: int
    latex: str
    lprec: int


def _pt(e: Expr, need: int) -> str:
    return e.text if e.tprec >= need else f"({e.text})"


def _pl(e: Expr, need: int) -> str:
    return e.latex if e.lprec >= need else r"\left(" + e.latex + r"\right)"


def tex_name(name: str) -> str:
    return r"\text{" + name.replace("_", r"\_") + "}"


def _op_tex(name: str) -> str:
    return r"\operatorname{" + name.replace("_", r"\_") + "}"


def name(node_id: str) -> Expr:
    return Expr(node_id, ATOM, tex_name(node_id), ATOM)


def unit_latex(text: str) -> str:
    if text.strip() == "":
        return "1"
    try:
        return U.latex(U.parse_unit(text))
    except ValueError:
        return r"\text{" + text.replace("_", r"\_") + "}"


_NUMBER = re.compile(r"^(-?)(\d+(?:\.\d+)?)(?:e([+-]\d+))?(?:/(\d+))?$")


def number_latex(text: str) -> str:
    m = _NUMBER.match(text)
    if m is None:
        return r"\text{" + text + "}"
    sign, digits, exp, den = m.groups()
    if den is not None:
        return sign + r"\frac{" + digits + "}{" + den + "}"
    if exp is not None:
        return sign + digits + r"\times 10^{" + str(int(exp)) + "}"
    return sign + digits


def value_expr(text: str) -> Expr:
    """A value's text ("450/13 h", "-1.4 mm", "true") as an operand."""
    if text in ("true", "false"):
        return Expr(text, ATOM, r"\text{" + text + "}", ATOM)
    number, _, unit = text.partition(" ")
    tex = number_latex(number)
    neg = number.startswith("-")
    frac = "/" in number
    if unit:
        tex = tex + r"\," + unit_latex(unit)
        return Expr(text, NEG if neg else MUL, tex, NEG if neg else MUL)
    if neg:
        return Expr(text, NEG, tex, NEG)
    return Expr(text, MUL if frac else ATOM, tex, FRAC if frac else ATOM)


def _call(fn_text: str, fn_tex: str, args: list[Expr], sep: str = ", ") -> Expr:
    t = fn_text + "(" + sep.join(a.text for a in args) + ")"
    lsep = r",\ " if sep == ", " else r";\ "
    return Expr(t, CALL, fn_tex + r"\left(" + lsep.join(a.latex for a in args) + r"\right)", CALL)


_CMP_TEXT = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
_CMP_TEX = {"eq": r"\overset{?}{=}", "ne": r"\neq", "lt": "<", "le": r"\le", "gt": ">", "ge": r"\ge"}
_FUNC_TEX = {"exp": r"\exp", "ln": r"\ln", "log10": r"\log_{10}", "sin": r"\sin", "cos": r"\cos", "tan": r"\tan",
             "asin": r"\arcsin", "acos": r"\arccos", "atan": r"\arctan", "min": r"\min", "max": r"\max"}


def _joined(op: str, args: list[Expr]) -> Expr:
    prec, word, tex = {"and": (AND, "and", r"\land"), "or": (OR, "or", r"\lor"), "xor": (XOR, "xor", r"\oplus")}[op]
    return Expr(f" {word} ".join(_pt(a, prec) for a in args), prec, f" {tex} ".join(_pl(a, prec) for a in args), prec)


def _with_axis(node: Any, text: str, latex: str) -> tuple[str, str]:
    axis = getattr(node, "axis", None)
    if axis is None:
        return text, latex
    return text + f", axis={axis}", latex + r";\ \text{axis } " + str(axis)


_FFT_TEX = {"fft": r"\mathcal{F}", "ifft": r"\mathcal{F}^{-1}", "fft2": r"\mathcal{F}_{2}", "ifft2": r"\mathcal{F}_{2}^{-1}"}


def array_expression(node: Any, args: list[Expr]) -> Expr | None:
    """An array operator's rendering (arrays.py), or None for the others."""
    op = node.op
    if op in ("sum", "product") or (op == "count_true" and getattr(node, "axis", None) is not None and len(args) == 1):
        sym = {"sum": r"\sum", "product": r"\prod", "count_true": r"\#_{\text{true}}"}[op]
        text, sub = _with_axis(node, args[0].text, "")
        latex = sym + ("_{" + sub.lstrip(r";\ ") + "}" if sub else "") + " " + _pl(args[0], CALL)
        return Expr(f"{op}({text})", CALL, latex, MUL)
    if op == "mean":
        if getattr(node, "axis", None) is None:
            return Expr(f"mean({args[0].text})", CALL, r"\overline{" + args[0].latex + "}", ATOM)
        text, tex = _with_axis(node, args[0].text, args[0].latex)
        return Expr(f"mean({text})", CALL, _op_tex("mean") + r"\left(" + tex + r"\right)", CALL)
    if op in ("min", "max", "any", "all") and len(args) == 1:
        text, tex = _with_axis(node, args[0].text, args[0].latex)
        fn = {"min": r"\min", "max": r"\max"}.get(op, _op_tex(op))
        return Expr(f"{op}({text})", CALL, fn + r"\left(" + tex + r"\right)", CALL)
    if op in _FFT_TEX:
        return Expr(f"{op}({args[0].text})", CALL, _FFT_TEX[op] + r"\left\{" + args[0].latex + r"\right\}", CALL)
    if op == "phase":
        unit = node.unit_text or "rad"
        return Expr(f"phase({args[0].text}, {unit})", CALL, r"\arg\left(" + args[0].latex + r"\right)_{" + unit_latex(unit) + "}", CALL)
    if op == "conj":
        return Expr(f"conj({args[0].text})", CALL, r"\overline{" + args[0].latex + "}", ATOM)
    if op in ("real", "imag"):
        return Expr(f"{op}({args[0].text})", CALL, (r"\operatorname{Re}" if op == "real" else r"\operatorname{Im}") + r"\left(" + args[0].latex + r"\right)", CALL)
    if op == "element":
        idx = ", ".join(a.text for a in args[1:])
        return Expr(f"{_pt(args[0], ATOM)}[{idx}]", ATOM, _pl(args[0], ATOM) + "_{" + ",".join(a.latex for a in args[1:]) + "}", ATOM)
    if op == "transpose":
        return Expr(f"transpose({args[0].text})", CALL, _pl(args[0], ATOM) + r"^{\mathsf{T}}", POW)
    if op in ("variance_sample", "variance_population", "sd_sample", "sd_population"):
        what, kind = op.split("_")
        fn = r"\operatorname{Var}" if what == "variance" else r"\operatorname{sd}"
        return Expr(f"{op}({args[0].text})", CALL, fn + r"_{\text{" + kind + r"}}\left(" + args[0].latex + r"\right)", CALL)
    return None


def expression(node: Any, args: list[Expr]) -> Expr:
    """One operation over its arguments' expressions."""
    op = node.op
    shaped = array_expression(node, args)
    if shaped is not None:
        return shaped
    if op in ("add", "sub"):
        if op == "sub":
            a, b = args
            return Expr(f"{_pt(a, ADD)} - {_pt(b, ADD + 1)}", ADD, f"{_pl(a, ADD)} - {_pl(b, ADD + 1)}", ADD)
        return Expr(" + ".join(_pt(a, ADD) for a in args), ADD, " + ".join(_pl(a, ADD) for a in args), ADD)
    if op == "mul":
        return Expr(" * ".join(_pt(a, MUL) for a in args), MUL, r" \cdot ".join(_pl(a, MUL) for a in args), MUL)
    if op == "div":
        a, b = args
        return Expr(f"{_pt(a, MUL)} / {_pt(b, MUL + 1)}", MUL, r"\frac{" + a.latex + "}{" + b.latex + "}", FRAC)
    if op == "neg":
        return Expr("-" + _pt(args[0], NEG + 1), NEG, "-" + _pl(args[0], NEG + 1), NEG)
    if op == "abs":
        return Expr(f"|{args[0].text}|", ATOM, r"\left|" + args[0].latex + r"\right|", ATOM)
    if op == "pow":
        a, b = args
        return Expr(f"{_pt(a, POW + 1)}^{_pt(b, POW + 1)}", POW, _pl(a, POW + 1) + "^{" + b.latex + "}", POW)
    if op == "sqrt":
        return Expr(f"sqrt({args[0].text})", CALL, r"\sqrt{" + args[0].latex + "}", ATOM)
    if op in ("pi", "e"):
        return Expr(op, ATOM, r"\pi" if op == "pi" else "e", ATOM)
    if op in _CMP_TEXT:
        a, b = args
        return Expr(f"{_pt(a, CMP + 1)} {_CMP_TEXT[op]} {_pt(b, CMP + 1)}", CMP, f"{_pl(a, CMP + 1)} {_CMP_TEX[op]} {_pl(b, CMP + 1)}", CMP)
    if op in ("and", "or", "xor"):
        return _joined(op, args)
    if op == "not":
        return Expr("not " + _pt(args[0], NOT), NOT, r"\lnot " + _pl(args[0], NOT), NOT)
    if op in ("nand", "nor"):
        inner = _joined("and" if op == "nand" else "or", args)
        return Expr(f"not ({inner.text})", NOT, r"\lnot\left(" + inner.latex + r"\right)", NOT)
    if op == "convert":
        unit = node.unit_text or ""
        tex = _op_tex("convert") + r"\left(" + args[0].latex + r",\ " + unit_latex(unit) + r"\right)"
        return Expr(f"convert({args[0].text}, {unit or '1'})", CALL, tex, CALL)
    if op == "magnitude":
        unit = node.unit_text or ""
        return Expr(f"magnitude({args[0].text}, {unit})", CALL, r"\left\{" + args[0].latex + r"\right\}_{" + unit_latex(unit) + "}", ATOM)
    if op == "with_unit":
        unit = node.unit_text or ""
        return Expr(f"with_unit({args[0].text}, {unit})", CALL, _pl(args[0], MUL + 1) + r"\," + unit_latex(unit), MUL)
    if op == "db_to_ratio":
        k = 10 if node.kind == "power" else 20
        x = args[0]
        return Expr(f"10^({x.text} / ({k} dB))", POW, r"10^{\frac{" + x.latex + "}{" + str(k) + r"\,\mathrm{dB}}}", POW)
    if op == "ratio_to_db":
        k = 10 if node.kind == "power" else 20
        r = args[0]
        return Expr(f"{k} dB * log10({r.text})", MUL, str(k) + r"\,\mathrm{dB}\cdot\log_{10}\left(" + r.latex + r"\right)", MUL)
    if op == "k_of_n":
        k, votes = args[0], args[1:]
        return Expr(
            f"k_of_n({k.text}; {', '.join(a.text for a in votes)})",
            CALL,
            _op_tex("k_of_n") + r"\left(" + k.latex + r";\ " + r",\ ".join(a.latex for a in votes) + r"\right)",
            CALL,
        )
    if op in ("ceil", "floor", "round"):
        extra = []
        if getattr(node, "places", None) is not None:
            extra.append(f"places={node.places}")
        if getattr(node, "mode", None) is not None:
            extra.append(f"mode={node.mode}")
        if not extra and op in ("ceil", "floor"):
            left, right = (r"\lceil ", r"\rceil") if op == "ceil" else (r"\lfloor ", r"\rfloor")
            return Expr(f"{op}({args[0].text})", CALL, r"\left" + left + args[0].latex + r" \right" + right, ATOM)
        t = f"{op}({', '.join([args[0].text, *extra])})"
        tex = _op_tex(op) + r"\left(" + args[0].latex + "".join(r";\ \text{" + x.replace("_", r"\_") + "}" for x in extra) + r"\right)"
        return Expr(t, CALL, tex, CALL)
    fn_tex = _FUNC_TEX.get(op, _op_tex(op))
    return _call(op, fn_tex, args)


def _is_constant(node: Any) -> bool:
    return getattr(node, "op", None) in ("pi", "e")


def _value_part(shown: Shown) -> tuple[str, str, str]:
    """(" = ", the value's text, its LaTeX) for the end of a line: its exact
    fraction where it has one, "≈" for a rounded value, and a long value named
    by its length instead of repeated."""
    text = shown.exact if shown.exact is not None else shown.text
    sign, tex_sign = (" ≈ ", r" \approx ") if (shown.rounded is not None or shown.float64 is not None) else (" = ", " = ")
    if shown.array:
        return sign, text, tex_sign + r"\text{" + text.replace("_", r"\_") + "}"
    if len(text) > SHOW_VALUE_AT:
        said = f'(a {len(text):,}-character value: see "values")'
        return sign, said, tex_sign + r"\text{" + said.replace('"', "") + "}"
    return sign, text, tex_sign + value_expr(text).latex


@dataclass
class Rendering:
    formula: list[dict[str, Any]]
    working: list[dict[str, Any]]
    shapes: list[tuple[Any, ...]]  # each step's shape, for collapsing a view


def _stem(node_id: str) -> str:
    return re.sub(r"\d+$", "#", node_id)


def _shape(node: Any) -> tuple[Any, ...]:
    if getattr(node, "op", None) is None:
        return ("input", _stem(node.id))
    keys = tuple(getattr(node, k, None) for k in ("unit_text", "digits", "places", "mode", "kind"))
    return (node.op, _stem(node.id), tuple(_stem(a) for a in node.args), keys)


def _label(shown: Shown | None, is_input: bool) -> str:
    if shown is None:
        return "not computed"
    if is_input:
        return "given"
    if shown.float64 is not None:
        return f"float64: error at most {shown.float64['error_at_most']}"
    r = shown.rounded
    if r is None:
        return "exact"
    how = "correctly rounded, " if r.get("correctly_rounded") else ""
    return f"rounded: {r['digits']} significant digits, {how}error at most {r['error_at_most']}"


def render(
    nodes: list[Any],
    order: list[str],
    results: tuple[str, ...],
    shown: dict[str, Shown],
    refused: dict[str, Any] | None = None,
) -> Rendering:
    """The formula and the working of a graph: `nodes` in the graph's order,
    `order` the evaluation order, `results` the result nodes, `shown` every
    computed value (none for a graph not yet computed), `refused` the refusal
    an evaluation stopped at, if any."""
    by_id = {n.id: n for n in nodes}
    uses: dict[str, int] = {n.id: 0 for n in nodes}
    for n in nodes:
        for a in getattr(n, "args", ()) or ():
            uses[a] += 1
    full: dict[str, Expr] = {}  # each operation, its folded arguments written in
    folded: set[str] = set()
    for nid in order:
        n = by_id[nid]
        if getattr(n, "op", None) is None:
            continue
        args = [full[a] if a in folded else name(a) for a in n.args]
        full[nid] = expression(n, args)
        if _is_constant(n) and nid not in results:
            folded.add(nid)
        elif uses[nid] == 1 and nid not in results and len(full[nid].text) <= FOLD_AT:
            folded.add(nid)

    formula: list[dict[str, Any]] = []
    for nid in order:
        n = by_id[nid]
        is_input = getattr(n, "op", None) is None
        if nid in folded or (is_input and nid not in results):
            continue
        text, tex = nid, tex_name(nid)
        if not is_input and full[nid].text != nid:
            text += " = " + full[nid].text
            tex += " = " + full[nid].latex
        if nid in results and nid in shown:
            sign, said, said_tex = _value_part(shown[nid])
            text += sign + said
            tex += said_tex
        formula.append({"node": nid, "text": text, "latex": tex})

    working: list[dict[str, Any]] = []
    shapes: list[tuple[Any, ...]] = []
    stop = refused.get("node") if refused else None
    for i, nid in enumerate(order, 1):
        n = by_id[nid]
        is_input = getattr(n, "op", None) is None
        here = shown.get(nid)
        if shown and here is None and nid != stop:
            break  # past the refused step
        text, tex = nid, tex_name(nid)
        if not is_input:
            step = expression(n, [name(a) for a in n.args])
            if step.text != nid:
                text += " = " + step.text
                tex += " = " + step.latex
            given = [shown.get(a) for a in n.args]
            if n.args and all(g is not None and not g.array for g in given):
                parts = [g.exact if g.exact is not None else g.text for g in given]  # type: ignore[union-attr]
                if all(len(p) <= SUBSTITUTE_AT for p in parts):
                    sub = expression(n, [value_expr(p) for p in parts])
                    text += " = " + sub.text
                    tex += " = " + sub.latex
        if here is not None:
            sign, said, said_tex = _value_part(here)
            text += sign + said
            tex += said_tex
        entry: dict[str, Any] = {"step": i, "node": nid, "text": text, "latex": tex, "label": _label(here, is_input)}
        if nid == stop and here is None:
            entry["label"] = f"refused: {refused['kind']}"  # type: ignore[index]
        working.append(entry)
        shapes.append(_shape(n))
        if nid == stop:
            break
    return Rendering(formula, working, shapes)


def view(working: list[dict[str, Any]], shapes: list[tuple[Any, ...]], where_rest: str) -> list[dict[str, Any]]:
    """The working as a reply shows it: a run of RUN_AT or more steps of one
    shape (the same operation on the same kinds of node, ids differing only in
    a trailing number) shows its first and last step and says how many lie
    between; past VIEW_STEPS entries, the first and the last VIEW_TAIL are
    shown, with how many steps are left out and `where_rest` they are."""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(working):
        j = i
        while j + 1 < len(working) and shapes[j + 1] == shapes[i]:
            j += 1
        if j - i + 1 >= RUN_AT:
            between = j - i - 1
            first, last = working[i + 1], working[j - 1]
            out.append(working[i])
            out.append({
                "collapsed": between,
                "steps": f"{first['step']} to {last['step']}",
                "text": f"{between} steps like step {working[i]['step']}, {first['node']} to {last['node']}",
            })
            out.append(working[j])
        else:
            out.extend(working[i: j + 1])
        i = j + 1
    if len(out) <= VIEW_STEPS:
        return out
    head, tail = out[: VIEW_STEPS - VIEW_TAIL - 1], out[-VIEW_TAIL:]
    left = out[len(head): len(out) - VIEW_TAIL]
    counted = sum(e.get("collapsed", 0) + (0 if "collapsed" in e else 1) for e in left)
    numbered = [e["step"] for e in left if "step" in e]
    span = f"{min(numbered)} to {max(numbered)}" if numbered else ""
    return [*head, {"omitted": counted, "steps": span, "text": f"{counted} more steps ({span}) {where_rest}"}, *tail]


def view_formula(formula: list[dict[str, Any]], where_rest: str) -> list[dict[str, Any]]:
    """The formula as a reply shows it: past VIEW_STEPS lines, the first and
    the last VIEW_TAIL, with how many lines are left out and `where_rest`
    they are. The result lines come last, so they are always shown."""
    if len(formula) <= VIEW_STEPS:
        return formula
    head, tail = formula[: VIEW_STEPS - VIEW_TAIL - 1], formula[-VIEW_TAIL:]
    left = formula[len(head): len(formula) - VIEW_TAIL]
    span = f"{left[0]['node']} to {left[-1]['node']}"
    return [*head, {"omitted": len(left), "lines": span, "text": f"{len(left)} more lines ({span}) {where_rest}"}, *tail]
