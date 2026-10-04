"""Units: carried through, converted exactly, spelled as reflow2 spells them.

ver:units-carry-and-convert in design 0bee0c00b35845f6 (and the evaluator's
half of ver:refusals-reach-the-agent; the client's half is test_server.py).
Round 1's fixes (dec:round-1-fixes-one-to-six): the units added, money as
separate dimensions with no rates, and a bare C or F refused. The near-miss
hint has its own file, test_unit_hints.py; temperatures, test_temperature.py.
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


def result_of(*nodes) -> dict:
    answer = run(*nodes)
    assert answer["status"] == "ok", answer
    return answer["result"]


def value(*nodes) -> str:
    return result_of(*nodes)["value"]


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
    ([inp("a", "1 mAh"), op("r", "convert", "a", unit="coulomb")], "3.6 coulomb"),
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
    ("khz", 'Write "kHz"'),
    ("kOhm", 'Write "kohm"'),
    ("µm", 'Write "um"'),
    ("Ω", 'Write "ohm"'),
    ("mΩ", 'Write "mohm"'),
    ("mm2", 'Write "mm^2"'),
    ("inch", 'Write "in"'),
    ("°C", 'Write "degC"'),
    ("℉", 'Write "degF"'),
    ("thou", 'Write "mil"'),
    ("€", 'Write "EUR"'),
    ("usd", 'Write "USD"'),
    # No hint where another case is another size or another quantity: the
    # case of a prefix is its size (dec:units-use-reflow2-spellings).
    ("MM", "case-sensitive"),
    ("Kg", "case-sensitive"),
])
def test_an_unknown_spelling_is_refused_never_guessed(text, hint):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"2 {text}")))
    e = caught.value
    assert e.path == "graph.nodes[0].value"
    assert "never guessed" in e.problem
    if hint:
        assert hint in e.problem
    if hint == "case-sensitive":
        assert "Write" not in e.problem


def test_an_unknown_unit_in_convert_is_refused_at_the_unit_field():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", "2 mm"), op("r", "convert", "a", unit="furlong")))
    assert caught.value.path == "graph.nodes[1].unit"


def test_a_unit_text_flo2_calc_cannot_read_says_how_to_write_it():
    for text in ("kg/m/s", "kg/m*s", "mm^0", "mm^99"):
        with pytest.raises(CallError):
            read_graph(graph(inp("a", f"1 {text}")))


# ---------------------------------------------------------------- every prefixed spelling is its prefix and its unit


def test_every_spelling_is_an_unprefixed_unit_or_an_si_prefix_and_one():
    """mJ is exactly 1/1000 J, Mohm exactly 10^6 ohm, uF exactly 10^-6 farad:
    a spelling means what it says, so a hint that reads a spelling by its
    prefix (test_unit_hints.py) reads it right."""
    for spelling in U.VOCABULARY:
        if spelling in U.UNPREFIXED:
            continue
        splits = [
            (p, spelling[len(p):]) for p in U.SI_PREFIXES
            if spelling.startswith(p) and spelling[len(p):] in (U.UNPREFIXED | set(U.OTHER_SYMBOLS))
        ]
        assert len(splits) == 1, (spelling, splits)
        prefix, base = splits[0]
        f, dim, zero = U.meaning(base)
        assert U.meaning(spelling) == (f * Fraction(10) ** U.SI_PREFIXES[prefix], dim, zero), spelling
    assert set(U.UNPREFIXED) <= set(U.VOCABULARY)


# ---------------------------------------------------------------- the units round 1 asked for (group 3)


@pytest.mark.parametrize("nodes, expected", [
    ([inp("a", "1 mil"), op("r", "convert", "a", unit="mm")], "0.0254 mm"),
    ([inp("a", "1000 mil"), op("r", "convert", "a", unit="in")], "1 in"),
    ([inp("a", "1 lbf"), op("r", "convert", "a", unit="N")], "4.4482216152605 N"),
    ([inp("a", "1 psi"), op("r", "convert", "a", unit="lbf/in^2")], "1 lbf/in^2"),
    ([inp("a", "1 ksi"), op("r", "convert", "a", unit="psi")], "1000 psi"),
    ([inp("a", "1 gal_us"), op("r", "convert", "a", unit="L")], "3.785411784 L"),
    ([inp("a", "1 gal_us"), op("r", "convert", "a", unit="in^3")], "231 in^3"),
    ([inp("a", "1 gal_imp"), op("r", "convert", "a", unit="L")], "4.54609 L"),
    ([inp("a", "1 deg"), op("r", "convert", "a", unit="arcsec")], "3600 arcsec"),
    ([inp("a", "1 deg"), inp("b", "30 arcmin"), inp("c", "36 arcsec"), op("r", "add", "a", "b", "c")], "1.51 deg"),
    ([inp("a", "5 mJ"), op("r", "convert", "a", unit="uJ")], "5000 uJ"),
    ([inp("a", "250 mohm"), op("r", "convert", "a", unit="ohm")], "0.25 ohm"),
    ([inp("a", "2 MWh"), op("r", "convert", "a", unit="kWh")], "2000 kWh"),
    ([inp("a", "3 pA"), inp("b", "2 nA"), op("r", "add", "b", "a")], "2.003 nA"),
    ([inp("a", "1 mHz"), op("r", "convert", "a", unit="1/s")], "0.001 1/s"),
    ([inp("a", "1 mPa*s"), op("r", "convert", "a", unit="Pa*s")], "0.001 Pa*s"),
    ([inp("a", "2 coulomb"), inp("t", "4 s"), op("r", "div", "a", "t"), op("i", "convert", "r", unit="A")], "0.5 A"),
    ([inp("c", "100 uF"), op("r", "convert", "c", unit="farad")], "0.0001 farad"),
])
def test_the_units_round_1_asked_for_convert_exactly(nodes, expected):
    assert value(*nodes) == expected


def test_a_psi_is_an_exact_fraction_of_a_pascal():
    r = result_of(inp("a", "1 psi"), op("r", "convert", "a", unit="Pa"))
    assert r["exact"] == "8896443230521/1290320000 Pa", "a pound-force (exactly 4.4482216152605 N) on a square inch"
    assert r["value"] == "6894.75729316836133672267344535 Pa"


@pytest.mark.parametrize("a, b", [("1 arcsec", "1 rad"), ("1 arcmin", "1 rad"), ("1 rad", "1 deg")])
def test_deg_arcmin_and_arcsec_are_still_not_turned_into_rad(a, b):
    r = refusal(inp("a", a), inp("b", b), op("r", "add", "a", "b"))
    assert r["kind"] == "unit_mismatch" and "pi" in r["reason"]


@pytest.mark.parametrize("text", ["gal", "gallon", "gallons"])
def test_a_bare_gallon_is_refused_naming_both_gallons(text):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"2 {text}")))
    problem = caught.value.problem
    assert '"gal_us"' in problem and '"gal_imp"' in problem
    assert "3.785411784 L" in problem and "4.54609 L" in problem
    assert "Write the one you mean" in problem


# ---------------------------------------------------------------- a bare C or F (coulomb or Celsius? farad or Fahrenheit?)


@pytest.mark.parametrize("text", ["25 C", "2.5 C/W", "3 um/(m*C)", "0.5 C*V"])
def test_a_bare_c_is_refused_and_the_reason_points_a_temperature_at_degc(text):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", text)))
    problem = caught.value.problem
    assert '"C" is the SI symbol for the coulomb' in problem
    assert '"degC"' in problem and '"delta_degC"' in problem and '"coulomb"' in problem


@pytest.mark.parametrize("text", ["77 F", "1 F"])
def test_a_bare_f_is_refused_and_the_reason_points_a_temperature_at_degf(text):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", text)))
    problem = caught.value.problem
    assert '"F" is the SI symbol for the farad' in problem
    assert '"degF"' in problem and '"farad"' in problem


def test_coulomb_and_farad_say_which_is_meant_and_work_as_units():
    assert value(inp("q", "0.5 coulomb"), inp("v", "2 V"), op("c", "div", "q", "v"), op("r", "convert", "c", unit="farad")) == "0.25 farad"


# ---------------------------------------------------------------- money: each currency its own dimension, no rates


def test_amounts_in_one_currency_add_exactly():
    assert value(inp("a", "987.50 USD"), inp("b", "12.50 USD"), op("r", "add", "a", "b")) == "1000 USD"
    assert value(inp("a", "120 EUR"), inp("p", "5 %"), op("r", "mul", "a", "p")) == "6 EUR"


@pytest.mark.parametrize("name", ["add", "sub", "lt", "max"])
def test_two_currencies_are_refused_naming_both_and_asking_for_a_rate(name):
    r = refusal(inp("a", "987.50 USD"), inp("b", "120 EUR"), op("r", name, "a", "b"))
    assert r["kind"] == "unit_mismatch"
    assert r["units"] == ["USD", "EUR"]
    assert r["reason"].startswith(f"{name} cannot combine USD and EUR: they are different currencies.")
    assert "no exchange rates" in r["reason"] and "source" in r["reason"]


def test_a_currency_is_not_a_plain_number_either():
    r = refusal(inp("a", "987.50 USD"), inp("b", "120"), op("r", "add", "a", "b"))
    assert r["kind"] == "unit_mismatch" and r["units"] == ["USD", ""]


def test_convert_never_turns_one_currency_into_another():
    r = refusal(inp("a", "100 USD"), op("r", "convert", "a", unit="EUR"))
    assert r["reason"].startswith("convert cannot turn USD into EUR") and "no exchange rates" in r["reason"]


def test_only_a_rate_the_caller_gives_with_its_source_converts():
    rate = {"id": "rate", "value": "0.92 EUR/USD", "source": "ECB reference rate, 2026-10-02"}
    assert value(inp("a", "100 USD"), rate, op("r", "mul", "a", "rate")) == "92 EUR"
    assert value(inp("a", "92 EUR"), rate, op("r", "div", "a", "rate")) == "100 USD"
    assert value(inp("a", "100 USD/h"), rate, op("r", "mul", "a", "rate")) == "92 EUR/h"


def test_a_rate_with_no_source_is_refused_at_its_source_field():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", "100 USD"), inp("rate", "0.92 EUR/USD", source=None), op("r", "mul", "a", "rate")))
    assert caught.value.path == "graph.nodes[1].source"
    assert "exchange rate" in caught.value.problem and "flo2-calc holds no rates" in caught.value.problem


def test_the_currencies_are_iso_4217_codes_each_its_own_dimension():
    assert list(U.CURRENCIES) == ["USD", "EUR", "JPY", "GBP", "CNY", "AUD", "CAD", "CHF", "HKD", "SGD"]
    dims = {U.atom(c).dimension for c in U.CURRENCIES}
    assert len(dims) == len(U.CURRENCIES), "no two currencies share a dimension"


@pytest.mark.parametrize("sign, named", [("$", "USD, CAD, AUD"), ("¥", "JPY"), ("£", "GBP")])
def test_a_currency_sign_shared_by_several_currencies_is_refused_naming_them(sign, named):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"5 {sign}")))
    assert named in caught.value.problem and 'Write "' not in caught.value.problem
