"""Arrays: values with one unit, element-wise operations, reductions, statistics over data, the FFT.

req:flo2-calc-computes-over-arrays and dec:idea-how-arrays-are-computed in design 0bee0c00b35845f6.
Checked against two independent oracles: numpy (the float64 values an agent would get from it) and
mpmath (the true values, at 50 digits or more), so every float64 bound flo2-calc states is shown to
hold. Exact results are checked against Python's own fractions.

ver:arrays-are-values-with-one-unit, ver:array-operations-match-numpy-and-the-truth,
ver:an-exact-array-stays-exact, ver:float64-is-labelled-and-its-bound-holds,
ver:a-regression-on-rational-data-is-exact, ver:the-fft-round-trips-within-its-bound,
ver:array-limits-hold and ver:array-records-re-run.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from fractions import Fraction

import jsonschema
import mpmath as mp
import numpy as np
import pytest
from conftest import graph, inp, op

from flo2_calc import arrays as A
from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph

mp.mp.dps = 50


def arr(values, unit=None):
    v = {"array": values}
    if unit is not None:
        v["unit"] = unit
    return v


def ev(*nodes, limits=L.LAPTOP, result=None, root=None):
    g = read_graph(graph(*nodes, result=result), data_root=root, exact_limit=limits.max_exact_elements)
    return evaluate(g, L.Guard(limits))


def value(*nodes, **kw):
    e = ev(*nodes, **kw)
    assert e.ok, e.refusal
    return e.values[e.graph.result]


def refusal(*nodes, **kw):
    e = ev(*nodes, **kw)
    assert not e.ok, "expected a refusal"
    return e.refusal


def answer(*nodes, **kw):
    return evaluation_json(ev(*nodes, **kw))


def texts(xs):
    return [str(x) for x in xs]


def truth_of(q):
    return mp.mpf(q.numerator) / q.denominator if isinstance(q, Fraction) else mp.mpf(q)


def holds(a: A.Array, truth: list) -> None:
    """Every element of a float64 array is within its stated bound of the true value."""
    assert a.inexact and a.label is not None
    flat_v = a.data.ravel().tolist()
    flat_e = a.error.ravel().tolist()
    for i, (v, e, t) in enumerate(zip(flat_v, flat_e, truth, strict=True)):
        d = abs(mp.mpc(v) - t) if isinstance(v, complex) else abs(mp.mpf(v) - t)
        assert d <= mp.mpf(e), f"element {i}: |{v} - {t}| = {d} > stated bound {e}"


# ---------------------------------------------------------------- an array is a value with one unit


def test_an_inline_array_is_exact_with_one_unit_and_the_record_keeps_it_as_written():
    x = value(inp("x", arr(["1", "2.5", "1/3", 7], "mm")))
    assert isinstance(x, A.Array) and x.kind == A.EXACT and x.shape == (4,)
    assert x.data.tolist() == [1, Fraction(5, 2), Fraction(1, 3), 7]
    g = read_graph(graph(inp("x", arr(["1", "2.5", "1/3", 7], "mm"))))
    assert g.to_json()["nodes"][0]["value"] == {"array": ["1", "2.5", "1/3", "7"], "unit": "mm"}
    shown = answer(inp("x", arr(["1", "2.5", "1/3"], "mm")))["result"]
    assert shown["array"]["values"] == ["1", "2.5", "1/3"] and shown["array"]["unit"] == "mm"
    assert shown["array"]["kind"] == "exact" and shown["array"]["shape"] == [3]
    assert shown["array"]["sha256"].startswith("sha256:") and "float64" not in shown


def test_a_grid_is_a_list_of_rows():
    g = value(inp("g", arr([["1", "2", "3"], ["4", "5", "6"]], "s")))
    assert g.shape == (2, 3) and g.data[1, 2] == 6


@pytest.mark.parametrize("bad, words", [
    ({"array": ["1 mm", "2"]}, "carries a unit of its own"),
    ({"array": ["1", "2+3"]}, "not a number"),
    ({"array": [0.1, 2]}, "fraction part"),
    ({"array": ["1", True]}, "all numbers or all true/false"),
    ({"array": [True, False], "unit": "mm"}, "no unit"),
    ({"array": [["1", "2"], ["3"]]}, "same length"),
    ({"array": [[["1"]]]}, "one or two dimensions"),
    ({"array": []}, "non-empty"),
    ({"array": ["1"], "unit": "furlongs"}, "not a unit"),
    ({"array": ["1"], "sha256": "00"}, "only a file array"),
    (["1", "2"], 'written {"array"'),
])
def test_a_malformed_array_is_a_malformed_call_naming_the_field(bad, words):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", bad)))
    assert caught.value.path.startswith("graph.nodes[0].value")
    assert words in caught.value.problem, caught.value.problem


def test_an_exchange_rate_array_needs_its_source_too():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("r", arr(["0.92", "0.93"], "EUR/USD"), source=None)))
    assert caught.value.path == "graph.nodes[0].source"


FLO2_IO_EXACT = L.Limits(max_exact_elements=4_096)  # flo2.io's exact limit, the image's ENV


def test_a_large_array_is_carried_in_float64_and_labelled_so():
    n = FLO2_IO_EXACT.max_exact_elements + 1
    x = value(inp("x", arr([str(i) for i in range(n - 1)] + ["0.1"])), limits=FLO2_IO_EXACT)
    assert x.kind == A.FLOAT64 and x.size == n
    assert A.how_large(4_096) in x.label.how
    assert x.error[:-1].max() == 0.0, "whole numbers are exact in float64"
    assert 0 < x.error[-1] <= 0.1 * 2**-53 and abs(Fraction(float(x.data[-1])) - Fraction(1, 10)) <= Fraction(float(x.error[-1]))
    shown = answer(inp("x", arr([str(i) for i in range(n)])), limits=FLO2_IO_EXACT)["result"]
    assert "values" not in shown["array"] and shown["array"]["first"][:3] == ["0.0", "1.0", "2.0"]
    assert shown["float64"]["error_at_most"] == "0"


def test_the_exact_limit_is_the_hosts_setting():
    """dec:v0-6-0-array-choices: 65,536 on a laptop, 4,096 in the image; past it, float64 and labelled."""
    assert L.LAPTOP.max_exact_elements == 65_536 and L.FLO2_IO.max_exact_elements == 4_096
    assert L.from_settings(None, None, None, None, "100").max_exact_elements == 100
    with pytest.raises(ValueError) as caught:
        L.from_settings(None, None, None, None, "0")
    assert "--max-exact-elements (or FLO2_CALC_MAX_EXACT_ELEMENTS)" in str(caught.value)
    data = [str(i) for i in range(5_000)]
    on_a_laptop = value(inp("x", arr(data)), inp("k", "3"), op("y", "mul", "x", "k"))
    assert on_a_laptop.kind == A.EXACT, "5,000 elements stay exact under a laptop's 65,536"
    hosted = value(inp("x", arr(data)), inp("k", "3"), op("y", "mul", "x", "k"), limits=FLO2_IO_EXACT)
    assert hosted.kind == A.FLOAT64 and A.how_large(4_096) in hosted.label.how
    grid = [inp("a", "0"), inp("b", "1"), inp("n", "100"), op("x", "linspace", "a", "b", "n"), op("c", "column", "x"), op("g", "mul", "c", "x")]
    assert value(*grid).kind == A.EXACT and value(*grid, limits=FLO2_IO_EXACT).kind == A.FLOAT64  # 10,000 elements
    assert value(*grid, limits=L.Limits(max_exact_elements=10_000)).kind == A.EXACT


# ---------------------------------------------------------------- arrays from files (local, under --root)


def test_a_file_array_is_read_under_the_root_and_the_record_keeps_its_sha256(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "grid.csv").write_text("# a grid\n1, 2, 3\n4 5 6\n")
    (tmp_path / "data" / "col.txt").write_text("0.5\n1.5\n2.5\n")
    np.save(tmp_path / "data" / "f.npy", np.array([0.1, 0.2]))
    g = read_graph(graph(inp("g", {"file": "data/grid.csv", "unit": "mm"}), inp("c", {"file": "data/col.txt"}), inp("f", {"file": "data/f.npy"})), data_root=tmp_path)
    nodes = {n.id: n for n in g.nodes}
    assert nodes["g"].value.shape == (2, 3) and nodes["g"].value.kind == A.EXACT
    assert nodes["c"].value.shape == (3,) and nodes["c"].value.data.tolist() == [Fraction(1, 2), Fraction(3, 2), Fraction(5, 2)]
    f = nodes["f"].value
    assert f.kind == A.FLOAT64 and f.error.max() == 0.0 and f.data.tolist() == [0.1, 0.2], "a .npy's doubles are taken as given"
    import hashlib

    kept = g.to_json()["nodes"][0]["value"]
    assert kept == {"file": "data/grid.csv", "sha256": hashlib.sha256((tmp_path / "data" / "grid.csv").read_bytes()).hexdigest(), "unit": "mm"}


def test_a_file_array_is_refused_with_no_root_outside_the_root_or_with_another_sha256(tmp_path):
    (tmp_path / "x.csv").write_text("1,2\n")
    with pytest.raises(A.DataUnavailable) as caught:
        read_graph(graph(inp("x", {"file": "x.csv"})))
    assert "no folder" in caught.value.problem and "inline" in caught.value.problem
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", {"file": "../x.csv"})), data_root=tmp_path / "sub")
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", {"file": "x.csv", "sha256": "0" * 64})), data_root=tmp_path)
    assert caught.value.path == "graph.nodes[0].value.sha256" and "not the data" in caught.value.problem
    (tmp_path / "bad.csv").write_text("1,2\n3\n")
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("x", {"file": "bad.csv"})), data_root=tmp_path)
    assert "same number of values" in caught.value.problem


# ---------------------------------------------------------------- broadcasting, strict about units


def test_shapes_broadcast_as_numpy_does_and_a_column_meets_a_row_as_a_grid():
    g = value(inp("y", arr(["1", "2"])), op("c", "column", "y"), inp("x", arr(["10", "20", "30"])), op("p", "mul", "c", "x"))
    assert g.shape == (2, 3) and g.data.tolist() == [[10, 20, 30], [20, 40, 60]]
    g2 = value(inp("g", arr([["1", "2", "3"], ["4", "5", "6"]])), inp("r", arr(["1", "1", "1"])), op("s", "add", "g", "r"))
    assert g2.data.tolist() == [[2, 3, 4], [5, 6, 7]]
    r = refusal(inp("a", arr(["1", "2", "3"])), inp("b", arr(["1", "2"])), op("s", "add", "a", "b"))
    assert r["kind"] == "shape_mismatch" and r["node"] == "s" and "column or transpose" in r["reason"]


def test_units_follow_the_single_value_rules_element_by_element():
    s = value(inp("a", arr(["1", "2"], "m")), inp("b", arr(["20", "50"], "cm")), op("s", "add", "a", "b"))
    assert s.unit == (("m", 1),) and s.data.tolist() == [Fraction(6, 5), Fraction(5, 2)]
    r = refusal(inp("a", arr(["1", "2"], "mm")), inp("b", "3 g"), op("s", "add", "a", "b"))
    assert r["kind"] == "unit_mismatch" and r["units"] == ["mm", "g"]
    p = value(inp("v", arr(["3.3", "5"], "V")), inp("i", "20 mA"), op("p", "mul", "v", "i"), op("w", "convert", "p", unit="mW"))
    assert p.unit == (("mW", 1),) and p.data.tolist() == [66, 100]
    r = refusal(inp("a", arr(["1", "2"], "mm")), inp("b", arr(["4", "0"])), op("q", "div", "a", "b"))
    assert r["kind"] == "division_by_zero" and "element [1]" in r["reason"]


def test_temperature_readings_keep_their_rules_element_by_element():
    t = value(inp("t", arr(["25", "30"], "degC")), inp("d", "5 K"), op("s", "add", "t", "d"))
    assert t.unit == (("degC", 1),) and t.data.tolist() == [30, 35]
    k = value(inp("t", arr(["0", "100"], "degC")), op("k", "convert", "t", unit="K"))
    assert k.data.tolist() == [Fraction(27315, 100), Fraction(37315, 100)]
    r = refusal(inp("t", arr(["25", "30"], "degC")), inp("two", "2"), op("m", "mul", "t", "two"))
    assert r["kind"] == "offset_temperature"
    r = refusal(inp("t", arr(["25", "30"], "degC")), op("s", "sum", "t"))
    assert r["kind"] == "offset_temperature"
    assert value(inp("t", arr(["25", "30"], "degC")), op("m", "mean", "t")).magnitude == Fraction(55, 2)


# ---------------------------------------------------------------- exact element-wise operations


RNG = random.Random(20261004)


def rationals(n, lo=-50, hi=50):
    return [Fraction(RNG.randint(lo, hi), RNG.randint(1, 12)) for _ in range(n)]


@pytest.mark.parametrize("name, fn", [
    ("add", lambda a, b: a + b), ("sub", lambda a, b: a - b), ("mul", lambda a, b: a * b),
    ("min", min), ("max", max),
])
def test_exact_element_wise_arithmetic_is_exact(name, fn):
    a, b = rationals(40), rationals(40)
    out = value(inp("a", arr(texts(a))), inp("b", arr(texts(b))), op("r", name, "a", "b"))
    assert out.kind == A.EXACT and out.label is None
    assert out.data.tolist() == [fn(x, y) for x, y in zip(a, b)]


def test_exact_division_powers_rounding_and_negation_stay_exact():
    a = [q for q in rationals(30) if q] or [Fraction(1)]
    b = [q for q in rationals(30) if q] or [Fraction(1)]
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    out = value(inp("a", arr(texts(a))), inp("b", arr(texts(b))), op("r", "div", "a", "b"))
    assert out.data.tolist() == [x / y for x, y in zip(a, b)]
    out = value(inp("a", arr(texts(a))), inp("k", "3"), op("r", "pow", "a", "k"))
    assert out.data.tolist() == [x**3 for x in a]
    out = value(inp("a", arr(texts(a))), inp("k", arr(["2"] * n)), op("r", "pow", "a", "k"))
    assert out.data.tolist() == [x**2 for x in a]
    out = value(inp("a", arr(texts(a))), op("r", "round", "a", places=1, mode="half_up"))
    assert out.kind == A.EXACT and all(abs(r - x) <= Fraction(1, 20) for r, x in zip(out.data.tolist(), a))
    assert value(inp("a", arr(["2.5", "-2.5"])), op("r", "round", "a")).data.tolist() == [2, -2]
    assert value(inp("a", arr(["1.5", "-1.5"])), op("r", "neg", "a")).data.tolist() == [Fraction(-3, 2), Fraction(3, 2)]
    assert value(inp("a", arr(["1.5", "-1.5"])), op("r", "abs", "a")).data.tolist() == [Fraction(3, 2), Fraction(3, 2)]
    r = refusal(inp("a", arr(["1", "0"])), inp("k", "-1"), op("r", "pow", "a", "k"))
    assert r["kind"] == "division_by_zero" and "element [1]" in r["reason"]
    r = refusal(inp("a", arr(["1", "2"], "m")), inp("k", arr(["2", "3"])), op("r", "pow", "a", "k"))
    assert r["kind"] == "unit_mismatch" and "one unit" in r["reason"]


def test_element_wise_logic_like_numpy():
    """Anthony's example: np.logical_or(arr < 3, arr > 12)."""
    xs = [RNG.randint(-5, 20) for _ in range(50)]
    nodes = [inp("a", arr(texts(xs))), inp("three", "3"), inp("twelve", "12"), op("lo", "lt", "a", "three"),
             op("hi", "gt", "a", "twelve"), op("either", "or", "lo", "hi")]
    either = value(*nodes)
    npa = np.array(xs)
    assert either.kind == A.BOOL and either.data.tolist() == np.logical_or(npa < 3, npa > 12).tolist()
    assert value(*nodes, op("n", "count_true", "either")).magnitude == int(np.logical_or(npa < 3, npa > 12).sum())
    assert value(*nodes, op("x", "xor", "lo", "hi")).data.tolist() == np.logical_xor(npa < 3, npa > 12).tolist()
    assert value(*nodes, op("x", "not", "lo")).data.tolist() == (~(npa < 3)).tolist()
    assert value(*nodes, op("x", "nor", "lo", "hi")).data.tolist() == (~np.logical_or(npa < 3, npa > 12)).tolist()
    assert value(*nodes, op("x", "any", "hi")) is bool((npa > 12).any())
    assert value(*nodes, op("x", "all", "either")) is bool(np.logical_or(npa < 3, npa > 12).all())
    assert value(*nodes, op("x", "eq", "lo", "hi")).data.tolist() == ((npa < 3) == (npa > 12)).tolist()
    r = refusal(inp("a", arr(["1"])), inp("t", True), op("x", "and", "a", "t"))
    assert r["kind"] == "type_mismatch"
    r = refusal(inp("t", arr([True, False])), op("s", "sum", "t"))
    assert r["kind"] == "type_mismatch" and "count_true" in r["reason"]


def test_count_true_counts_several_true_false_values_too():
    assert value(inp("a", True), inp("b", False), inp("c", True), op("n", "count_true", "a", "b", "c")).magnitude == 2


# ---------------------------------------------------------------- float64: functions over arrays


X = ["0.1", "0.5", "1", "2.5", "7/3", "10"]
P = ["0.01", "0.25", "0.5", "0.9", "0.999"]


@pytest.mark.parametrize("name, xs, unit, extra, truth, np_fn", [
    ("sqrt", X, None, {}, mp.sqrt, np.sqrt),
    ("exp", X, None, {}, mp.exp, np.exp),
    ("ln", X, None, {}, mp.log, np.log),
    ("log10", X, None, {}, mp.log10, np.log10),
    ("sin", ["0", "30", "45", "89.5", "200"], "deg", {}, lambda x: mp.sin(x * mp.pi / 180), lambda x: np.sin(np.radians(x))),
    ("cos", X, "rad", {}, mp.cos, np.cos),
    ("tan", ["0.1", "1", "1.5"], "rad", {}, mp.tan, np.tan),
    ("asin", ["-1", "-0.5", "0.3", "1"], None, {"unit": "deg"}, lambda x: mp.asin(x) * 180 / mp.pi, lambda x: np.degrees(np.arcsin(x))),
    ("acos", ["-1", "0.3", "1"], None, {"unit": "rad"}, mp.acos, np.arccos),
    ("atan", X, None, {"unit": "rad"}, mp.atan, np.arctan),
    ("normal_cdf", ["-3", "0", "1.5"], None, {}, mp.ncdf, None),
    ("normal_sf", ["-3", "0", "8"], None, {}, lambda x: 1 - mp.ncdf(x) if x < 5 else mp.erfc(x / mp.sqrt(2)) / 2, None),
    ("normal_quantile", P, None, {}, lambda p: mp.sqrt(2) * mp.erfinv(2 * p - 1), None),
])
def test_a_function_over_an_array_is_float64_labelled_and_its_bound_holds(name, xs, unit, extra, truth, np_fn):
    out = value(inp("x", arr(xs, unit)), op("y", name, "x", **extra))
    assert out.kind == A.FLOAT64 and out.label.origins == ("y",)
    assert any(name in h and "Arb" in h for h in out.label.how)
    exact = [Fraction(t) if "/" not in t else Fraction(t) for t in xs]
    holds(out, [truth(truth_of(q)) for q in exact])
    if np_fn is not None:  # the value an agent would get from numpy, to a few units in the last place
        expect = np_fn(np.array([float(q) for q in exact]))
        assert np.allclose(out.data, expect, rtol=8 * 2**-52, atol=1e-300)
    assert out.error.max() < 1e-14 * max(1.0, float(np.max(np.abs(out.data))))


def test_more_functions_over_arrays_atan2_pow_chi2_t_and_deg_to_rad():
    out = value(inp("y", arr(["1", "-1", "0", "2"], "mm")), inp("x", arr(["1", "1", "-3", "0"], "mm")), op("a", "atan2", "y", "x", unit="deg"))
    holds(out, [mp.mpf(45), mp.mpf(-45), mp.mpf(180), mp.mpf(90)])
    out = value(inp("x", arr(["2", "9", "0.5"])), inp("k", "0.5"), op("p", "pow", "x", "k"))
    holds(out, [mp.sqrt(2), mp.mpf(3), mp.sqrt(mp.mpf(1) / 2)])
    out = value(inp("x", arr(["4", "9"], "m^2")), inp("k", "1/2"), op("p", "pow", "x", "k"))
    assert out.unit == (("m", 1),)
    out = value(inp("x", arr(["1", "3.84", "10"])), inp("k", "1"), op("c", "chi2_sf", "x", "k"))
    holds(out, [mp.erfc(mp.sqrt(truth_of(Fraction(s)) / 2)) for s in ("1", "3.84", "10")])
    out = value(inp("p", arr(["0.975", "0.5", "0.05"])), inp("k", "4"), op("t", "t_quantile", "p", "k"))
    def t_truth(p):
        q = min(p, 1 - p)
        t = mp.findroot(lambda t: mp.betainc(2, mp.mpf(1) / 2, 0, 4 / (4 + t * t), regularized=True) / 2 - q, 2)
        return t if p > 0.5 else -t

    holds(out, [t_truth(mp.mpf("0.975")), mp.mpf(0), t_truth(mp.mpf("0.05"))])
    assert out.data[1] == 0.0
    out = value(inp("a", arr(["180", "90", "0"], "deg")), op("r", "convert", "a", unit="rad"))
    holds(out, [mp.pi, mp.pi / 2, mp.mpf(0)])


@pytest.mark.parametrize("nodes, kind, words", [
    ((inp("x", arr(["4", "-1"])), op("y", "sqrt", "x")), "out_of_domain", "element [1]"),
    ((inp("x", arr(["1", "0"])), op("y", "ln", "x")), "out_of_domain", "element [1]"),
    ((inp("x", arr(["0.5", "2"])), op("y", "asin", "x", unit="deg")), "out_of_domain", "element [1]"),
    ((inp("x", arr(["45", "90"], "deg")), op("y", "tan", "x")), "undefined", "element [1]"),
    ((inp("x", arr(["1", "2"], "mm")), op("y", "exp", "x")), "unit_mismatch", "never dropped"),
    ((inp("x", arr(["1", "2"])), op("y", "sin", "x")), "unit_mismatch", "angle"),
    ((inp("x", arr(["1", "2"], "m")), op("y", "sqrt", "x")), "unit_mismatch", "square root"),
    ((inp("x", arr(["-8", "2"])), inp("k", "1/3"), op("y", "pow", "x", "k")), "out_of_domain", "element [0]"),
    ((inp("y", arr(["0", "1"])), inp("x", arr(["0", "1"])), op("a", "atan2", "y", "x", unit="deg")), "undefined", "origin"),
])
def test_a_function_outside_its_domain_or_units_is_refused_naming_the_element(nodes, kind, words):
    r = refusal(*nodes)
    assert r["kind"] == kind and words in r["reason"], r


def test_an_exact_array_stays_exact_and_mixing_in_float64_or_a_rounded_value_gives_float64_labelled():
    x = ["1", "2", "3"]
    exact = value(inp("x", arr(x, "mm")), inp("k", "1/7"), op("y", "mul", "x", "k"), op("z", "sub", "y", "x"))
    assert exact.kind == A.EXACT and exact.label is None
    mixed = value(inp("x", arr(x)), op("e", "exp", "x"), inp("y", arr(["1/3", "1/3", "1/3"])), op("s", "add", "e", "y"))
    assert mixed.kind == A.FLOAT64 and mixed.label.origins == ("e", "s"), "float64 entered at e, and the exact y at s"
    assert A.HOW_ARITH in mixed.label.how and A.HOW_TAKEN in mixed.label.how
    holds(mixed, [mp.exp(k) + mp.mpf(1) / 3 for k in (1, 2, 3)])
    with_pi = value(inp("x", arr(x, "mm")), op("pi", "pi"), op("c", "mul", "x", "pi"))
    assert with_pi.kind == A.FLOAT64 and set(with_pi.label.origins) == {"pi", "c"} and A.HOW_ROUNDED_IN in with_pi.label.how
    holds(with_pi, [k * mp.pi for k in (1, 2, 3)])
    shown = answer(inp("x", arr(x)), op("e", "exp", "x"))
    assert shown["result"]["float64"]["from"] == ["e"] and "float64" in shown["exactness"]


def test_float64_arithmetic_carries_its_bound_through_a_chain():
    xs = ["0.1", "1.7", "-2.3", "5", "123.456"]
    out = value(inp("x", arr(xs)), op("e", "exp", "x"), inp("k", "3.3"), op("m", "mul", "e", "k"), inp("c", "1/7"),
                op("d", "div", "m", "c"), op("s", "sub", "d", "x"), op("q", "neg", "s"))
    holds(out, [-(mp.exp(truth_of(Fraction(t))) * mp.mpf("3.3") * 7 - truth_of(Fraction(t))) for t in xs])


def test_a_float64_comparison_is_answered_only_where_the_bound_decides_it():
    two = value(inp("x", arr(["2", "3"])), op("r", "sqrt", "x"), op("s", "mul", "r", "r"), inp("lim", "10"), op("c", "lt", "s", "lim"))
    assert two.data.tolist() == [True, True]
    r = refusal(inp("x", arr(["2", "3"])), op("r", "sqrt", "x"), op("s", "mul", "r", "r"), inp("two", "2"), op("c", "eq", "s", "two"))
    assert r["kind"] == "undecidable" and "element [0]" in r["reason"]
    fl = value(inp("x", arr(["2", "10"])), op("r", "sqrt", "x"), op("f", "floor", "r"))
    assert fl.kind == A.EXACT and fl.data.tolist() == [1, 3], "decided: exact, and true of the true value"
    # sqrt(2) * sqrt(2) is 2 exactly, but its float64 value's bound straddles 2: floor is not decided.
    r = refusal(inp("x", arr(["2"])), op("r", "sqrt", "x"), op("p", "mul", "r", "r"), op("f", "floor", "p"))
    assert r["kind"] == "undecidable" and "element [0]" in r["reason"]


# ---------------------------------------------------------------- reductions


def test_reductions_of_exact_data_are_exact_with_an_axis_for_a_grid():
    xs = rationals(30, 1, 40)
    nodes = [inp("x", arr(texts(xs), "g"))]
    assert value(*nodes, op("s", "sum", "x")).magnitude == sum(xs)
    assert value(*nodes, op("m", "mean", "x")).magnitude == sum(xs) / len(xs)
    assert value(*nodes, op("m", "min", "x")).magnitude == min(xs)
    assert value(*nodes, op("m", "max", "x")).magnitude == max(xs)
    assert value(*nodes, op("i", "argmax", "x")).magnitude == xs.index(max(xs))
    assert value(*nodes, op("i", "argmin", "x")).magnitude == xs.index(min(xs))
    assert value(inp("p", arr(["1/2", "3", "4"])), op("s", "product", "p")).magnitude == 6
    grid = [["1", "2", "3"], ["4", "5", "6"]]
    assert value(inp("g", arr(grid, "mm")), op("s", "sum", "g", axis=0)).data.tolist() == [5, 7, 9]
    assert value(inp("g", arr(grid, "mm")), op("s", "sum", "g", axis=1)).data.tolist() == [6, 15]
    assert value(inp("g", arr(grid)), op("s", "max", "g", axis=0)).data.tolist() == [4, 5, 6]
    assert value(inp("g", arr(grid)), inp("k", "3"), op("b", "gt", "g", "k"), op("c", "count_true", "b", axis=1)).data.tolist() == [0, 3]
    r = refusal(inp("x", arr(["1", "2"], "mm")), op("p", "product", "x"))
    assert r["kind"] == "unit_mismatch"
    r = refusal(inp("x", "2"), op("s", "sum", "x"))
    assert r["kind"] == "type_mismatch"
    r = refusal(inp("x", "2"), op("s", "min", "x"))
    assert r["kind"] == "type_mismatch"
    with pytest.raises(CallError):
        read_graph(graph(inp("x", arr(["1"])), op("s", "sqrt", "x", axis=0)))


def test_a_float64_sum_is_fsum_and_its_bound_holds():
    xs = ["1e16", "1", "-1e16", "0.1", "3"]  # cancellation: a naive float64 sum loses the 1
    floats = [inp("x", arr(xs)), op("pi", "pi"), op("one", "div", "pi", "pi"), op("l", "mul", "x", "one")]  # float64 copies
    out = value(*floats, op("s", "sum", "l"))
    assert out.shape == () and out.kind == A.FLOAT64
    holds(out, [sum(truth_of(Fraction(t)) for t in xs)])
    assert abs(float(out.data) - 4.1) < 1e-14
    m = value(*floats, op("s", "mean", "l"))
    holds(m, [sum(truth_of(Fraction(t)) for t in xs) / 5])


def test_the_discretised_integral_is_a_few_nodes_and_matches_numpy_and_the_truth():
    """Anthony's np.sum(np.sum(f(x0, y0) * np.exp(...))): a 32 x 32 grid built from two axes."""
    n = 32
    nodes = [
        inp("lo", "-2 mm"), inp("hi", "2 mm"), inp("n", str(n)),
        op("x", "linspace", "lo", "hi", "n"), op("y0", "linspace", "lo", "hi", "n"), op("y", "column", "y0"),
        op("x2", "mul", "x", "x"), op("y2", "mul", "y", "y"), op("r2", "add", "x2", "y2"),
        inp("w", "1 mm^2"), op("q", "div", "r2", "w"), op("mq", "neg", "q"), op("g", "exp", "mq"),
        op("f", "mul", "x2", "g"), op("total", "sum", "f"),
    ]
    out = value(*nodes)
    assert out.shape == () and out.unit == (("mm", 2),)
    grid = [Fraction(-2) + Fraction(4, n - 1) * k for k in range(n)]
    truth = mp.fsum(truth_of(a) ** 2 * mp.exp(-(truth_of(a) ** 2 + truth_of(b) ** 2)) for a in grid for b in grid)
    holds(out, [truth])
    g = np.linspace(-2, 2, n)
    X, Y = np.meshgrid(g, g)
    assert abs(float(out.data) - float(np.sum(np.sum(X**2 * np.exp(-(X**2 + Y**2)))))) < 1e-12
    axis = value(*nodes[:-1], op("rows", "sum", "f", axis=1))
    assert axis.shape == (n,)
    holds(axis, [mp.fsum(truth_of(a) ** 2 * mp.exp(-(truth_of(a) ** 2 + truth_of(b) ** 2)) for a in grid) for b in grid])


# ---------------------------------------------------------------- statistics over data


def test_variance_and_sd_are_named_sample_or_population_and_exact_where_they_can_be():
    xs = rationals(25, 1, 100)
    t = texts(xs)
    v_s = value(inp("x", arr(t, "mm")), op("v", "variance_sample", "x"))
    v_p = value(inp("x", arr(t, "mm")), op("v", "variance_population", "x"))
    assert v_s.magnitude == statistics.variance(xs) and v_s.unit == (("mm", 2),) and v_s.rounding is None
    assert v_p.magnitude == statistics.pvariance(xs)
    sd = value(inp("x", arr(t, "mm")), op("s", "sd_sample", "x"))
    assert sd.unit == (("mm", 1),) and sd.rounding.correctly_rounded
    assert abs(truth_of(sd.magnitude) - mp.sqrt(truth_of(statistics.variance(xs)))) <= truth_of(sd.rounding.error)
    sdp = value(inp("x", arr(["2", "4", "4", "4", "5", "5", "7", "9"])), op("s", "sd_population", "x"))
    assert sdp.magnitude == 2 and sdp.rounding is None, "a perfect square stays exact"
    assert abs(float(sd.magnitude) - float(np.std(np.array([float(q) for q in xs]), ddof=1))) < 1e-12
    r = refusal(inp("x", arr(["3"])), op("v", "variance_sample", "x"))
    assert r["kind"] == "undefined" and "n - 1" in r["reason"]
    with pytest.raises(CallError):
        read_graph(graph(inp("x", arr(["1", "2"])), op("v", "variance", "x")))


def q063_style():
    t = [str(2 * k) for k in range(6)]
    y = ["0.0000", "0.0291", "0.0574", "0.0868", "0.1152", "0.1447"]
    return t, y


def test_a_regression_on_rational_data_gives_an_exact_slope_and_correctly_rounded_standard_errors():
    t, y = q063_style()
    nodes = [inp("t", arr(t, "s")), inp("y", arr(y, "deg"))]
    tx = [Fraction(v) for v in t]
    yx = [Fraction(v) for v in y]
    n = len(tx)
    tm, ym = sum(tx) / n, sum(yx) / n
    sxx = sum((a - tm) ** 2 for a in tx)
    sxy = sum((a - tm) * (b - ym) for a, b in zip(tx, yx))
    b = sxy / sxx
    a = ym - b * tm
    ssr = sum((yy - a - b * xx) ** 2 for xx, yy in zip(tx, yx))
    s2 = ssr / (n - 2)
    slope = value(*nodes, op("b", "fit_slope", "t", "y"))
    assert slope.magnitude == b == Fraction(316, 21875) and slope.unit == (("deg", 1), ("s", -1)) and slope.rounding is None
    assert value(*nodes, op("a", "fit_intercept", "t", "y")).magnitude == a
    for name, sq in (("fit_slope_se", s2 / sxx), ("fit_intercept_se", s2 * (Fraction(1, n) + tm * tm / sxx)), ("fit_residual_se", s2)):
        se = value(*nodes, op("se", name, "t", "y"))
        assert se.rounding is not None and se.rounding.correctly_rounded and se.rounding.digits == 30
        assert abs(truth_of(se.magnitude) - mp.sqrt(truth_of(sq))) <= truth_of(se.rounding.error), name
    # numpy's polyfit, the oracle an agent would reach for: the same slope and standard error to float64
    coef, cov = np.polyfit([float(v) for v in tx], [float(v) for v in yx], 1, cov="unscaled")
    resid = np.array([float(v) for v in yx]) - np.polyval(coef, [float(v) for v in tx])
    s2f = float(resid @ resid) / (n - 2)
    se_np = math.sqrt(cov[0, 0] * s2f)
    assert abs(coef[0] - float(b)) < 1e-15
    se = value(*nodes, op("se", "fit_slope_se", "t", "y"))
    assert abs(float(se.magnitude) - se_np) < 1e-15


def test_a_fit_is_refused_where_it_has_no_answer():
    r = refusal(inp("x", arr(["1", "1", "1"])), inp("y", arr(["1", "2", "3"])), op("b", "fit_slope", "x", "y"))
    assert r["kind"] == "undefined" and "same" in r["reason"]
    r = refusal(inp("x", arr(["1", "2"])), inp("y", arr(["1", "2"])), op("b", "fit_slope_se", "x", "y"))
    assert r["kind"] == "undefined" and "n - 2" in r["reason"]
    r = refusal(inp("x", arr(["1", "2", "3"])), inp("y", arr(["1", "2"])), op("b", "fit_slope", "x", "y"))
    assert r["kind"] == "shape_mismatch"
    perfect = value(inp("x", arr(["1", "2", "3"])), inp("y", arr(["3", "5", "7"])), op("s", "fit_slope_se", "x", "y"))
    assert perfect.magnitude == 0 and perfect.rounding is None


def test_statistics_over_float64_data_are_labelled_and_their_bounds_hold():
    xs = ["0.5", "1", "1.5", "2", "2.5", "3"]
    nodes = [inp("x", arr(xs)), op("e", "exp", "x"), op("l", "ln", "e")]  # float64 copies of xs
    ys = [truth_of(Fraction(v)) for v in xs]
    yb = mp.fsum(ys) / len(ys)
    var_s = mp.fsum((v - yb) ** 2 for v in ys) / (len(ys) - 1)
    out = value(*nodes, op("v", "variance_sample", "l"))
    assert out.kind == A.FLOAT64 and out.label.origins[-1] == "v"
    holds(out, [var_s])
    holds(value(*nodes, op("s", "sd_sample", "l")), [mp.sqrt(var_s)])
    ex = [truth_of(Fraction(v)) for v in xs]
    eys = [mp.exp(v) for v in ex]
    xm, ym = mp.fsum(ex) / 6, mp.fsum(eys) / 6
    slope = mp.fsum((a - xm) * (b - ym) for a, b in zip(ex, eys)) / mp.fsum((a - xm) ** 2 for a in ex)
    holds(value(*nodes, op("b", "fit_slope", "x", "e")), [slope])


# ---------------------------------------------------------------- the FFT


def dft(xs, inverse=False):
    n = len(xs)
    sign = 1 if inverse else -1
    out = [mp.fsum(xs[k] * mp.expjpi(sign * 2 * mp.mpf(j * k % n) / n) for k in range(n)) for j in range(n)]
    return [v / n for v in out] if inverse else out


@pytest.mark.parametrize("n", [1, 2, 3, 5, 7, 8, 12, 16, 17, 31, 64, 100, 127, 128])
def test_the_fft_is_numpys_value_and_within_its_stated_bound_of_the_exact_dft(n):
    xs = [Fraction(RNG.randint(-1000, 1000), RNG.choice([1, 3, 7, 10])) for _ in range(n)]
    out = value(inp("x", arr(texts(xs), "V")), op("f", "fft", "x"))
    assert out.kind == A.COMPLEX and out.unit == (("V", 1),)
    assert np.array_equal(out.data, np.fft.fft(np.array([float(q) for q in xs], dtype=complex))), "numpy's own value"
    holds(out, dft([truth_of(q) for q in xs]))
    how = " ".join(out.label.how)
    if n & (n - 1) == 0:
        assert "Higham" in how and "Theorem 24.2" in how
    else:
        assert "Arb" in how and "acb_dft" in how


def test_the_fft_round_trips_within_its_bound():
    for n in (8, 100, 256):
        xs = [Fraction(RNG.randint(-10**6, 10**6), 1000) for _ in range(n)]
        back = value(inp("x", arr(texts(xs), "mm")), op("f", "fft", "x"), op("b", "ifft", "f"), op("r", "real", "b"))
        assert back.kind == A.FLOAT64
        holds(back, [truth_of(q) for q in xs])
        assert back.error.max() < 1e-12 * max(abs(float(q)) for q in xs), back.error.max()


def test_the_fft_bound_holds_on_a_wide_dynamic_range():
    xs = ["1e12", "1e-12", "-3", "7.5e6", "1/3", "2", "-1e9", "5"]
    out = value(inp("x", arr(xs)), op("f", "fft", "x"))
    holds(out, dft([truth_of(Fraction(v)) for v in xs]))


def test_the_2d_fft_matches_numpy_and_the_exact_dft():
    for m, n in ((4, 4), (3, 5), (8, 6)):
        g = [[Fraction(RNG.randint(-99, 99), 4) for _ in range(n)] for _ in range(m)]
        out = value(inp("g", arr([texts(r) for r in g])), op("f", "fft2", "g"))
        assert np.array_equal(out.data, np.fft.fft2(np.array([[float(q) for q in r] for r in g], dtype=complex)))
        rows = [dft([truth_of(q) for q in r]) for r in g]
        cols = [dft([rows[i][j] for i in range(m)]) for j in range(n)]
        holds(out, [cols[j][i] for i in range(m) for j in range(n)])
        back = value(inp("g", arr([texts(r) for r in g])), op("f", "fft2", "g"), op("b", "ifft2", "f"), op("r", "real", "b"))
        holds(back, [truth_of(q) for r in g for q in r])


def test_the_stated_fft_bound_is_highams_doubled():
    u = 2.0**-53
    mu = 8 * u
    eta = mu + 4 * u / (1 - 4 * u) * (math.sqrt(2) + mu)
    assert A.higham_bound(8) == pytest.approx(2 * 8 * eta / (1 - 8 * eta), rel=1e-9)
    assert 3e-14 < A.higham_bound(16) < 6e-14  # a 256 x 256 grid: t = 16


def test_abs_phase_real_imag_and_conj_take_a_spectrum_apart():
    xs = ["1", "0", "-1", "0"]
    f = value(inp("x", arr(xs)), op("f", "fft", "x"))
    mag = value(inp("x", arr(xs)), op("f", "fft", "x"), op("m", "abs", "f"))
    assert np.allclose(mag.data, np.abs(f.data)) and mag.kind == A.FLOAT64
    holds(mag, [mp.mpf(0), mp.mpf(2), mp.mpf(0), mp.mpf(2)])
    ph = value(inp("x", arr(["1", "-2", "3"])), op("p", "phase", "x", unit="deg"))
    assert ph.data.tolist() == [0.0, 180.0, 0.0] and ph.error.max() == 0
    r = refusal(inp("x", arr(xs)), op("f", "fft", "x"), op("p", "phase", "f", unit="deg"))
    assert r["kind"] in ("undecidable", "undefined") and "element" in r["reason"]
    one = value(inp("x", arr(xs)), op("f", "fft", "x"), inp("i", "1"), op("b", "element", "f", "i"), op("p", "phase", "b", unit="deg"))
    holds(one, [mp.mpf(0)])
    conj = value(inp("x", arr(["1", "2", "3"])), op("f", "fft", "x"), op("c", "conj", "f"), op("i", "imag", "c"))
    assert np.allclose(conj.data, -np.fft.fft([1.0, 2, 3]).imag)
    r = refusal(inp("x", arr(xs)), op("f", "fft", "x"), op("s", "sqrt", "f"))
    assert r["kind"] == "type_mismatch" and "abs" in r["reason"]


def test_a_circular_convolution_through_the_fft_is_within_its_bound():
    a = [Fraction(k, 3) for k in (1, 2, 0, -1, 4, 0, 0, 2)]
    b = [Fraction(k, 2) for k in (3, 0, 1, 0, 0, 0, -1, 1)]
    n = len(a)
    conv = [sum(a[k] * b[(j - k) % n] for k in range(n)) for j in range(n)]
    out = value(inp("a", arr(texts(a), "V")), inp("b", arr(texts(b), "A")), op("fa", "fft", "a"), op("fb", "fft", "b"),
                op("p", "mul", "fa", "fb"), op("c", "ifft", "p"), op("r", "real", "c"))
    assert out.unit == (("V", 1), ("A", 1))
    holds(out, [truth_of(q) for q in conv])


def test_an_fft_refuses_what_it_cannot_take():
    assert refusal(inp("g", arr([["1", "2"], ["3", "4"]])), op("f", "fft", "g"))["kind"] == "shape_mismatch"
    assert refusal(inp("x", arr(["1", "2"])), op("f", "fft2", "x"))["kind"] == "shape_mismatch"
    assert refusal(inp("x", arr([True, False])), op("f", "fft", "x"))["kind"] == "type_mismatch"
    assert refusal(inp("x", "3"), op("f", "fft", "x"))["kind"] == "type_mismatch"


# ---------------------------------------------------------------- making and shaping arrays


def test_linspace_column_transpose_and_element():
    x = value(inp("a", "0 s"), inp("b", "1 s"), inp("n", "5"), op("x", "linspace", "a", "b", "n"))
    assert x.kind == A.EXACT and x.data.tolist() == [0, Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), 1]
    t = value(inp("g", arr([["1", "2", "3"], ["4", "5", "6"]])), op("t", "transpose", "g"))
    assert t.shape == (3, 2) and t.data.tolist() == [[1, 4], [2, 5], [3, 6]]
    e = value(inp("g", arr([["1", "2", "3"], ["4", "5", "6"]], "mm")), inp("r", "1"), inp("c", "2"), op("e", "element", "g", "r", "c"))
    assert e.magnitude == 6 and e.unit == (("mm", 1),)
    assert refusal(inp("g", arr(["1", "2"])), inp("i", "2"), op("e", "element", "g", "i"))["kind"] == "out_of_domain"
    lp = value(op("pi", "pi"), op("m", "neg", "pi"), inp("n", "5"), op("x", "linspace", "m", "pi", "n"))
    assert lp.kind == A.FLOAT64 and "pi" in lp.label.origins
    holds(lp, [-mp.pi + mp.pi / 2 * k for k in range(5)])


# ---------------------------------------------------------------- the host's limits


def test_an_array_past_the_hosts_budget_is_refused_before_it_is_made():
    small = L.Limits(max_array_bytes=256 * 1024)
    r = refusal(inp("a", "0"), inp("b", "1"), inp("n", "400"), op("x", "linspace", "a", "b", "n"), op("c", "column", "x"),
                op("g", "mul", "c", "x"), limits=small)
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_array_bytes" and r["node"] == "g"
    assert "was not made" in r["reason"] and r["limit"]["setting"] == "--max-array-bytes or FLO2_CALC_MAX_ARRAY_BYTES"
    assert r["limits"]["max_array_bytes"] == 256 * 1024


def test_a_long_array_computation_is_stopped_at_the_deadline():
    clock = iter(range(0, 10**12, 10**6))  # every check moves the clock on a millisecond
    guard = L.Guard(L.Limits(deadline_ms=50), clock=lambda: next(clock))
    e = evaluate(read_graph(graph(inp("a", "0"), inp("b", "1"), inp("n", "50000"), op("x", "linspace", "a", "b", "n"), op("y", "exp", "x"))), guard)
    assert e.refusal["kind"] == "exceeds_limits" and e.refusal["limit"]["name"] == "deadline"


def test_an_exact_element_past_the_digits_budget_is_stopped():
    r = refusal(inp("x", arr(["123456789", "2"])), inp("k", "40"), op("p", "pow", "x", "k"), limits=L.Limits(max_digits=100))
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_digits"


# ---------------------------------------------------------------- records


REGRESSION = graph(
    inp("t", arr(q063_style()[0], "s"), "frame times"),
    inp("y", arr(q063_style()[1], "deg"), "along-track angles, frames 1 to 6"),
    op("slope", "fit_slope", "t", "y"), op("slope_se", "fit_slope_se", "t", "y"),
    inp("x", arr(["1", "2", "3", "4", "5", "6", "7"]), "test"), op("f", "fft", "x"), op("m", "abs", "f"),
    op("peak", "max", "m"),
    result="slope_se",
)


def make(g=REGRESSION, root=None, name="arrays"):
    e = evaluate(read_graph(g, data_root=root), L.Guard())
    assert e.ok, e.refusal
    return R.build(e, name, "dec:test")


def test_a_record_with_arrays_fits_its_schema_and_re_runs():
    rec = make()
    assert rec["schema_version"] == 6 and rec["produced_by"]["numpy"] == np.__version__
    jsonschema.validate(rec, R.schema(6))
    assert "ARRAY" in rec["arithmetic"]
    t_input = next(i for i in rec["inputs"] if i["id"] == "t")
    assert t_input["array"]["shape"] == [6] and "values" not in t_input["array"] and t_input["unit"] == "s"
    by = {v["node"]: v for v in rec["values"]}
    assert by["f"]["float64"]["from"] == ["f"] and "Arb" in " ".join(by["f"]["float64"]["how"])
    assert by["peak"]["float64"]["error_at_most"]
    assert R.rerun(rec)["reproduces"] is True
    assert R.file_bytes(make()) == R.file_bytes(rec), "the same graph gives the same file, FFT and Arb included"


def test_the_content_hash_covers_an_inline_arrays_data():
    rec = make()
    tampered = json.loads(json.dumps(rec))
    tampered["graph"]["nodes"][1]["value"]["array"][3] = "0.0869"
    again = R.rerun(tampered)
    assert again["reproduces"] is False and again["content_hash"]["matches"] is False
    tampered["content_hash"] = R.content_hash(tampered)
    again = R.rerun(tampered)
    assert again["reproduces"] is False and {d["field"] for d in again["differences"]} >= {"inputs", "result"}


def test_a_large_result_is_kept_as_its_sha256_and_re_running_compares_it():
    g = graph(inp("a", "0", "s"), inp("b", "1", "s"), inp("n", "2000", "s"), op("x", "linspace", "a", "b", "n"), op("e", "exp", "x"))
    rec = make(g)
    e_val = next(v for v in rec["values"] if v["node"] == "e")
    assert "values" not in e_val["array"] and e_val["array"]["sha256"].startswith("sha256:") and len(e_val["array"]["first"]) == 8
    assert R.rerun(rec)["reproduces"] is True
    bad = json.loads(json.dumps(rec))
    for v in bad["values"]:
        if v["node"] == "e":
            v["array"]["sha256"] = "sha256:" + "0" * 64
    bad["content_hash"] = R.content_hash(bad)
    again = R.rerun(bad)
    assert again["reproduces"] is False and any(d["field"] == "values[e]" for d in again["differences"])


def test_a_file_arrays_record_re_runs_where_the_file_is_and_says_so_where_it_is_not(tmp_path):
    (tmp_path / "y.csv").write_text("\n".join(q063_style()[1]) + "\n")
    g = graph(inp("t", arr(q063_style()[0], "s"), "frame times"), inp("y", {"file": "y.csv", "unit": "deg"}, "measurements"),
              op("b", "fit_slope", "t", "y"))
    rec = make(g, root=tmp_path)
    jsonschema.validate(rec, R.schema(6))
    assert rec["result"]["exact"] == "316/21875 deg/s"
    assert R.rerun(rec, data_root=tmp_path)["reproduces"] is True
    elsewhere = R.rerun(rec)
    assert elsewhere["status"] == "refused" and elsewhere["reproduces"] is None and elsewhere["refused"]["kind"] == "data_unavailable"
    assert "neither confirmed nor contradicted" in elsewhere["verdict"]
    (tmp_path / "y.csv").write_text("\n".join(q063_style()[1][:-1] + ["0.1448"]) + "\n")
    changed = R.rerun(rec, data_root=tmp_path)
    assert changed["reproduces"] is False and "sha256" in json.dumps(changed["differences"])


def test_a_not_yet_computed_record_with_arrays_completes_to_the_direct_record():
    g = graph(inp("a", "0", "s"), inp("b", "1", "s"), inp("n", "5000", "s"), op("x", "linspace", "a", "b", "n"), op("e", "exp", "x"),
              op("s", "sum", "e"))
    small = L.Limits(max_array_bytes=64 * 1024)
    e = evaluate(read_graph(g), L.Guard(small))
    assert e.stopped and e.refusal["limit"]["name"] == "max_array_bytes"
    pending = R.build_pending(e.graph, "big", None, e.refusal, small)
    jsonschema.validate(pending, R.schema(6))
    done = evaluate(read_graph(pending["graph"]), L.Guard())
    direct = evaluate(read_graph(g), L.Guard())
    assert R.file_bytes(R.build(done, "big", None)) == R.file_bytes(R.build(direct, "big", None))


# ---------------------------------------------------------------- flo2-calc 0.5.0's additions, over arrays


def test_count_true_and_k_of_n_take_a_true_false_array():
    nodes = [inp("x", arr(["1", "5", "13", "2", "20"])), inp("lim", "12"), op("hi", "gt", "x", "lim")]
    assert value(*nodes, op("n", "count_true", "hi")).magnitude == 2
    assert value(*nodes, inp("k", "2"), op("v", "k_of_n", "k", "hi")) is True
    assert value(*nodes, inp("k", "3"), op("v", "k_of_n", "k", "hi")) is False
    assert refusal(*nodes, inp("k", "6"), op("v", "k_of_n", "k", "hi"))["kind"] == "out_of_domain"
    grid = [inp("g", arr([["1", "20"], ["30", "4"]])), inp("lim", "12"), op("hi", "gt", "g", "lim")]
    assert value(*grid, op("n", "count_true", "hi", axis=0)).data.tolist() == [1, 1]


def test_magnitude_and_with_unit_apply_to_every_element():
    m = value(inp("i", arr(["2", "0.5"], "A")), op("n", "magnitude", "i", unit="mA"))
    assert m.unit == () and m.data.tolist() == [2000, 500]
    r = refusal(inp("i", arr(["2", "0.5"], "A")), op("n", "magnitude", "i", unit="mm"))
    assert r["kind"] == "unit_mismatch" and "never taken in the wrong unit" in r["reason"]
    w = value(inp("a", arr(["1.5", "2"])), {"id": "w", "op": "with_unit", "args": ["a"], "unit": "mil^2", "source": "IPC-2221"})
    assert w.unit == (("mil", 2),) and w.data.tolist() == [Fraction(3, 2), 2]
    assert refusal(inp("a", arr(["1"], "mm")), {"id": "w", "op": "with_unit", "args": ["a"], "unit": "mil^2", "source": "x"})["kind"] == "unit_mismatch"


def test_decibels_over_arrays_keep_their_rules():
    lv = value(inp("p", arr(["10", "20"], "dBm")), inp("g", "3 dB"), op("s", "add", "p", "g"))
    assert lv.unit == (("dBm", 1),) and lv.data.tolist() == [13, 23]
    r = refusal(inp("p", arr(["10", "20"], "dBm")), inp("q", "3 dBm"), op("s", "add", "p", "q"))
    assert r["kind"] == "decibel_level"
    ratio = value(inp("g", arr(["10", "3", "-20"], "dB")), {"id": "r", "op": "db_to_ratio", "args": ["g"], "kind": "power"})
    assert ratio.kind == A.FLOAT64
    holds(ratio, [mp.mpf(10), mp.power(10, mp.mpf(3) / 10), mp.mpf("0.01")])
    back = value(inp("r", arr(["100", "2"])), {"id": "d", "op": "ratio_to_db", "args": ["r"], "kind": "amplitude"})
    assert back.unit == (("dB", 1),)
    holds(back, [mp.mpf(40), 20 * mp.log10(2)])


def test_formulas_show_array_operations_and_never_write_an_array_in():
    g = graph(inp("x", arr(["1", "2", "3", "4"], "V")), op("s", "sum", "x"), op("f", "fft", "x"), op("p", "abs", "f"),
              op("m", "max", "p"), inp("i", "1"), op("el", "element", "x", "i"), result=["s", "m", "el"])
    out = evaluation_json(evaluate(read_graph(g), L.Guard()))
    assert out["status"] == "ok" and [r["node"] for r in out["results"]] == ["s", "m", "el"]
    lines = {line["node"]: line for line in out["formula"]}
    assert lines["s"]["text"] == "s = sum(x) = 10 V" and r"\sum" in lines["s"]["latex"]
    assert lines["m"]["text"].startswith("m = max(|fft(x)|) ≈ ") and r"\mathcal{F}" in lines["m"]["latex"]
    assert lines["el"]["text"] == "el = x[i] = 2 V" and "_{" in lines["el"]["latex"]
    steps = {s["node"]: s for s in out["working"] if "node" in s}
    assert steps["s"]["text"] == "s = sum(x) = 10 V", "an array is named, never written in"
    assert steps["f"]["label"].startswith("float64: error at most") and "array 4 (complex, float64, V)" in steps["f"]["text"]
    assert steps["x"]["label"] == "given"


def test_several_results_carry_arrays_and_the_record_re_runs():
    g = graph(inp("t", arr(q063_style()[0], "s"), "times"), inp("y", arr(q063_style()[1], "deg"), "angles"),
              op("slope", "fit_slope", "t", "y"), op("se", "fit_slope_se", "t", "y"), op("f", "fft", "y"),
              result=["slope", "se", "f"])
    rec = make(g)
    jsonschema.validate(rec, R.schema(6))
    assert [r["node"] for r in rec["results"]] == ["slope", "se", "f"]
    assert rec["results"][2]["array"]["kind"] == "complex" and "float64" in rec["results"][2]
    assert R.rerun(rec)["reproduces"] is True


def test_a_computed_array_is_shown_in_a_simpler_unit_and_whole_numbers_in_full():
    out = answer(inp("v", arr(["3.3", "5"], "V")), inp("i", "20 mA"), op("r", "div", "v", "i"))
    r = out["result"]
    assert r["array"]["unit"] == "kohm" and r["array"]["values"] == ["0.165", "0.25"] and r["simplified_from"] == "V/mA"
    big = answer(inp("x", arr(["2", "3"])), inp("k", "200"), op("p", "pow", "x", "k"))["result"]
    assert big["array"]["values"][0] == str(2**200) and "/" not in big["array"]["values"][0]
    f = answer(inp("v", arr(["3.3", "5"], "V")), op("e", "exp", "v"), inp("i", "20 mA"), op("r", "div", "v", "i"), op("s", "sqrt", "r"))
    assert f["status"] == "refused" and f["refused"]["kind"] == "unit_mismatch"  # exp of volts: a unit is never dropped
    g = answer(inp("v", arr(["4", "9"], "V")), inp("i", "1 mA"), op("r", "div", "v", "i"), inp("one", "1"), op("x", "pow", "r", "one"))
    assert g["result"]["array"]["unit"] == "kohm"


# ---------------------------------------------------------------- dec:v0-6-0-array-choices (flo2-calc 0.6.1)


def _record(g, limits=L.LAPTOP, name="choices", version=R.SCHEMA_VERSION):
    e = evaluate(read_graph(g, exact_limit=limits.max_exact_elements), L.Guard(limits))
    assert e.ok, e.refusal
    return R.build(e, name, None, version)


FIVE_THOUSAND = graph(inp("x", arr([str(i) for i in range(5_000)], "mm"), "data"), inp("k", "1/3", "scale"), op("y", "mul", "x", "k"),
                      op("s", "sum", "y"), result="s")


def test_a_record_keeps_its_exact_limit_and_re_runs_with_it_on_any_host():
    laptop = _record(FIVE_THOUSAND)
    jsonschema.validate(laptop, R.schema(6))
    assert laptop["max_exact_elements"] == 65_536 and laptop["result"]["value"].endswith(" mm") and "float64" not in laptop["result"]
    on_flo2 = R.rerun(laptop, L.Guard(L.FLO2_IO))
    assert on_flo2["reproduces"] is True and on_flo2["outcome"] == "reproduced"
    assert "the record's limit for an exact array, 65,536 elements" in on_flo2["exact_arrays"]
    hosted = _record(FIVE_THOUSAND, L.FLO2_IO)
    assert hosted["max_exact_elements"] == 4_096 and "float64" in hosted["result"]
    back_home = R.rerun(hosted)
    assert back_home["reproduces"] is True, back_home["differences"]
    no_arrays = _record(graph(inp("a", "1", "t"), inp("b", "2", "t"), op("s", "add", "a", "b")))
    assert "max_exact_elements" not in no_arrays, "a record with no array is as it was"


def test_a_version_5_record_re_runs_with_0_6_0s_fixed_limit():
    v5 = _record(FIVE_THOUSAND, L.Limits(max_exact_elements=4_096), version=5)
    jsonschema.validate(v5, R.schema(5))
    assert v5["schema_version"] == 5 and "max_exact_elements" not in v5 and "float64" in v5["result"]
    again = R.rerun(v5)  # a laptop now keeps 5,000 elements exact, but this record was made with 4,096
    assert again["reproduces"] is True, again["differences"]


def test_the_exact_limit_reaches_the_server_as_a_setting():
    import anyio
    from conftest import session

    g = graph(inp("x", arr([str(i) for i in range(20)])), inp("k", "3"), op("y", "mul", "x", "k"))

    async def ask(*extra):
        async with session(*extra) as s:
            return json.loads((await s.call_tool("evaluate_graph", {"graph": g})).content[0].text)

    assert anyio.run(ask, "--max-exact-elements", "10")["result"]["array"]["kind"] == "float64"
    assert anyio.run(ask, "--max-exact-elements", "20")["result"]["array"]["kind"] == "exact"


SPECTRUM = graph(inp("x", arr([str(i) for i in range(1, 9)], "V"), "samples"), op("f", "fft", "x"), op("m", "abs", "f"),
                 op("peak", "max", "m"), inp("p", arr(["0", "1", "2"]), "exponents"), op("e", "exp", "p"),
                 op("tot", "sum", "x"), result=["peak", "tot"])


def _another_processor(monkeypatch, factor):
    """numpy's FFT as another processor might compute it: every element moved by a relative `factor`."""
    real = np.fft.fft
    monkeypatch.setattr(np.fft, "fft", lambda x: real(x) * (1 + factor))
    return real


def test_an_fft_result_from_another_processor_re_runs_within_its_bound(monkeypatch):
    real = _another_processor(monkeypatch, 2.0**-50)
    rec = _record(SPECTRUM)
    monkeypatch.setattr(np.fft, "fft", real)
    again = R.rerun(rec)
    assert again["reproduces"] == "within_bound" and again["outcome"] == "reproduced_within_bound"
    assert again["reproduces"] is not True and again["differences"] == []
    nodes = {w["node"] for w in again["within_bound"]}
    assert {"f", "m", "peak"} <= nodes and "e" not in nodes and "tot" not in nodes, "only what rests on the FFT"
    worst = again["largest_difference"]
    assert 0 < worst["largest_difference"] <= worst["bound"] and worst["node"] in nodes
    assert "WITHIN THEIR STATED BOUNDS, not byte for byte" in again["verdict"]
    assert R.rerun(_record(SPECTRUM))["reproduces"] is True, "on the same processor, byte for byte"


def test_an_fft_result_beyond_its_bound_is_caught(monkeypatch):
    real = _another_processor(monkeypatch, 1e-9)
    rec = _record(SPECTRUM)
    monkeypatch.setattr(np.fft, "fft", real)
    again = R.rerun(rec)
    assert again["reproduces"] is False and again["outcome"] == "not_reproduced"
    f = next(d for d in again["differences"] if d["field"] == "values[f]")
    assert "beyond the bound" in f["why"] and f["largest_difference"] > f["bound"]


def test_every_other_value_must_still_reproduce_byte_for_byte():
    rec = _record(SPECTRUM)
    for node, old, new in (("e", None, None), ("tot", "36 V", "36.000000000000001 V")):
        bad = json.loads(json.dumps(rec))
        entry = next(v for v in bad["values"] if v["node"] == node)
        if node == "e":  # a float64 value with no FFT in it: one unit in the last place
            v = entry["array"]["values"]
            v[0] = repr(math.nextafter(float(v[0]), math.inf))
        else:  # an exact value
            entry["value"] = new
        bad["content_hash"] = R.content_hash(bad)
        again = R.rerun(bad)
        assert again["reproduces"] is False and again["outcome"] == "not_reproduced", node
        d = next(d for d in again["differences"] if d["field"] == f"values[{node}]")
        assert "byte for byte" in d["why"] or "not a float64 value resting on an FFT" in d["why"]


def test_a_large_fft_result_kept_only_as_its_sha256_cannot_be_weighed(monkeypatch):
    g = graph(inp("a", "0", "t"), inp("b", "1", "t"), inp("n", "2048", "t"), op("x", "linspace", "a", "b", "n"), op("f", "fft", "x"))
    real = _another_processor(monkeypatch, 2.0**-50)
    rec = _record(g)
    monkeypatch.setattr(np.fft, "fft", real)
    again = R.rerun(rec)
    assert again["reproduces"] is False
    assert any("keeps only this array's sha256" in d.get("why", "") for d in again["differences"])
