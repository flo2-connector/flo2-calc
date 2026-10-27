"""A reply shows a readable decimal beside each exact array result; the kept record stays exact (flo2-calc 0.12.0).

dec:a-reply-shows-a-readable-decimal-beside-an-exact-array-result in design 0bee0c00b35845f6, Anthony's ruling of
2026-10-24 ("go with your recommendations").

WHAT PROMPTED IT. The Shop sample trial's Phase C monthly net energy (tests/data/answer-budget/electricity, node
net_m) came back as twelve exact fractions, the first -4869729231506843861/1575262621733750 kWh. A single exact value
is already written as a rounded decimal with its fraction beside it ("value" and "exact"); an exact array was written
as fractions only, so nobody could read it.

THE RULE, pinned here as a class:
  - every reply (all four tools) shows, beside each exact array result that has an element written as a fraction, a
    `readable` block: the same elements as decimals, each fraction rounded half-even to answer.READABLE_DIGITS
    significant digits and labelled as a rendering, every element already written as a decimal repeated as written;
  - it mirrors what the reply shows of the array: every value (a grid's rows kept), or its first, least and
    greatest, or, when cut to fit, its first and last;
  - it is the reply's alone: the kept record holds the exact values only, in the record format of schema 10,
    unchanged;
  - it fits the host's answer budget. It is a view of the result, not the result: when the outcome alone is over the
    budget, a rendering goes before any exact value is cut, and comes back beside whatever is shown of a result cut
    to its ends.
flo2-calc has no symbolic values: an exact array's elements are rationals, and every other numeric value (a rounded
value, a float64 array) is already written as a decimal, so it gets no rendering.
"""

from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import anyio
import jsonschema
import pytest
from conftest import answer_of, graph, inp, op, session, text_of, under_image

from flo2_calc import record as R

DATA = Path(__file__).parent / "data" / "answer-budget"
FLO2_IO_ANSWER_CHARS = 24_000
FLO2_IO_ENV = {
    "FLO2_CALC_DEADLINE": "20", "FLO2_CALC_MAX_DIGITS": "2000", "FLO2_CALC_MAX_REPLY_BYTES": "2097152",
    "FLO2_CALC_MAX_ARRAY_BYTES": "16777216", "FLO2_CALC_MAX_EXACT_ELEMENTS": "4096",
    "FLO2_CALC_MAX_ARRANGEMENTS": "1000000", "FLO2_CALC_MAX_SHAPLEY_FACTORS": "12",
    "FLO2_CALC_MAX_PRIME_DIGITS": "200", "FLO2_CALC_MAX_FACTOR_DIGITS": "40",
    "FLO2_CALC_MAX_ANSWER_CHARS": str(FLO2_IO_ANSWER_CHARS),
}
DIGITS = 6

THIRDS = graph(
    inp("x", {"array": ["1", "2", "3.5", "3"], "unit": "kWh"}),
    inp("k", "3"),
    op("y", "div", "x", "k"),
    result="y",
)
GRID = graph(inp("g", {"array": [["1", "2"], ["3", "14"]], "unit": "m"}), inp("k", "7"), op("y", "div", "g", "k"), result="y")


async def _calls(steps, env):
    out = []
    async with session(env=None if under_image() else env) as s:
        for tool, args in steps:
            out.append(await s.call_tool(tool, args))
    return out


def calls(steps, env=FLO2_IO_ENV):
    return anyio.run(_calls, steps, env)


def within_a_rendering(shown: str, exact: str) -> bool:
    """`shown` is `exact` rounded to DIGITS significant digits: within half a unit of its last digit."""
    q, r = Fraction(exact), Fraction(Decimal(shown))
    return abs(r - q) <= abs(q) * Fraction(5, 10**DIGITS)


def flat(v):
    return [x for row in v for x in row] if v and isinstance(v[0], list) else list(v)


def nowhere_in(record: dict, key: str) -> bool:
    def walk(v):
        if isinstance(v, dict):
            return key not in v and all(walk(x) for x in v.values())
        if isinstance(v, list):
            return all(walk(x) for x in v)
        return True

    return walk(record)


# ---------------------------------------------------------------- beside each exact array result


def test_an_exact_array_result_shows_a_readable_decimal_beside_its_fractions():
    (r,) = calls([("evaluate_graph", {"graph": THIRDS})])
    res = answer_of(r)["result"]
    assert res["array"]["values"] == ["1/3", "2/3", "7/6", "1"], "the exact values are shown as they are"
    shown = res["readable"]
    assert shown["values"] == ["0.333333", "0.666667", "1.16667", "1"], "a fraction rounded, a decimal as written"
    assert "rendering" in shown["rendering"] and f"{DIGITS} significant digits" in shown["rendering"]
    assert all(within_a_rendering(s, e) for s, e in zip(shown["values"], res["array"]["values"]))


def test_a_grids_rendering_keeps_its_rows():
    (r,) = calls([("evaluate_graph", {"graph": GRID})])
    res = answer_of(r)["result"]
    assert res["array"]["values"] == [["1/7", "2/7"], ["3/7", "2"]]
    assert res["readable"]["values"] == [["0.142857", "0.285714"], ["0.428571", "2"]]


def test_every_tool_shows_it_and_the_kept_record_stays_exact():
    made, added = calls([
        ("record_computation", {"graph": THIRDS, "name": "thirds", "supports": "a test"}),
        ("add_node", {"graph": {"nodes": THIRDS["nodes"][:2]}, "node": THIRDS["nodes"][2]}),
    ])
    record = json.loads(made.content[1].resource.text)
    (again,) = calls([("rerun_record", {"record": made.content[1].resource.text})])
    for reply, key in ((made, "result"), (added, "added"), (again, "result")):
        v = answer_of(reply)[key]
        assert v["readable"]["values"] == ["0.333333", "0.666667", "1.16667", "1"], key
    assert answer_of(again)["reproduces"] is True
    # The kept record: the exact values only, in the current schema's format (12 since 0.14.0).
    assert record["schema_version"] == 12
    jsonschema.Draft202012Validator(R.schema()).validate(record)
    assert record["result"]["array"]["values"] == ["1/3", "2/3", "7/6", "1"]
    assert nowhere_in(record, "readable"), "the record holds no rendering"


def test_the_trials_monthly_net_energy_reads_as_decimals_within_flo2_ios_budget():
    g = json.loads((DATA / "electricity.graph.json").read_text(encoding="utf-8"))
    evaluated, made = calls([
        ("evaluate_graph", {"graph": g}),
        ("record_computation", {"graph": g, "name": "electricity", "supports": "a test"}),
    ])
    record = json.loads(made.content[1].resource.text)
    kept = {v["node"]: v for v in record["results"]}["net_m"]
    assert kept["array"]["values"][0] == "-4869729231506843861/1575262621733750" and "readable" not in kept
    for r in (evaluated, made):
        assert len(text_of(r)) <= FLO2_IO_ANSWER_CHARS, f"{len(text_of(r)):,} characters"
        net = {v["node"]: v for v in answer_of(r)["results"]}["net_m"]
        assert net["array"] == kept["array"], "the exact result, whole, as the record holds it"
        assert net["readable"]["values"][0] == "-3091.38"
        assert all(within_a_rendering(s, e) for s, e in zip(net["readable"]["values"], net["array"]["values"]))


# ---------------------------------------------------------------- only where it is needed


def test_nothing_is_added_where_the_value_is_already_a_decimal():
    g = graph(
        inp("x", {"array": ["1", "2", "3"], "unit": "mm^2"}),  # sqrt of mm^2 is in mm
        inp("h", "2"),
        op("half", "div", "x", "h"),  # 0.5, 1, 1.5: exact, and already decimals
        op("root", "sqrt", "x"),  # a float64 array: a decimal with its bound
        inp("a", "1"),
        inp("b", "3"),
        op("third", "div", "a", "b"),  # one exact value: its decimal and its fraction, as before
        op("r2", "sqrt", "h"),  # one rounded value
        result=["half", "root", "third", "r2"],
    )
    (r,) = calls([("evaluate_graph", {"graph": g})])
    by = {v["node"]: v for v in answer_of(r)["results"]}
    assert by["half"]["array"]["values"] == ["0.5", "1", "1.5"]
    assert all("readable" not in v for v in by.values())
    assert by["third"] == {"node": "third", "value": "0.333333333333333333333333333333", "exact": "1/3"}


# ---------------------------------------------------------------- within the reply bound


def long_fractions(n: int) -> list[str]:
    return [f"{10**25 + 7 * i}/{3**40}" for i in range(n)]


def test_a_large_array_shows_its_first_least_and_greatest_as_decimals():
    big = graph(inp("x", {"array": long_fractions(2000), "unit": "J"}), inp("k", "1"), op("y", "mul", "x", "k"), result="y")
    (r,) = calls([("evaluate_graph", {"graph": big})])
    assert len(text_of(r)) <= FLO2_IO_ANSWER_CHARS
    res = answer_of(r)["result"]
    body, shown = res["array"], res["readable"]
    assert "values" not in body and len(body["first"]) == len(shown["first"])
    assert all(within_a_rendering(s, e) for s, e in zip(shown["first"], body["first"]))
    assert within_a_rendering(shown["least"], body["least"]) and within_a_rendering(shown["greatest"], body["greatest"])


def test_a_rendering_goes_before_any_exact_value_is_cut():
    """An outcome whose exact values fit the budget alone, with no room left for their rendering: the values come
    whole, and `withheld` names the rendering left out."""
    from flo2_calc import limits as L
    from flo2_calc.answer import fit, text
    from flo2_calc.evaluator import evaluate, evaluation_json, read_graph

    g = graph(inp("x", {"array": long_fractions(100), "unit": "J"}), inp("k", "1"), op("y", "mul", "x", "k"), result="y")
    answer = evaluation_json(evaluate(read_graph(g), L.Guard(L.LAPTOP)))
    outcome = {k: v for k, v in answer.items() if k not in ("formula", "working", "values")}
    whole = fit(outcome, 10**9, "in the record")
    assert len(whole["result"]["readable"]["values"]) == 100
    budget = len(text(whole)) - 300  # a hundred decimals are some 1,700 characters
    fitted = fit(answer, budget, "in the record")
    assert len(text(fitted)) <= budget
    assert fitted["result"]["array"] == answer["result"]["array"], "every exact value, whole"
    assert "readable" not in fitted["result"]
    assert any(e["node"] == "y" and "readable" in e["shown"] for e in fitted["withheld"]["results"])
    assert "readable" not in answer["result"], "fit never writes into what it was given (a record's own values)"


@pytest.mark.skipif(under_image(), reason="the image's own budget is flo2.io's; this sets a smaller one")
def test_a_result_cut_to_its_ends_shows_those_ends_as_decimals():
    n = 600
    g = graph(inp("x", {"array": long_fractions(n), "unit": "J"}), inp("k", "1"), op("y", "mul", "x", "k"), result="y")
    env = {**FLO2_IO_ENV, "FLO2_CALC_MAX_ANSWER_CHARS": "4000"}
    made, evaluated = calls([
        ("record_computation", {"graph": g, "name": "long-fractions", "supports": "a test"}),
        ("evaluate_graph", {"graph": g}),
    ], env)
    record = json.loads(made.content[1].resource.text)
    assert len(record["result"]["array"]["values"]) == n and nowhere_in(record, "readable")
    for r in (made, evaluated):
        assert len(text_of(r)) <= 4000, f"{len(text_of(r)):,} characters"
        res = answer_of(r)["result"]
        body, shown = res["array"], res["readable"]
        assert set(shown) - {"rendering"} == {"first", "last"}
        assert all(within_a_rendering(s, e) for s, e in zip(shown["first"] + shown["last"], body["first"] + body["last"]))
