"""The computation shown back: its formula, and its step-by-step working.

dec:idea-show-a-computation-in-math-notation (a): every reply and record shows
the computation as a formula, in plain text always and in LaTeX beside it,
with named sub-expressions where the graph is large ("t = C / I = 450/13 h").

dec:idea-what-sets-flo2-calc-apart-from-other-math-mcps (b): every reply and
record shows step-by-step working, the graph as numbered steps in evaluation
order, each with its formula, its value with its unit, and its label. The
steps come from what was computed, so they cannot drift from the answer. A
reply keeps a large graph readable (a run of like steps collapsed, a cap with
how many are left out); the record holds every step.
"""

from __future__ import annotations

import copy
import json
import re

import pytest
from conftest import graph, inp, op

from flo2_calc import formula as FM
from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph


def run(g):
    return evaluation_json(evaluate(read_graph(g)))


BATTERY = graph(inp("C", "450 mAh", "cell datasheet"), inp("I", "13 mA", "measured"), op("t", "div", "C", "I"))
FIBER = graph(
    inp("cavity", "2 mm", "design"), inp("bend", "1.4 mm", "datasheet"), op("margin", "sub", "cavity", "bend"),
    inp("needed", "0.5 mm", "assumed"), op("fits", "ge", "margin", "needed"),
)


# ---------------------------------------------------------------- the formula


def test_the_battery_formula_reads_as_the_decision_wrote_it():
    """The decision's own example: t = C / I = 450/13 h."""
    answer = run(BATTERY)
    assert answer["formula"] == [{
        "node": "t",
        "text": "t = C / I = 450/13 h",
        "latex": r"\text{t} = \frac{\text{C}}{\text{I}} = \frac{450}{13}\,\mathrm{h}",
    }]


def test_a_small_graph_is_one_equation_with_its_single_use_steps_folded_in():
    assert run(FIBER)["formula"] == [{
        "node": "fits",
        "text": "fits = cavity - bend >= needed = true",
        "latex": r"\text{fits} = \text{cavity} - \text{bend} \ge \text{needed} = \text{true}",
    }]


def test_a_rounded_result_is_shown_approximately_equal_never_equal():
    answer = run(graph(inp("x", "2"), op("r", "sqrt", "x")))
    line = answer["formula"][0]
    assert line["text"] == "r = sqrt(x) ≈ 1.41421356237309504880168872421"
    assert r"\sqrt{\text{x}} \approx 1.41421356237309504880168872421" in line["latex"]


def test_a_node_used_twice_is_its_own_named_line():
    answer = run(graph(inp("a", "3"), inp("b", "4"), op("s", "add", "a", "b"), op("sq", "mul", "s", "s")))
    assert [f["text"] for f in answer["formula"]] == ["s = a + b", "sq = s * s = 49"]


def test_a_large_graph_reads_as_named_sub_expressions_each_short():
    nodes = [inp("x", "1"), inp("one", "1")] + [op("y0", "add", "x", "one")]
    nodes += [op(f"y{i}", "add", f"y{i - 1}", "one") for i in range(1, 60)]
    formula = run(graph(*nodes))["formula"]
    assert 3 < len(formula) < 20, "folded into a few named sub-expressions, not one line and not sixty"
    for before, line in zip(formula, formula[1:]):
        lhs, rhs = line["text"].split(" = ", 1)
        assert rhs.startswith(before["node"] + " + "), "each named sub-expression builds on the one before"
        assert len(rhs.split(" = ")[0]) <= FM.FOLD_AT + len(" + one")
    assert formula[-1]["text"].endswith("= 61")


def test_precedence_is_kept_by_parentheses_in_text_and_in_latex():
    g = graph(inp("a", "1"), inp("b", "2"), inp("c", "3"), op("s", "sub", "b", "c"), op("d", "sub", "a", "s"),
              op("p", "add", "a", "b"), op("q", "mul", "p", "c"), op("r", "pow", "q", "c"), op("both", "add", "d", "r"))
    text = run(g)["formula"][-1]["text"]
    assert text == "both = a - (b - c) + ((a + b) * c)^c = 731"


def test_several_results_are_each_a_line_with_its_value():
    g = graph(inp("a", "2 mm"), inp("b", "3 mm"), op("s", "add", "a", "b"), op("t", "mul", "a", "b"), result=["t", "s"])
    answer = run(g)
    assert [f["text"] for f in answer["formula"]] == ["s = a + b = 5 mm", "t = a * b = 6 mm^2"]


@pytest.mark.parametrize("node, text", [
    (op("r", "convert", "x", unit="mm"), "r = convert(x, mm)"),
    (op("r", "magnitude", "x", unit="mm"), "r = magnitude(x, mm)"),
    (op("r", "abs", "x"), "r = |x|"),
    (op("r", "neg", "x"), "r = -x"),
    (op("r", "ceil", "x", places=1), "r = ceil(x, places=1)"),
])
def test_each_operator_has_a_plain_text_form(node, text):
    assert run(graph(inp("x", "2.25 m"), node))["formula"][0]["text"].startswith(text + " = ")


def test_a_long_value_is_not_repeated_in_a_line():
    answer = run(graph(inp("x", "2"), inp("n", "1000"), op("p", "pow", "x", "n")))
    line = answer["formula"][0]["text"]
    assert line == 'p = x^n = (a 302-character value: see "values")'
    assert len(answer["result"]["value"]) == 302


# ---------------------------------------------------------------- the working


def test_every_node_is_a_numbered_step_with_its_formula_value_unit_and_label():
    working = run(FIBER)["working"]
    assert working == [
        {"step": 1, "node": "cavity", "text": "cavity = 2 mm", "latex": r"\text{cavity} = 2\,\mathrm{mm}", "label": "given"},
        {"step": 2, "node": "bend", "text": "bend = 1.4 mm", "latex": r"\text{bend} = 1.4\,\mathrm{mm}", "label": "given"},
        {"step": 3, "node": "margin", "text": "margin = cavity - bend = 2 mm - 1.4 mm = 0.6 mm",
         "latex": r"\text{margin} = \text{cavity} - \text{bend} = 2\,\mathrm{mm} - 1.4\,\mathrm{mm} = 0.6\,\mathrm{mm}",
         "label": "exact"},
        {"step": 4, "node": "needed", "text": "needed = 0.5 mm", "latex": r"\text{needed} = 0.5\,\mathrm{mm}", "label": "given"},
        {"step": 5, "node": "fits", "text": "fits = margin >= needed = 0.6 mm >= 0.5 mm = true",
         "latex": r"\text{fits} = \text{margin} \ge \text{needed} = 0.6\,\mathrm{mm} \ge 0.5\,\mathrm{mm} = \text{true}",
         "label": "exact"},
    ]


def test_a_rounded_step_is_labelled_with_its_digits_and_bound():
    working = run(graph(inp("x", "2"), op("r", "sqrt", "x", digits=12), inp("k", "3"), op("y", "mul", "r", "k")))["working"]
    assert working[1]["label"] == "rounded: 12 significant digits, correctly rounded, error at most 5e-12"
    assert working[1]["text"] == "r = sqrt(x) = sqrt(2) ≈ 1.41421356237"
    assert working[3]["label"].startswith("rounded: 12 significant digits, error at most ")


def test_the_steps_come_from_what_was_computed_not_from_a_narrative():
    """Each step's value is the value the evaluation reported for that node."""
    nodes = [inp("x", "0.7"), op("a", "sqrt", "x"), op("b", "exp", "a"), inp("c", "3 mm"), op("d", "mul", "b", "c"),
             op("e", "convert", "d", unit="um"), inp("lim", "5000 um"), op("f", "lt", "e", "lim")]
    answer = run(graph(*nodes))
    values = {v["node"]: v for v in answer["values"]}
    for step in answer["working"]:
        shown = values[step["node"]]
        assert step["text"].endswith(shown.get("exact") or shown["value"]), step
        assert ("rounded" in shown) == step["label"].startswith("rounded")


def test_a_refused_evaluation_shows_the_working_up_to_the_refused_step():
    answer = run(graph(inp("a", "2 mm"), inp("b", "3 g"), op("s", "add", "a", "b"), op("t", "mul", "s", "s")))
    assert answer["status"] == "refused"
    assert [w["node"] for w in answer["working"]] == ["a", "b", "s"]
    assert answer["working"][-1] == {"step": 3, "node": "s", "text": "s = a + b = 2 mm + 3 g",
                                     "latex": r"\text{s} = \text{a} + \text{b} = 2\,\mathrm{mm} + 3\,\mathrm{g}",
                                     "label": "refused: unit_mismatch"}


def test_a_long_graph_is_readable_in_a_reply_and_whole_in_the_record():
    nodes = [inp("x0", "1", "t"), inp("one", "1/7", "t")] + [op(f"y{i}", "add", f"y{i - 1}" if i else "x0", "one") for i in range(300)]
    g = graph(*nodes)
    answer = run(g)
    shown = answer["working"]
    assert len(shown) <= FM.VIEW_STEPS
    collapsed = [w for w in shown if "collapsed" in w]
    assert collapsed and collapsed[0]["text"].startswith(f"{collapsed[0]['collapsed']} steps like step ")
    assert shown[-1]["node"] == "y299", "the last step, the result, is always shown"
    counted = sum(w.get("collapsed", 0) + w.get("omitted", 0) + (1 if "step" in w else 0) for w in shown)
    assert counted == len(nodes), "every step is shown or counted"
    record = R.build(evaluate(read_graph(g)), "chain", None)
    assert [w["step"] for w in record["working"]] == list(range(1, len(nodes) + 1)), "the record holds every step"


def test_a_reply_past_the_cap_says_how_many_steps_are_left_out_and_where():
    nodes = [inp(f"v{i}_{chr(97 + i % 26)}", str(i)) for i in range(60)] + [op("s", "add", *[f"v{i}_{chr(97 + i % 26)}" for i in range(60)])]
    shown = run(graph(*nodes))["working"]
    assert len(shown) == FM.VIEW_STEPS
    gap = next(w for w in shown if "omitted" in w)
    assert gap["text"] == f"{gap['omitted']} more steps ({gap['steps']}) are not shown here; record_computation keeps every one in its record"
    counted = sum(w.get("omitted", 0) + (1 if "step" in w else 0) for w in shown)
    assert counted == 61


# ---------------------------------------------------------------- in the record, sealed and re-checked


def test_a_record_holds_the_formula_and_every_step_and_re_runs_to_them():
    rec = R.build(evaluate(read_graph(BATTERY)), "battery", None)
    assert rec["formula"][0]["text"] == "t = C / I = 450/13 h"
    assert [w["node"] for w in rec["working"]] == ["C", "I", "t"]
    assert R.rerun(rec)["reproduces"] is True


@pytest.mark.parametrize("field", ["formula", "working"])
def test_a_formula_or_working_edited_after_the_fact_is_caught_even_with_a_new_hash(field):
    """The steps cannot drift from the answer: a record whose shown working no
    longer follows from its graph does not reproduce."""
    rec = R.build(evaluate(read_graph(BATTERY)), "battery", None)
    lied = copy.deepcopy(rec)
    lied[field][-1]["text"] = lied[field][-1]["text"].replace("450/13", "450/12")
    lied["content_hash"] = R.content_hash(lied)
    answer = R.rerun(R.load(lied))
    assert answer["reproduces"] is False
    assert any(d["field"] == field for d in answer["differences"])


def test_a_not_yet_computed_record_shows_its_equations_with_no_values():
    g = graph(inp("x", "9" * 60, "t"), inp("n", "60", "t"), op("p", "pow", "x", "n"), op("q", "mul", "p", "p"))
    limits = L.Limits(max_digits=200)
    ev = evaluate(read_graph(g), L.Guard(limits))
    assert ev.stopped
    rec = R.build_pending(ev.graph, "big", None, ev.refusal, limits)
    assert [f["text"] for f in rec["formula"]] == ["p = x^n", "q = p * p"], "p is used twice: a named line"
    assert all(w["label"] == "not computed" for w in rec["working"])
    assert rec["working"][2]["text"] == "p = x^n"
    assert "9" * 60 not in json.dumps(rec["working"]), "no value is written into a step"


def test_latex_is_given_beside_every_line_and_balanced():
    nodes = [inp("x", "0.5"), inp("y", "2 m"), inp("z", "3 m"), op("a", "asin", "x", unit="deg"), op("b", "atan2", "y", "z", unit="rad"),
             op("c", "normal_cdf", "x"), op("d", "div", "y", "z"), op("e", "pow", "d", "x"), op("f", "ln", "e"),
             op("g", "floor", "f", places=2), op("h", "lt", "g", "c")]
    answer = run(graph(*nodes))
    for line in answer["formula"] + answer["working"]:
        tex = line["latex"]
        assert tex.count("{") == tex.count("}"), tex
        assert tex.count(r"\left") == tex.count(r"\right"), tex
        assert line["text"] and not re.search(r"\\[a-z]", line["text"]), "the plain text holds no LaTeX"
