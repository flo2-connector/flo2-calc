"""A clamp keeps its one-sided bound, an array stays exact where every element is, and an intermediate array is
summarized in a reply (flo2-calc 0.15.0).

Three findings of 2026-10-27 in design 0bee0c00b35845f6, each measured on flo2-calc 0.14.0:

A. fact:a-clamp-at-zero-on-a-float64-array-keeps-a-two-sided-error-so-sqrt-refuses-the-edge-2026-10-27 (a defect).
   max(x, 0) on a float64 array kept each element as a symmetric ball, so an edge element read 0.0 within 3.4e-16 and
   sqrt refused it as undecidable, though max(x, 0) is never below 0. min, max and abs now give the interval their
   arguments' enclosures give ([max(lo), max(hi)] for max), written back from the end the operation guarantees. A
   single rounded value had the same shape (max(sin(pi rad), 0), then sqrt) and is fixed the same way.
B. fact:an-array-function-is-float64-where-the-same-scalar-is-exact-2026-10-27. sqrt(1/4) and cos(90 deg) were exact
   as single values and float64 over an array: the array path never tried the exact cases the scalar path checks first.
   Now an exact array whose every element has an exact value stays exact; otherwise float64 as before.
C. fact:a-reply-fills-its-budget-with-intermediate-values-in-graph-order-so-one-array-crowds-out-the-rest-2026-10-27.
   A 1,023-element integer_range took 7,272 characters of a reply and the six values after it were withheld. An
   intermediate array of more than 16 elements is now shown by its shape, sha256 and first and last elements.

Every test here failed on 0.14.0 (78fd6cc) but four: the version 12 record's re-run, which holds what was made
before, and three that hold what does not change (a domain refused element by element, float64 past the host's
exact limit, and float64 where one element has no exact value).
"""

from __future__ import annotations

import json
import time
from fractions import Fraction
from pathlib import Path

import anyio
import mpmath as mp
import numpy as np
import pytest
from conftest import answer_of, graph, inp, op, session, under_image

from flo2_calc import answer as AN
from flo2_calc import arrays as A
from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc import rederive as RD
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph

mp.mp.dps = 50
DATA = Path(__file__).parent / "data"


def arr(values, unit=None):
    return {"array": list(values), **({"unit": unit} if unit else {})}


def ev(*nodes, limits=L.FLO2_IO, result=None):
    return evaluate(read_graph(graph(*nodes, result=result), exact_limit=limits.max_exact_elements), L.Guard(limits))


def ok(*nodes, **kw):
    e = ev(*nodes, **kw)
    assert e.ok, e.refusal
    return e


def holds(a: A.Array, truth: list) -> None:
    """Every element of a float64 array is within its stated bound of the true value."""
    assert a.inexact
    for i, (v, e, t) in enumerate(zip(a.data.ravel().tolist(), a.error.ravel().tolist(), truth, strict=True)):
        assert abs(mp.mpf(v) - t) <= mp.mpf(e), f"element {i}: |{v} - {t}| > {e}"


# A chord of a unit circle at three angles, one of them (45 deg) with no exact cosine, so the array is float64.
def chord(angles=("0", "45", "90"), clamp="max"):
    return [
        inp("r", "1 mm"), inp("th", arr(angles, "deg")),
        op("c", "cos", "th"), op("rc", "mul", "r", "c"), op("rc2", "mul", "rc", "rc"), op("r2", "mul", "r", "r"),
        op("raw", "sub", "r2", "rc2"), inp("z", "0 mm^2"), op("cl", clamp, "raw", "z"),
    ]


def lower_ends(a: A.Array) -> list[Fraction]:
    return [Fraction(v) - Fraction(e) for v, e in zip(a.data.ravel().tolist(), a.error.ravel().tolist(), strict=True)]


# ---------------------------------------------------------------- A: min, max and abs keep a one-sided bound


def test_a_clamp_at_zero_on_a_float64_array_is_never_below_zero_and_its_root_answers_at_the_edge():
    e = ok(*chord(), op("s", "sqrt", "cl"), result="s")
    cl, s = e.values["cl"], e.values["s"]
    assert cl.inexact and min(lower_ends(cl)) >= 0, "max(x, 0) is never below 0, bound included"
    holds(cl, [mp.mpf(0), mp.mpf(1) / 2, mp.mpf(1)])
    holds(s, [mp.mpf(0), mp.sqrt(mp.mpf(1) / 2), mp.mpf(1)])  # the edge: its true value 0 is within its bound
    assert s.error[0] < 1e-7 and s.unit == (("mm", 1),)


def test_abs_of_an_element_either_side_of_zero_is_never_below_zero_and_its_root_answers():
    e = ok(*chord(), op("a", "abs", "raw"), op("s", "sqrt", "a"), result="s")
    assert min(lower_ends(e.values["a"])) >= 0
    holds(e.values["s"], [mp.mpf(0), mp.sqrt(mp.mpf(1) / 2), mp.mpf(1)])


def test_a_clamp_from_above_is_never_above_zero():
    e = ok(*chord(), op("n", "neg", "raw"), op("cl2", "min", "n", "z"), op("p", "neg", "cl2"), op("s", "sqrt", "p"), result="s")
    upper = [Fraction(v) + Fraction(x) for v, x in zip(e.values["cl2"].data.tolist(), e.values["cl2"].error.tolist())]
    assert max(upper) <= 0, "min(x, 0) is never above 0, bound included"
    holds(e.values["s"], [mp.mpf(0), mp.sqrt(mp.mpf(1) / 2), mp.mpf(1)])


def test_the_greatest_and_least_of_a_float64_array_keep_their_bounds_one_sided():
    e = ok(*chord(), op("n", "neg", "cl"), op("top", "max", "n"), op("p", "neg", "top"), op("s", "sqrt", "p"), result="s")
    top = e.values["top"]
    assert Fraction(float(top.data)) + Fraction(float(top.error)) <= 0, "the greatest of values <= 0 is <= 0"
    holds(e.values["s"], [mp.mpf(0)])


def test_where_the_one_picked_holds_both_ends_it_keeps_its_own_value_and_bound():
    big = ok(*chord(), inp("half", "1/1000 mm^2"), op("lo", "max", "raw", "half"), result="lo")
    raw, lo = big.values["raw"], big.values["lo"]
    # raw's elements 1 and 2 (0.5, 1 mm^2) are surely above 1/1000: their own balls, not a wider one.
    assert lo.data.tolist()[1:] == raw.data.tolist()[1:] and lo.error.tolist()[1:] == raw.error.tolist()[1:]
    assert lo.data.tolist()[0] == 0.001 and lo.error.tolist()[0] == float(A.to_float(Fraction(1, 1000))[1])


def test_a_single_rounded_value_clamped_at_zero_is_never_below_zero_and_its_root_answers():
    pi_rad = [op("p", "pi"), inp("u", "1 rad"), op("pr", "mul", "p", "u"), op("s", "sin", "pr"), inp("z", "0")]
    for last in (op("m", "max", "s", "z"), op("m", "abs", "s")):
        e = ok(*pi_rad, last, op("r", "sqrt", "m"), result="r")
        m, r = e.values["m"], e.values["r"]
        assert m.rounding is not None and m.magnitude - m.error >= 0, "never below 0, bound included"
        assert r.rounding is not None and r.magnitude - r.error <= 0 <= r.magnitude + r.error  # sin(pi) = 0 within it


# ---------------------------------------------------------------- B: an exact array stays exact where every element is


def test_sqrt_and_cos_over_an_exact_array_are_exact_where_each_element_is():
    q = ok(inp("x", arr(["1/4", "9/4"])), op("s", "sqrt", "x")).values["s"]
    assert q.kind == A.EXACT and q.data.tolist() == [Fraction(1, 2), Fraction(3, 2)] and q.label is None
    c = ok(inp("t", arr(["0", "90", "180", "-60"], "deg")), op("c", "cos", "t")).values["c"]
    assert c.kind == A.EXACT and c.data.tolist() == [1, 0, -1, Fraction(1, 2)]
    answer = evaluation_json(ok(inp("t", arr(["0", "90"], "deg")), op("c", "cos", "t")))
    assert answer["result"]["array"]["kind"] == "exact" and answer["result"]["array"]["values"] == ["1", "0"]
    assert "float64" not in answer["result"]


CASES = [  # (op, its arguments' arrays, extra node fields): every element has an exact value as a single value
    ("sqrt", [arr(["0", "1/4", "16/9"], "m^2")], {}),
    ("exp", [arr(["0", "0"])], {}),
    ("ln", [arr(["1"])], {}),
    ("log10", [arr(["1", "1000", "1/100"])], {}),
    ("sin", [arr(["0", "30", "150", "-90", "720"], "deg")], {}),
    ("tan", [arr(["0", "45", "-45", "225"], "deg")], {}),
    ("cos", [arr(["0"], "rad")], {}),
    ("asin", [arr(["0", "1/2", "-1"])], {"unit": "deg"}),
    ("acos", [arr(["1", "1/2", "0", "-1/2"])], {"unit": "deg"}),
    ("atan", [arr(["0", "1", "-1"])], {"unit": "deg"}),
    ("atan2", [arr(["1", "0", "-2"], "mm"), arr(["1", "-3", "0"], "mm")], {"unit": "deg"}),
    ("pow", [arr(["4", "9/4", "0"]), arr(["1/2", "3/2", "5/2"])], {}),
    ("normal_cdf", [arr(["0"])], {}),
    ("normal_quantile", [arr(["1/2"])], {}),
    ("db_to_ratio", [arr(["10", "-20", "0"], "dB")], {"kind": "power"}),
    ("ratio_to_db", [arr(["100", "1/10"])], {"kind": "amplitude"}),
]


@pytest.mark.parametrize("name,arrays,extra", CASES, ids=[c[0] for c in CASES])
def test_an_array_function_is_exact_exactly_where_the_same_single_value_is(name, arrays, extra):
    ids = [f"a{i}" for i in range(len(arrays))]
    out = ok(*[inp(i, a) for i, a in zip(ids, arrays)], op("y", name, *ids, **extra)).values["y"]
    assert out.kind == A.EXACT, f"{name} over an exact array whose every element has an exact value"
    for k in range(len(arrays[0]["array"])):  # each element, as a single value
        nodes = [inp(i, f'{a["array"][k]} {a.get("unit", "")}'.strip()) for i, a in zip(ids, arrays)]
        single = ok(*nodes, op("y", name, *ids, **extra)).values["y"]
        assert single.rounding is None and single.magnitude == out.data.ravel()[k] and single.unit == out.unit


def test_one_element_without_an_exact_value_keeps_the_array_float64_and_labelled():
    out = ok(inp("x", arr(["1/4", "2"])), op("s", "sqrt", "x")).values["s"]
    assert out.inexact and out.label is not None and "Arb" in " ".join(out.label.how)
    holds(out, [mp.mpf(1) / 2, mp.sqrt(2)])


def test_a_domain_is_still_refused_element_by_element():
    e = ev(inp("x", arr(["1/4", "-1"])), op("s", "sqrt", "x"))
    assert not e.ok and e.refusal["kind"] == "out_of_domain" and "[1]" in e.refusal["reason"]


def test_past_the_hosts_exact_limit_an_array_is_float64_as_before():
    tiny = L.Limits(max_exact_elements=2)
    out = ok(inp("x", arr(["1/4", "9/4", "4"])), op("s", "sqrt", "x"), limits=tiny).values["s"]
    assert out.inexact


def test_with_exact_angles_the_chord_is_exact_and_its_root_is_exactly_0_at_the_edge():
    e = ok(*chord(("0", "60", "90")), op("s", "sqrt", "cl"), result="s")
    assert e.values["cl"].kind == A.EXACT and e.values["cl"].data.tolist() == [0, Fraction(3, 4), 1]
    s = e.values["s"]  # sqrt(3/4) has no exact value: float64, its edge exactly 0
    assert s.inexact and s.data.tolist()[0] == 0.0 and s.error.tolist()[0] == 0.0


def test_the_exact_attempt_at_flo2_ios_exact_limit_keeps_within_its_deadline():
    n = L.FLO2_IO.max_exact_elements
    squares = [f"{k * k}/{(k + 1) ** 2}" for k in range(n)]
    started = time.perf_counter()
    out = ok(inp("x", arr(squares)), op("s", "sqrt", "x")).values["s"]
    assert out.kind == A.EXACT and out.size == n
    worst = squares[:-1] + ["2"]  # every element exact but the last: the attempt, then the float64 pass
    out = ok(inp("x", arr(worst)), op("s", "sqrt", "x")).values["s"]
    assert out.inexact
    assert time.perf_counter() - started < L.FLO2_IO.deadline_ms / 1000 / 2


# ---------------------------------------------------------------- C: an intermediate array is summarized in a reply

RANGE = graph(
    inp("a", "0"), inp("b", "1022"), op("n", "integer_range", "a", "b"), inp("three", "3"),
    op("big", "pow", "three", "n"), op("tot", "sum", "n"), inp("seven", "7"), op("p", "pow", "seven", "b"),
    op("q", "div", "three", "p"), op("res", "add", "tot", "q"), result="res",
)


def range_reply():
    e = evaluate(read_graph(RANGE, exact_limit=L.FLO2_IO.max_exact_elements), L.Guard(L.FLO2_IO))
    whole = evaluation_json(e)
    return whole, AN.fit(whole, L.FLO2_IO.max_answer_chars, "the record")


def test_an_intermediate_array_no_longer_crowds_out_the_values_after_it():
    whole, reply = range_reply()
    assert len(AN.text(reply)) <= L.FLO2_IO.max_answer_chars
    assert [v["node"] for v in reply["values"]] == [v["node"] for v in whole["values"]], "every value is shown"
    assert "values" not in reply["withheld"]


def test_a_summarized_array_keeps_its_shape_sha256_and_ends_and_says_where_the_rest_is():
    whole, reply = range_reply()
    full = {v["node"]: v for v in whole["values"]}
    shown = {v["node"]: v for v in reply["values"]}
    n = shown["n"]
    assert n["value"] == full["n"]["value"] and n["array"]["shape"] == [1023] and n["array"]["kind"] == "exact"
    assert n["array"]["sha256"] == full["n"]["array"]["sha256"], "the digest of the whole, as the record holds it"
    assert n["array"]["first"] == ["0", "1", "2"] and n["array"]["last"] == ["1020", "1021", "1022"]
    assert "values" not in n["array"]
    said = reply["withheld"]["values_summarized"]
    assert said["nodes"] == ["n", "big"] and "the record" in said["where"] and '"element"' in said["where"]
    assert shown["tot"] == full["tot"] and shown["res"] == full["res"], "single values are shown whole"
    assert reply["result"] == whole["result"], "the result is whole"


def test_a_result_array_and_a_short_intermediate_array_are_shown_whole():
    g = graph(inp("x", arr([str(k) for k in range(40)])), inp("k", "2"), op("y", "mul", "x", "k"),
              op("w", "integer_range", "k", "k"), op("z", "add", "y", "k"), result="z")
    e = evaluate(read_graph(g), L.Guard(L.FLO2_IO))
    whole = evaluation_json(e)
    reply = AN.fit(whole, L.FLO2_IO.max_answer_chars, "the record")
    shown = {v["node"]: v for v in reply["values"]}
    assert reply["result"] == whole["result"] and len(reply["result"]["array"]["values"]) == 40
    assert shown["z"]["array"]["values"] == whole["result"]["array"]["values"], "a result is never summarized"
    assert shown["w"]["array"]["values"] == ["2"], "a short array is shown whole"
    assert "values" not in shown["y"]["array"] and reply["withheld"]["values_summarized"]["nodes"] == ["x", "y"]


async def _evaluate_over_mcp(env):
    async with session(env=None if under_image() else env) as s:
        return await s.call_tool("evaluate_graph", {"graph": RANGE})


def test_evaluate_graph_summarizes_an_intermediate_array_over_mcp():
    from test_answer_budget import FLO2_IO_ENV

    answer = answer_of(anyio.run(_evaluate_over_mcp, FLO2_IO_ENV))
    assert [v["node"] for v in answer["values"]] == ["a", "b", "n", "three", "big", "tot", "seven", "p", "q", "res"]
    assert answer["withheld"]["values_summarized"]["nodes"] == ["n", "big"]
    assert "where" in answer["withheld"]["values_summarized"]


# ---------------------------------------------------------------- the records made before re-run as they were made


def test_a_version_12_record_made_by_0_14_0_re_runs_byte_for_byte_under_its_own_rules():
    """array-rules.v12.calc.json was made by flo2-calc 0.14.0 with every path 0.15.0 changes: max(raw, 0), min, abs
    and the greatest of a float64 array with an element either side of 0 (each then a symmetric ball), and sqrt and cos
    over exact arrays whose every element has an exact value (each then float64). It re-runs as it was made."""
    rec = json.loads((DATA / "array-rules.v12.calc.json").read_text())
    assert rec["schema_version"] == 12 and rec["produced_by"]["flo2_calc"] == "0.14.0"
    results = {r["node"]: r for r in rec["results"]}
    assert results["cl"]["array"]["values"][0] == "0.0" and results["sq"]["array"]["kind"] == "float64"
    answer = R.rerun(R.load(rec))
    assert answer["reproduces"] is True, answer["differences"]


def test_the_same_graph_recorded_now_keeps_its_bounds_one_sided_and_its_exact_arrays_exact():
    old = json.loads((DATA / "array-rules.v12.calc.json").read_text())
    e = evaluate(read_graph(old["graph"]), L.Guard())
    now = R.build(e, old["name"], old["supports"])
    assert now["schema_version"] == R.SCHEMA_VERSION == 13
    results = {r["node"]: r for r in now["results"]}
    assert results["sq"]["array"] == {**results["sq"]["array"], "kind": "exact", "values": ["0.5", "1.5"]}
    assert results["ct"]["array"]["values"] == ["1", "0"] and "float64" not in results["ct"]
    assert min(lower_ends(e.values["cl"])) >= 0 and min(lower_ends(e.values["ab"])) >= 0
    assert R.rerun(now)["reproduces"] is True
    assert np.all(e.values["lo"].data <= 1.0)


def test_a_version_12_record_is_re_derived_comparing_old_and_new_under_todays_rules():
    old = R.load(json.loads((DATA / "array-rules.v12.calc.json").read_text()))
    answer, new = RD.rederive(old, [{"input": "r", "value": "2 mm", "source": "a larger circle"}], L.Guard())
    assert answer["status"] == "ok" and new is not None and new["schema_version"] == 13
    assert "under today's rules" in answer["compared"]
    moved = {m["node"] for m in answer["moved"]}
    assert "cl" in moved and "sq" not in moved and "ct" not in moved, "only what the change moved, not the rules"
    assert R.rerun(new)["reproduces"] is True
