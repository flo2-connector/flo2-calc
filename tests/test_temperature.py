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
    ("5 delta_degC", "K", "5 delta_K"),        # a change converted to K stays a change (round 3, q036)
    ("18 delta_degF", "K", "10 delta_K"),
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
    assert r["value"] == "65 delta_K", "a rise, written so it is never read as a temperature of 65 K"


def test_a_temperature_minus_a_change_is_a_temperature():
    assert value(inp("t", "30 degC"), inp("d", "9 delta_degF"), op("r", "sub", "t", "d")) == "25 degC"


def test_a_temperature_minus_k_is_refused_because_k_could_be_either():
    r = refusal(inp("t", "30 degC"), inp("k", "5 K"), op("r", "sub", "t", "k"))
    assert r["kind"] == "offset_temperature"
    assert "temperature or a change of temperature" in r["reason"] and "delta_degC" in r["reason"]


def test_k_minus_a_temperature_is_a_change_in_k():
    assert value(inp("k", "300 K"), inp("t", "25 degC"), op("r", "sub", "k", "t")) == "1.85 delta_K"


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


# ---------------------------------------------------------------- a change stays a change (round 3, q036; flo2-calc 0.7.0)
#
# ver:a-temperature-difference-stays-a-difference. flo2-calc 0.6.1 converted
# 18 delta_degF to a bare "10 K", and converted that on to -263.15 degC as if
# it were a temperature: right in q036, silently wrong in the next step a
# design takes. A K known to be a change is now delta_K, exactly the size of K,
# and never read as a temperature.

# Every way a change of temperature comes out in kelvin, and the change it is.
CHANGE_IN_KELVIN = [
    pytest.param([inp("r", "18 delta_degF"), op("x", "convert", "r", unit="K")], "10 delta_K", id="delta_degF to K"),
    pytest.param([inp("r", "10 delta_degC"), op("x", "convert", "r", unit="K")], "10 delta_K", id="delta_degC to K"),
    pytest.param([inp("r", "10 delta_K"), op("x", "convert", "r", unit="K")], "10 delta_K", id="delta_K to K"),
    pytest.param([inp("a", "30 degC"), inp("b", "20 degC"), op("d", "sub", "a", "b"), op("x", "convert", "d", unit="K")],
                 "10 delta_K", id="degC - degC, to K"),
    pytest.param([inp("a", "86 degF"), inp("b", "68 degF"), op("d", "sub", "a", "b"), op("x", "convert", "d", unit="K")],
                 "10 delta_K", id="degF - degF, to K"),
    pytest.param([inp("k", "303.15 K"), inp("t", "20 degC"), op("x", "sub", "k", "t")], "10 delta_K", id="K - degC"),
    pytest.param([inp("rth", "2.5 K/W"), inp("p", "4 W"), op("x", "mul", "rth", "p")], "10 delta_K", id="K/W * W"),
    pytest.param([inp("p", "4000 mW"), inp("rth", "2.5 K/W"), op("x", "mul", "p", "rth")], "10 delta_K", id="mW * K/W"),
    pytest.param([inp("rth", "2.5 degC/W"), inp("p", "4 W"), op("d", "mul", "rth", "p"), op("x", "convert", "d", unit="K")],
                 "10 delta_K", id="degC/W * W, to K"),
    pytest.param([inp("q", "1000 J"), inp("c", "100 J/K"), op("x", "div", "q", "c")], "10 delta_K", id="J / (J/K)"),
    pytest.param([inp("x", "10 K*W/W")], "10 delta_K", id="K inside a compound, as written"),
]


@pytest.mark.parametrize("nodes, change", CHANGE_IN_KELVIN)
def test_a_change_of_temperature_in_kelvin_is_written_delta_k(nodes, change):
    assert value(*nodes) == change


@pytest.mark.parametrize("nodes, change", CHANGE_IN_KELVIN)
@pytest.mark.parametrize("scale", ["degC", "degF"])
def test_a_change_in_kelvin_is_never_converted_as_a_temperature(nodes, change, scale):
    """The step 0.6.1 got silently wrong: -263.15 degC from a 10 K rise."""
    r = refusal(*nodes, op("onward", "convert", nodes[-1]["id"], unit=scale))
    assert r["kind"] == "offset_temperature" and r["units"] == ["delta_K", scale]
    assert "change of temperature, not a temperature" in r["reason"] and f"delta_{scale}" in r["reason"]


@pytest.mark.parametrize("nodes, change", CHANGE_IN_KELVIN)
def test_a_change_in_kelvin_converts_on_as_a_change_and_shifts_a_temperature(nodes, change):
    last = nodes[-1]["id"]
    assert value(*nodes, op("to_c", "convert", last, unit="delta_degC")) == "10 delta_degC"
    assert value(*nodes, op("to_f", "convert", last, unit="delta_degF")) == "18 delta_degF"
    assert value(*nodes, inp("t0", "20 degC"), op("hot", "add", "t0", last)) == "30 degC"
    assert value(*nodes, inp("t0", "30 degC"), op("cool", "sub", "t0", last)) == "20 degC", "a known change needs no guess"
    r = refusal(*nodes, inp("t0", "20 degC"), op("cmp", "lt", "t0", last))
    assert r["kind"] == "offset_temperature", "a temperature is never compared with a change"


def test_q036_the_rise_in_kelvin_and_the_next_step():
    nodes = [inp("rise", "18 delta_degF", "imported spec: an allowed temperature RISE"), op("rise_k", "convert", "rise", unit="K")]
    answer = run(*nodes)
    assert answer["result"] == {"node": "rise_k", "value": "10 delta_K"}
    assert "-263.15" not in str(run(*nodes, op("c", "convert", "rise_k", unit="degC")))


def test_q096_a_k_typed_for_a_rise_still_adds_to_a_temperature():
    """add(20 degC, 10 K) is 30 degC, and 30 degC is 303.15 K, as before."""
    answer = run(inp("t", "20 degC"), inp("d", "10 K"), op("n", "add", "t", "d"), op("k", "convert", "n", unit="K"))
    assert [v["value"] for v in answer["values"]][-2:] == ["30 degC", "303.15 K"]


def test_a_k_typed_or_scaled_is_still_read_by_where_it_stands():
    """Only a K KNOWN to be a change is delta_K. A typed K is a temperature in
    convert, and a K scaled by a plain number keeps its K."""
    assert value(inp("k", "298.15 K"), op("c", "convert", "k", unit="degC")) == "25 degC"
    assert value(inp("k", "10 K"), inp("n", "2"), op("x", "mul", "k", "n")) == "20 K"
    assert value(inp("k", "10 K"), inp("n", "50 %"), op("x", "mul", "k", "n")) == "5 K"
    assert value(inp("k", "300 K"), inp("d", "10 delta_K"), op("x", "add", "k", "d")) == "310 K"
    assert value(inp("a", "300 K"), inp("b", "25 degC"), op("r", "min", "a", "b")) == "298.15 K"


def test_offset_units_in_products_are_changes_or_refused():
    """A degree that comes out of a product is a change; a reading never multiplies."""
    assert value(inp("rth", "2.5 degC/W"), inp("p", "4 W"), op("x", "mul", "rth", "p")) == "10 delta_degC"
    assert value(inp("rth", "4.5 degF/W"), inp("p", "4 W"), op("x", "mul", "rth", "p")) == "18 delta_degF"
    assert value(inp("rth", "2.5 K/W"), inp("p", "4 W"), op("x", "mul", "rth", "p")) == "10 delta_K"
    assert value(inp("a", "12 um/(m*degC)"), inp("d", "10 delta_K"), inp("l", "2 m"), op("r", "mul", "a", "d", "l"),
                 op("u", "convert", "r", unit="um")) == "240 um"
    r = refusal(inp("t", "25 degC"), inp("w", "2 W"), op("x", "mul", "t", "w"))
    assert r["kind"] == "offset_temperature"


def test_delta_k_is_a_change_a_typed_one_too():
    assert U.parse_unit("delta_K") == (("delta_K", 1),)
    assert U.describe_dimension(U.parse_unit("delta_K")) == "temperature change"
    assert value(inp("t", "25 degC"), inp("d", "5 delta_K"), op("r", "add", "t", "d")) == "30 degC"
    r = refusal(inp("d", "5 delta_K"), op("c", "convert", "d", unit="degF"))
    assert r["kind"] == "offset_temperature"


def test_a_temperature_minus_k_still_names_every_way_to_write_a_change():
    r = refusal(inp("t", "30 degC"), inp("k", "5 K"), op("r", "sub", "t", "k"))
    assert "delta_K" in r["reason"] and "delta_degC" in r["reason"]


def test_an_array_of_changes_converted_to_k_stays_changes():
    from conftest import graph as g_

    def arr(values, unit):
        return {"array": values, "unit": unit}

    answer = evaluation_json(evaluate(read_graph(g_(inp("r", arr(["9", "18"], "delta_degF")), op("k", "convert", "r", unit="K")))))
    assert answer["result"]["array"]["unit"] == "delta_K" and answer["result"]["array"]["values"] == ["5", "10"]
    answer = evaluation_json(evaluate(read_graph(g_(inp("r", arr(["9", "18"], "delta_degF")), op("k", "convert", "r", unit="K"),
                                                    op("c", "convert", "k", unit="degC")))))
    assert answer["status"] == "refused" and answer["refused"]["kind"] == "offset_temperature"
    answer = evaluation_json(evaluate(read_graph(g_(inp("t", arr(["300", "310"], "K")), inp("c", "20 degC"), op("d", "sub", "t", "c")))))
    assert answer["result"]["array"]["unit"] == "delta_K"


def test_before_0_7_0_a_change_in_k_was_a_bare_k():
    """Records of version 6 and older re-run under the rules they were made with
    (units.before_delta_k; tests/test_record.py re-runs one)."""
    with U.before_delta_k():
        assert value(inp("r", "18 delta_degF"), op("x", "convert", "r", unit="K")) == "10 K"
        assert value(inp("rth", "2.5 K/W"), inp("p", "4 W"), op("x", "mul", "rth", "p")) == "10 K"
    assert value(inp("r", "18 delta_degF"), op("x", "convert", "r", unit="K")) == "10 delta_K"
