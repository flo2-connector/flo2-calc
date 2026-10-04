"""Units: carried through, converted exactly, spelled as reflow2 spells them.

ver:units-carry-and-convert in design 0bee0c00b35845f6 (and the evaluator's
half of ver:refusals-reach-the-agent; the client's half is test_server.py).
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from conftest import graph, inp, op

from flo2_calc import units as U
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph


def run(*nodes):
    return evaluation_json(evaluate(read_graph(graph(*nodes))))


def value(*nodes) -> str:
    answer = run(*nodes)
    assert answer["status"] == "ok", answer
    return answer["result"]["value"]


def refusal(*nodes):
    answer = run(*nodes)
    assert answer["status"] == "refused", answer
    return answer["refused"]


# ---------------------------------------------------------------- carried through


@pytest.mark.parametrize("nodes, expected", [
    ([inp("a", "2 mm"), inp("b", "3 mm"), op("r", "add", "a", "b")], "5 mm"),
    ([inp("a", "2 mm"), inp("b", "3 mm"), op("r", "sub", "a", "b")], "-1 mm"),
    ([inp("a", "2 mm"), inp("b", "3 mm"), op("r", "mul", "a", "b")], "6 mm^2"),
    ([inp("a", "6 mm^2"), inp("b", "3 mm"), op("r", "div", "a", "b")], "2 mm"),
    ([inp("a", "6 mm"), inp("b", "3 mm"), op("r", "div", "a", "b")], "2"),
    ([inp("a", "2 mm"), op("r", "neg", "a")], "-2 mm"),
    ([inp("a", "-2 mm"), op("r", "abs", "a")], "2 mm"),
    ([inp("a", "2 mm"), inp("n", "3"), op("r", "pow", "a", "n")], "8 mm^3"),
    ([inp("a", "2 mm"), inp("n", "-1"), op("r", "pow", "a", "n")], "0.5 1/mm"),
    ([inp("a", "5 mm"), inp("b", "3 mm"), op("r", "min", "a", "b")], "3 mm"),
    ([inp("a", "10 m"), inp("t", "4 s"), op("r", "div", "a", "t")], "2.5 m/s"),
    ([inp("f", "12 N"), inp("a", "4 m/s^2"), op("r", "div", "f", "a")], "3 N*s^2/m"),
])
def test_a_unit_survives_every_operation(nodes, expected):
    assert value(*nodes) == expected


def test_plain_numbers_and_true_false_carry_no_unit():
    answer = run(inp("a", "2"), inp("b", "3"), op("r", "mul", "a", "b"), inp("t", True), op("n", "not", "t"))
    vals = {v["node"]: v["value"] for v in answer["values"]}
    assert vals == {"a": "2", "b": "3", "r": "6", "t": "true", "n": "false"}


# ---------------------------------------------------------------- converted exactly


@pytest.mark.parametrize("nodes, expected", [
    ([inp("a", "0 mm"), inp("b", "1 in"), op("r", "add", "a", "b")], "25.4 mm"),
    ([inp("a", "1 in"), op("r", "convert", "a", unit="mm")], "25.4 mm"),
    ([inp("a", "1 ft"), op("r", "convert", "a", unit="mm")], "304.8 mm"),
    ([inp("a", "1 lb"), op("r", "convert", "a", unit="g")], "453.59237 g"),
    ([inp("a", "2 ct"), op("r", "convert", "a", unit="g")], "0.4 g"),
    ([inp("a", "1 mAh"), op("r", "convert", "a", unit="C")], "3.6 C"),
    ([inp("a", "1 eV"), op("r", "convert", "a", unit="J")], "1.602176634e-19 J"),
    ([inp("a", "1.5 kWh"), op("r", "convert", "a", unit="J")], "5400000 J"),
    ([inp("v", "3.3 V"), inp("i", "20 mA"), op("p", "mul", "v", "i"), op("r", "convert", "p", unit="mW")], "66 mW"),
    ([inp("a", "2 m"), inp("b", "3 mm"), op("r", "mul", "a", "b")], "0.006 m^2"),
    ([inp("a", "1 m"), inp("b", "1 mm"), op("r", "div", "a", "b")], "1000"),
    ([inp("a", "200 g"), inp("b", "5 %"), op("r", "mul", "a", "b")], "10 g"),
    ([inp("a", "10 %"), inp("b", "2"), op("r", "mul", "a", "b")], "20 %"),
    ([inp("a", "0.5"), inp("b", "10 %"), op("r", "add", "a", "b")], "0.6"),
    ([inp("a", "1 h"), op("r", "convert", "a", unit="s")], "3600 s"),
    ([inp("a", "1 L"), op("r", "convert", "a", unit="mm^3")], "1000000 mm^3"),
    ([inp("a", "1 kohm"), op("r", "convert", "a", unit="V/mA")], "1 V/mA"),
    ([inp("a", "1 bar"), op("r", "convert", "a", unit="kPa")], "100 kPa"),
])
def test_compatible_units_convert_exactly(nodes, expected):
    assert value(*nodes) == expected


def test_a_mixed_sum_is_in_the_first_operands_unit():
    assert value(inp("a", "1 m"), inp("b", "20 cm"), inp("c", "5 mm"), op("r", "add", "a", "b", "c")) == "1.205 m"


def test_every_conversion_factor_is_an_exact_fraction():
    for spelling in U.VOCABULARY:
        assert isinstance(U.atom(spelling).factor, Fraction), spelling
    assert U.atom("in").factor == Fraction(254, 10000)


# ---------------------------------------------------------------- refused, naming the operation and both units


@pytest.mark.parametrize("name", ["add", "sub", "min", "max", "lt", "eq"])
def test_units_that_measure_different_things_are_refused_naming_the_operation_and_both_units(name):
    r = refusal(inp("a", "2 mm"), inp("b", "3 g"), op("r", name, "a", "b"))
    assert r["kind"] == "unit_mismatch"
    assert r["node"] == "r" and r["op"] == name
    assert r["units"] == ["mm", "g"]
    assert r["reason"].startswith(f"{name} cannot combine mm and g")
    assert "length and mass" in r["reason"]


def test_convert_to_a_unit_of_another_kind_is_refused_naming_both():
    r = refusal(inp("a", "2 mm"), op("r", "convert", "a", unit="V"))
    assert r["reason"].startswith("convert cannot turn mm into V")
    assert r["units"] == ["mm", "V"]


def test_a_unit_is_never_stripped_against_a_plain_number():
    r = refusal(inp("a", "2 mm"), inp("b", "3"), op("r", "add", "a", "b"))
    assert r["kind"] == "unit_mismatch"
    assert "a plain number (no unit)" in r["reason"]


def test_angles_do_not_mix_with_plain_numbers_and_deg_and_rad_are_not_converted():
    assert refusal(inp("a", "30 deg"), inp("b", "1"), op("r", "add", "a", "b"))["kind"] == "unit_mismatch"
    r = refusal(inp("a", "30 deg"), inp("b", "1 rad"), op("r", "add", "a", "b"))
    assert "pi" in r["reason"]
    assert value(inp("a", "30 deg"), inp("b", "15 deg"), op("r", "add", "a", "b")) == "45 deg"


# ---------------------------------------------------------------- spelled as reflow2 spells them


@pytest.mark.parametrize("spelling", sorted(U.VOCABULARY))
def test_every_spelling_reads_and_writes_back_the_same(spelling):
    unit = U.parse_unit(spelling)
    assert U.format_unit(unit) == spelling


@pytest.mark.parametrize("text", ["mm^2", "m/s^2", "N*m", "kg/(m*s^2)", "1/s", "V*mA", "mAh/g", "W/(m^2*K)"])
def test_compound_units_read_and_write_back_the_same(text):
    assert U.format_unit(U.parse_unit(text)) == text


def test_the_integrated_designs_units_are_in_the_vocabulary():
    for spelling in ("mm", "g", "V", "mA"):  # rule:integrated-flo-unit-system
        assert spelling in U.VOCABULARY


@pytest.mark.parametrize("text, hint", [
    ("furlong", None),
    ("MM", '"mm"'),
    ("Kg", '"kg"'),
    ("µm", '"um"'),
    ("Ω", '"ohm"'),
    ("mm2", '"mm^2"'),
    ("inch", '"in"'),
    ("°C", "offset"),
    ("degC", "offset"),
])
def test_an_unknown_spelling_is_refused_never_guessed(text, hint):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"2 {text}")))
    e = caught.value
    assert e.path == "graph.nodes[0].value"
    assert "never guessed" in e.problem
    if hint:
        assert hint in e.problem


def test_an_unknown_unit_in_convert_is_refused_at_the_unit_field():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", "2 mm"), op("r", "convert", "a", unit="furlong")))
    assert caught.value.path == "graph.nodes[1].unit"


def test_a_unit_text_flo2_calc_cannot_read_says_how_to_write_it():
    for text in ("kg/m/s", "kg/m*s", "mm^0", "mm^99"):
        with pytest.raises(CallError):
            read_graph(graph(inp("a", f"1 {text}")))
