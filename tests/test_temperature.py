"""degC and degF: temperatures on a scale with an offset (temperature.py).

ver:units-carry-and-convert in design 0bee0c00b35845f6, for group 4 of
dec:round-1-fixes-one-to-six: temperatures convert without detours, exactly,
and a difference of temperatures stays correct. Round 1 found agents typing
273.15 and the Fahrenheit formula themselves (q030, q032), and readings going
in as plain numbers (q012, q014, q021).

A READING is a value whose whole unit is degC or degF; a CHANGE is delta_degC,
delta_degF, or a degree inside a compound unit. K is either; where both are
possible, flo2-calc refuses.
"""

from __future__ import annotations

import pytest
from conftest import graph, inp, op

from flo2_calc import units as U
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph


def run(*nodes):
    return evaluation_json(evaluate(read_graph(graph(*nodes))))


def result_of(*nodes) -> dict:
    answer = run(*nodes)
    assert answer["status"] == "ok", answer
    return answer["result"]


def value(*nodes) -> str:
    return result_of(*nodes)["value"]


def refusal(*nodes) -> dict:
    answer = run(*nodes)
    assert answer["status"] == "refused", answer
    assert answer["result"] is None
    return answer["refused"]


# ---------------------------------------------------------------- converting, exactly


@pytest.mark.parametrize("given, to, expected", [
    ("36.6 degC", "K", "309.75 K"),            # q030, with no typed 273.15
    ("98.6 degF", "degC", "37 degC"),          # q032, with no typed formula
    ("0 degC", "degF", "32 degF"),
    ("100 degC", "degF", "212 degF"),
    ("-40 degF", "degC", "-40 degC"),
    ("0 K", "degC", "-273.15 degC"),
    ("0 K", "degF", "-459.67 degF"),
    ("273.15 K", "degC", "0 degC"),
    ("77 degF", "K", "298.15 K"),
    ("25 degC", "degC", "25 degC"),
])
def test_a_temperature_converts_exactly_between_degc_degf_and_k(given, to, expected):
    assert value(inp("t", given), op("r", "convert", "t", unit=to)) == expected


def test_a_conversion_that_does_not_end_keeps_its_exact_value():
    r = result_of(inp("t", "1 degF"), op("r", "convert", "t", unit="degC"))
    assert r["exact"] == "-155/9 degC"


@pytest.mark.parametrize("given, to, expected", [
    ("9 delta_degF", "delta_degC", "5 delta_degC"),
    ("5 delta_degC", "K", "5 K"),
    ("10 K", "delta_degF", "18 delta_degF"),
    ("2.5 degC/W", "K/W", "2.5 K/W"),           # a degree in a compound is a change
    ("18 um/(m*degF)", "um/(m*K)", "32.4 um/(m*K)"),
])
def test_a_change_of_temperature_converts_by_its_factor_alone(given, to, expected):
    assert value(inp("t", given), op("r", "convert", "t", unit=to)) == expected


def test_a_reading_is_never_turned_into_a_change_nor_a_change_into_a_reading():
    r = refusal(inp("t", "25 degC"), op("r", "convert", "t", unit="delta_degC"))
    assert r["kind"] == "offset_temperature" and r["units"] == ["degC", "delta_degC"]
    r = refusal(inp("t", "5 delta_degC"), op("r", "convert", "t", unit="degC"))
    assert r["kind"] == "offset_temperature" and "not a temperature" in r["reason"]


def test_a_temperature_is_not_converted_into_another_kind_of_unit():
    r = refusal(inp("t", "25 degC"), op("r", "convert", "t", unit="mm"))
    assert r["kind"] == "unit_mismatch" and r["units"] == ["degC", "mm"]


# ---------------------------------------------------------------- adding and subtracting


def test_a_temperature_plus_a_change_is_a_temperature_on_its_scale():
    assert value(inp("t", "25 degC"), inp("d", "5 delta_degC"), op("r", "add", "t", "d")) == "30 degC"
    assert value(inp("t", "25 degC"), inp("d", "9 delta_degF"), op("r", "add", "t", "d")) == "30 degC"
    assert value(inp("t", "25 degC"), inp("d", "5 K"), op("r", "add", "t", "d")) == "30 degC"
    assert value(inp("d", "5 K"), inp("t", "77 degF"), op("r", "add", "d", "t")) == "86 degF", "the reading's scale, wherever it stands"


def test_a_junction_temperature_from_power_and_thermal_resistance():
    """q021's sum without typed offsets: Tj = Ta + P * R(th), with R(th) in degC/W."""
    r = result_of(
        inp("ta", "40 degC"), inp("p", "1.2 W"), inp("rth", "23.25 degC/W"),
        op("rise", "mul", "p", "rth"), op("tj", "add", "ta", "rise"),
        inp("limit", "125 degC"), op("ok", "lt", "tj", "limit"),
    )
    assert r["value"] == "true"
    values = {v["node"]: v["value"] for v in run(
        inp("ta", "40 degC"), inp("p", "1.2 W"), inp("rth", "23.25 degC/W"),
        op("rise", "mul", "p", "rth"), op("tj", "add", "ta", "rise"))["values"]}
    assert values["rise"] == "27.9 delta_degC", "a product that comes out in degrees is a change"
    assert values["tj"] == "67.9 degC"


def test_two_temperatures_do_not_add():
    r = refusal(inp("a", "25 degC"), inp("b", "30 degC"), op("r", "add", "a", "b"))
    assert r["kind"] == "offset_temperature" and r["units"] == ["degC", "degC"]
    assert "means nothing" in r["reason"] and "use sub" in r["reason"]


def test_the_difference_of_two_temperatures_is_a_change():
    assert value(inp("a", "30 degC"), inp("b", "25 degC"), op("r", "sub", "a", "b")) == "5 delta_degC"
    assert value(inp("a", "30 degC"), inp("b", "77 degF"), op("r", "sub", "a", "b")) == "5 delta_degC"
    assert value(inp("a", "86 degF"), inp("b", "25 degC"), op("r", "sub", "a", "b")) == "9 delta_degF"


def test_a_rise_from_two_readings_is_the_same_change_in_k():
    """q012's 65 K rise, from two readings and no offsets typed by hand."""
    r = result_of(inp("hot", "85 degC"), inp("cold", "20 degC"), op("d", "sub", "hot", "cold"), op("k", "convert", "d", unit="K"))
    assert r["value"] == "65 K"


def test_a_temperature_minus_a_change_is_a_temperature():
    assert value(inp("t", "30 degC"), inp("d", "9 delta_degF"), op("r", "sub", "t", "d")) == "25 degC"


def test_a_temperature_minus_k_is_refused_because_k_could_be_either():
    r = refusal(inp("t", "30 degC"), inp("k", "5 K"), op("r", "sub", "t", "k"))
    assert r["kind"] == "offset_temperature"
    assert "temperature or a change of temperature" in r["reason"] and "delta_degC" in r["reason"]


def test_k_minus_a_temperature_is_a_change_in_k():
    assert value(inp("k", "300 K"), inp("t", "25 degC"), op("r", "sub", "k", "t")) == "1.85 K"


def test_a_change_minus_a_temperature_is_refused():
    r = refusal(inp("d", "5 delta_degC"), inp("t", "25 degC"), op("r", "sub", "d", "t"))
    assert r["kind"] == "offset_temperature"


def test_a_temperature_and_another_kind_of_unit_are_refused_naming_both():
    r = refusal(inp("t", "25 degC"), inp("m", "2 mm"), op("r", "add", "t", "m"))
    assert r["kind"] == "unit_mismatch" and r["units"] == ["degC", "mm"]
    r = refusal(inp("t", "25 degC"), inp("n", "2"), op("r", "add", "t", "n"))
    assert r["kind"] == "unit_mismatch"


# ---------------------------------------------------------------- comparing


@pytest.mark.parametrize("name, a, b, expected", [
    ("eq", "25 degC", "77 degF", "true"),
    ("eq", "25 degC", "298.15 K", "true"),
    ("lt", "25 degC", "78 degF", "true"),
    ("gt", "300 K", "25 degC", "true"),
    ("le", "-40 degF", "-40 degC", "true"),
    ("ne", "0 degC", "0 degF", "true"),
])
def test_temperatures_compare_exactly_on_one_scale(name, a, b, expected):
    assert value(inp("a", a), inp("b", b), op("r", name, "a", "b")) == expected


def test_min_and_max_answer_in_the_first_ones_unit():
    assert value(inp("a", "25 degC"), inp("b", "80 degF"), op("r", "max", "a", "b")) == "26.6666666666666666666666666667 degC"
    assert value(inp("a", "300 K"), inp("b", "25 degC"), op("r", "min", "a", "b")) == "298.15 K"


def test_a_temperature_is_not_compared_with_a_change():
    r = refusal(inp("a", "25 degC"), inp("b", "25 delta_degC"), op("r", "eq", "a", "b"))
    assert r["kind"] == "offset_temperature" and r["units"] == ["degC", "delta_degC"]


# ---------------------------------------------------------------- what a reading does not do


@pytest.mark.parametrize("nodes", [
    [inp("t", "25 degC"), inp("n", "2"), op("r", "mul", "t", "n")],
    [inp("t", "25 degC"), inp("n", "2"), op("r", "div", "t", "n")],
    [inp("t", "25 degC"), inp("n", "2"), op("r", "pow", "t", "n")],
    [inp("t", "25 degC"), op("r", "neg", "t")],
    [inp("t", "-25 degC"), op("r", "abs", "t")],
    [inp("a", "25 degC"), inp("b", "50 degC"), op("r", "div", "b", "a")],
])
def test_a_temperature_on_an_offset_scale_does_not_multiply_divide_raise_or_negate(nodes):
    r = refusal(*nodes)
    assert r["kind"] == "offset_temperature"
    assert "Convert it to K first" in r["reason"]


def test_a_change_of_temperature_multiplies_like_any_unit():
    assert value(inp("d", "5 delta_degC"), inp("n", "2"), op("r", "mul", "d", "n")) == "10 delta_degC"
    assert value(inp("a", "12 um/(m*degC)"), inp("d", "50 delta_degC"), inp("l", "2 m"),
                 op("r", "mul", "a", "d", "l"), op("u", "convert", "r", unit="um")) == "1200 um"


# ---------------------------------------------------------------- reading the units


def test_a_degree_alone_is_a_reading_and_in_a_compound_that_reduces_to_it_a_change():
    assert U.parse_unit("degC") == (("degC", 1),)
    assert U.parse_unit("degC*W/W") == (("delta_degC", 1),)
    assert U.scale_of(U.parse_unit("degF")) == "degF"
    assert U.scale_of(U.parse_unit("degC/W")) is None


@pytest.mark.parametrize("text, hint", [("°C", "degC"), ("℃", "degC"), ("°F", "degF"), ("degc", "degC"), ("DELTA_DEGC", "delta_degC")])
def test_the_ways_people_write_a_degree_are_hinted(text, hint):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"25 {text}")))
    assert f'Write "{hint}"' in caught.value.problem


def test_c_with_a_degree_mark_after_it_is_refused_naming_both_readings():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", "25 C°")))
    assert '"degC"' in caught.value.problem and '"delta_degC"' in caught.value.problem
