"""Decibels: dB as its own kind of value, power levels, and the conversions.

Round 2 (dec:round-2-fixes, fix 1): "dB" was refused as unknown, so agents
typed the decibel definition themselves (q010 a 10, q055 a 10, q056 a 20); a 10
in place of a 20 (q056's own trap) or a dB added to a linear ratio would have
been recorded as valid. Now:

- dB is its own dimension: dB adds to dB, dB/m times m is dB, and dB with a
  plain ratio is refused;
- db_to_ratio and ratio_to_db must be told "power" (10 log10) or "amplitude"
  (20 log10), never defaulted;
- dBm and dBW are power levels: convert turns them into mW or W and back, and
  a level is never added to a level, multiplied, or compared with a gain.

Every rounded result is checked against mpmath (tests/oracle.py), a different
implementation from Arb.
"""

from __future__ import annotations

from fractions import Fraction

import mpmath as mp
import oracle as O
import pytest
from conftest import graph, inp, op

from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph
from flo2_calc.numbers import parse_number


def run(*nodes, result=None):
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result))))


def ok(*nodes):
    answer = run(*nodes)
    assert answer["status"] == "ok", answer
    return answer["result"]


def refused(*nodes):
    answer = run(*nodes)
    assert answer["status"] == "refused", answer
    return answer["refused"]


def malformed(*nodes) -> CallError:
    with pytest.raises(CallError) as caught:
        read_graph(graph(*nodes))
    return caught.value


def number(r: dict, unit: str = "") -> Fraction:
    text = r["value"]
    if unit:
        assert text.endswith(" " + unit), r
        text = text[: -len(unit) - 1]
    return parse_number(text)


def oracle(fn, *args: str, places: int = 30) -> Fraction:
    with mp.workdps(O.DPS):
        return O.rounded(fn(*[O.mpq(parse_number(a)) for a in args]), places)


# ---------------------------------------------------------------- the kind is stated, never defaulted


@pytest.mark.parametrize("op_name", ["db_to_ratio", "ratio_to_db"])
def test_a_decibel_conversion_without_its_kind_is_refused_naming_both(op_name):
    e = malformed(inp("x", "6 dB" if op_name == "db_to_ratio" else "4"), op("r", op_name, "x"))
    assert e.path == "graph.nodes[1].kind"
    assert '"power"' in e.problem and '"amplitude"' in e.problem and "never picks one" in e.problem


def test_a_kind_that_is_neither_is_refused_and_not_read_case_blind():
    e = malformed(inp("g", "6 dB"), op("r", "db_to_ratio", "g", kind="Power"))
    assert e.path == "graph.nodes[1].kind" and "'Power' is neither" in e.problem


def test_only_the_decibel_conversions_take_a_kind():
    e = malformed(inp("a", "2"), op("r", "neg", "a", kind="power"))
    assert e.path == "graph.nodes[1].kind"


@pytest.mark.parametrize("db, kind, fn", [
    ("6", "power", lambda x: mp.power(10, x / 10)),
    ("6", "amplitude", lambda x: mp.power(10, x / 20)),
    ("-3.01", "power", lambda x: mp.power(10, x / 10)),
    ("17.5", "amplitude", lambda x: mp.power(10, x / 20)),
])
def test_db_to_ratio_is_correctly_rounded_for_the_kind_it_is_told(db, kind, fn):
    r = ok(inp("g", f"{db} dB"), op("r", "db_to_ratio", "g", kind=kind))
    assert number(r) == oracle(fn, db)
    assert r["rounded"]["correctly_rounded"] is True and r["rounded"]["digits"] == 30


def test_the_same_db_is_a_different_ratio_for_power_and_amplitude():
    """q056's trap: 10 for 20. Told the kind, flo2-calc cannot be off by it."""
    power = ok(inp("g", "6 dB"), op("r", "db_to_ratio", "g", kind="power"))
    amplitude = ok(inp("g", "6 dB"), op("r", "db_to_ratio", "g", kind="amplitude"))
    assert number(power) == oracle(lambda x: mp.power(10, x / 10), "6")
    assert number(amplitude) == oracle(lambda x: mp.power(10, x / 20), "6")
    assert number(power) != number(amplitude)


@pytest.mark.parametrize("ratio, kind, k", [("250", "power", 10), ("7.5", "amplitude", 20), ("0.5", "power", 10)])
def test_ratio_to_db_is_correctly_rounded_and_in_db(ratio, kind, k):
    """q055 (10 log10 of 250) and q056 (20 log10 of 7.5), with no typed 10 or 20."""
    r = ok(inp("x", ratio), op("g", "ratio_to_db", "x", kind=kind))
    assert number(r, "dB") == oracle(lambda x: k * mp.log10(x), ratio)
    assert r["rounded"]["error_at_most"].endswith(" dB")


@pytest.mark.parametrize("db, kind, exact", [("20 dB", "power", "100"), ("20 dB", "amplitude", "10"), ("-30 dB", "power", "0.001"),
                                             ("0 dB", "amplitude", "1")])
def test_a_whole_power_of_ten_stays_exact(db, kind, exact):
    r = ok(inp("g", db), op("r", "db_to_ratio", "g", kind=kind))
    assert r == {"node": "r", "value": exact}


def test_a_power_of_ten_ratio_is_an_exact_db():
    assert ok(inp("x", "1000"), op("g", "ratio_to_db", "x", kind="power")) == {"node": "g", "value": "30 dB"}
    assert ok(inp("x", "1/100"), op("g", "ratio_to_db", "x", kind="amplitude")) == {"node": "g", "value": "-40 dB"}


def test_a_ratio_of_zero_or_less_has_no_db():
    r = refused(inp("x", "0"), op("g", "ratio_to_db", "x", kind="power"))
    assert r["kind"] == "out_of_domain"


# ---------------------------------------------------------------- dB is its own kind


def test_db_adds_to_db_and_db_per_metre_times_metres_is_db():
    assert ok(inp("a", "3 dB"), inp("b", "-1.5 dB"), op("s", "add", "a", "b"))["value"] == "1.5 dB"
    assert ok(inp("a", "0.2 dB/m"), inp("l", "30 m"), op("s", "mul", "a", "l"))["value"] == "6 dB"
    assert ok(inp("a", "0.35 dB/km"), inp("l", "2000 m"), op("s", "mul", "a", "l"))["value"] == "0.7 dB"
    assert ok(inp("a", "12 dB"), inp("b", "10 dB"), op("s", "ge", "a", "b"))["value"] == "true"


@pytest.mark.parametrize("nodes", [
    [inp("a", "3 dB"), inp("b", "2"), op("s", "add", "a", "b")],
    [inp("a", "3 dB"), inp("b", "2"), op("s", "gt", "a", "b")],
    [inp("a", "3 dB"), op("s", "convert", "a", unit="")],
])
def test_db_with_a_plain_ratio_is_refused_pointing_to_the_conversions(nodes):
    r = refused(*nodes)
    assert r["kind"] == "unit_mismatch"
    assert "db_to_ratio" in r["reason"] and "never picks one" in r["reason"]


def test_db_to_ratio_of_a_plain_number_is_refused_never_taken_for_db():
    """q010's agent passed dB as plain numbers: never again silently."""
    r = refused(inp("g", "6"), op("r", "db_to_ratio", "g", kind="power"))
    assert r["kind"] == "unit_mismatch" and 'Write its unit ("6 dB")' in r["reason"]


def test_ratio_to_db_of_a_value_already_in_db_is_refused():
    r = refused(inp("g", "6 dB"), op("r", "ratio_to_db", "g", kind="power"))
    assert "already in decibels" in r["reason"]


@pytest.mark.parametrize("op_name", ["log10", "sqrt", "exp"])
def test_a_function_of_db_is_refused_a_unit_is_never_dropped(op_name):
    r = refused(inp("g", "6 dB"), op("r", op_name, "g"))
    assert r["kind"] == "unit_mismatch"


# ---------------------------------------------------------------- power levels: dBm and dBW


@pytest.mark.parametrize("level, unit, expected", [("10 dBm", "mW", "10 mW"), ("0 dBm", "mW", "1 mW"), ("30 dBm", "W", "1 W"),
                                                    ("-20 dBW", "mW", "10 mW"), ("0 dBW", "kW", "0.001 kW")])
def test_a_level_converts_exactly_to_a_power_where_it_can(level, unit, expected):
    assert ok(inp("p", level), op("w", "convert", "p", unit=unit))["value"] == expected


def test_a_level_converts_to_a_power_correctly_rounded():
    r = ok(inp("p", "13 dBm"), op("w", "convert", "p", unit="mW"))
    assert number(r, "mW") == oracle(lambda x: mp.power(10, x / 10), "13")
    r = ok(inp("p", "-7.3 dBm"), op("w", "convert", "p", unit="uW"))
    assert number(r, "uW") == oracle(lambda x: 1000 * mp.power(10, x / 10), "-7.3")


def test_a_power_converts_to_a_level_correctly_rounded():
    r = ok(inp("p", "2 mW"), op("l", "convert", "p", unit="dBm"))
    assert number(r, "dBm") == oracle(lambda x: 10 * mp.log10(x), "2")
    assert ok(inp("p", "100 mW"), op("l", "convert", "p", unit="dBW"))["value"] == "-10 dBW"


def test_dbm_and_dbw_differ_by_exactly_thirty():
    assert ok(inp("p", "-30 dBW"), op("l", "convert", "p", unit="dBm"))["value"] == "0 dBm"
    assert ok(inp("p", "13 dBm"), op("l", "convert", "p", unit="dBW"))["value"] == "-17 dBW"


def test_a_power_of_zero_has_no_level():
    assert refused(inp("p", "0 mW"), op("l", "convert", "p", unit="dBm"))["kind"] == "out_of_domain"


def test_a_level_plus_gains_is_a_level_and_a_level_minus_a_level_is_a_gain():
    """A link budget: transmit level, cable loss, received level, margin."""
    nodes = [inp("tx", "20 dBm"), inp("loss_per_m", "0.2 dB/m"), inp("len", "30 m"), op("loss", "mul", "loss_per_m", "len"),
             inp("gain", "3 dB"), op("rx", "sub", "tx", "loss"), op("rx2", "add", "rx", "gain"), inp("floor", "-80 dBW"),
             op("margin", "sub", "rx2", "floor"), op("ok", "gt", "rx2", "floor")]
    answer = run(*nodes)
    values = {v["node"]: v["value"] for v in answer["values"]}
    assert values["rx"] == "14 dBm" and values["rx2"] == "17 dBm"
    assert values["margin"] == "67 dB", "-80 dBW is -50 dBm"
    assert values["ok"] == "true"


@pytest.mark.parametrize("nodes, words", [
    ([inp("a", "10 dBm"), inp("b", "3 dBm"), op("s", "add", "a", "b")], "not the level of their total power"),
    ([inp("a", "10 dBm"), inp("b", "2"), op("s", "mul", "a", "b")], "does not multiply"),
    ([inp("a", "10 dBm"), op("s", "neg", "a")], "change sign"),
    ([inp("a", "10 dBm"), inp("b", "3 dB"), op("s", "gt", "a", "b")], "only a level compares with a level"),
    ([inp("a", "3 dB"), inp("b", "10 dBm"), op("s", "sub", "a", "b")], "that means nothing"),
    ([inp("a", "10 dBm"), inp("b", "2"), op("s", "add", "a", "b")], "only by a gain in dB"),
    ([inp("a", "10 dBm"), op("s", "convert", "a", unit="dB")], "a gain in dB: subtract a reference level"),
    ([inp("a", "10 dBm"), op("s", "convert", "a", unit="")], "not a ratio"),
    ([inp("a", "10 dBm"), op("s", "db_to_ratio", "a", kind="power")], "a level is a power, not a ratio"),
])
def test_what_a_level_cannot_do_is_refused_with_its_reason(nodes, words):
    r = refused(*nodes)
    assert words in r["reason"], r["reason"]


def test_a_level_is_read_only_as_a_whole_unit():
    e = malformed(inp("n", "-174 dBm/Hz"))
    assert e.path == "graph.nodes[0].value" and "whole unit" in e.problem


def test_a_level_rounds_in_its_own_unit():
    assert ok(inp("p", "10.5 dBm"), op("r", "round", "p", mode="half_up"))["value"] == "11 dBm"


# ---------------------------------------------------------------- shown back: the 10 or the 20 is visible


@pytest.mark.parametrize("kind, k", [("power", 10), ("amplitude", 20)])
def test_the_formula_shows_the_factor_the_kind_chose(kind, k):
    answer = run(inp("g", "6 dB"), op("r", "db_to_ratio", "g", kind=kind))
    assert answer["formula"][-1]["text"].startswith(f"r = 10^(g / ({k} dB)) ≈ ")
    assert rf"{k}\,\mathrm{{dB}}" in answer["formula"][-1]["latex"]
    answer = run(inp("x", "7.5"), op("g", "ratio_to_db", "x", kind=kind))
    assert answer["formula"][-1]["text"].startswith(f"g = {k} dB * log10(x) ≈ ")
