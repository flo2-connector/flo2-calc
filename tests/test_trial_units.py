"""The units the Shop sample trial asked for (flo2-calc 0.11.0): the acre and the hectare, the Btu and the
refrigeration ton, each defined exactly, and their other readings refused as ambiguous.

THE ACRE AND THE HECTARE.

dec:the-international-acre-and-the-hectare-the-survey-acre-refused in design 0bee0c00b35845f6, Anthony's ruling of
2026-10-24, on the evidence of the Shop sample trial: a parcel of 3.27 acres, and a county code counting one
animal unit per half acre. flo2-calc carried no named unit of area at all, so the agent turned acres into ft^2 by
hand.

The acre is the INTERNATIONAL acre, 43,560 ft^2, exactly 4,046.8564224 m^2. pint's acre is the US survey acre
(10 square survey chains, about 4,046.8726 m^2), so flo2-calc defines its own, as it does the international
furlong. A value written in US survey acres does not say which acre it is, so the survey acre is refused with
its reason, like "gr" and a bare gallon.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from conftest import graph, inp, op

from flo2_calc import units as U
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph


def value(*nodes) -> str:
    answer = evaluation_json(evaluate(read_graph(graph(*nodes))))
    assert answer["status"] == "ok", answer
    return answer["result"]["value"]


def test_an_acre_is_exactly_43560_international_square_feet():
    assert U.atom("acre").factor == Fraction(40468564224, 10**7) == 43560 * U.atom("ft").factor ** 2
    assert U.atom("acre").dimension == tuple((d, 2 * e) for d, e in U.atom("ft").dimension)
    assert value(inp("a", "1 acre"), op("r", "convert", "a", unit="ft^2")) == "43560 ft^2"
    assert value(inp("a", "1 acre"), op("r", "convert", "a", unit="m^2")) == "4046.8564224 m^2"
    assert value(inp("a", "3.27 acre"), op("r", "convert", "a", unit="ft^2")) == "142441.2 ft^2"


def test_a_hectare_is_exactly_10000_square_metres():
    assert U.atom("ha").factor == Fraction(10000)
    assert value(inp("a", "1 ha"), op("r", "convert", "a", unit="m^2")) == "10000 m^2"
    assert value(inp("a", "1 acre"), op("r", "convert", "a", unit="ha")) == "0.40468564224 ha"


def test_an_area_in_acres_adds_to_one_in_square_feet_exactly():
    assert value(inp("a", "0.5 acre"), inp("b", "21780 ft^2"), op("s", "add", "a", "b"), op("r", "convert", "s", unit="acre")) == "1 acre"


def test_pints_survey_acre_is_never_the_acre():
    import pint

    survey = pint.UnitRegistry(non_int_type=Fraction).Quantity(Fraction(1), "acre").to("meter**2").magnitude
    assert Fraction(survey) != U.atom("acre").factor


@pytest.mark.parametrize("text", ["survey_acre", "us_survey_acre", "US_survey_acre"])
def test_the_us_survey_acre_is_refused_as_ambiguous_with_its_reason(text):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"3.27 {text}")))
    said = caught.value.problem
    assert "US survey acre" in said and "international acre" in said, said
    assert '"acre"' in said and "43,560 ft^2" in said
    assert "ft^2" in said and "m^2" in said, "says how to write an area its source states in survey measure"


@pytest.mark.parametrize("text, hint", [("acres", "acre"), ("hectare", "ha"), ("hectares", "ha")])
def test_the_spellings_people_write_for_them_are_hinted(text, hint):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"2 {text}")))
    assert f'Write "{hint}"' in caught.value.problem


# ---------------------------------------------------------------- the Btu and the refrigeration ton
#
# dec:the-international-table-btu-and-the-refrigeration-ton (Anthony's ruling of 2026-10-24, on the Shop sample's
# Phase C: the chat was refused "Btu" and routed its U-factors, its 1.08 air factor and its heat-pump ratings through
# a cited NIST factor and with_unit). The Btu is the International Table Btu, exactly 1055.05585262 J (NIST SP 811,
# Btu_IT). pint's own "Btu" is the ISO one, 1055.056 J, so flo2-calc defines its own, as it does the furlong and
# the acre. Every other Btu is refused as ambiguous. The refrigeration ton is 12,000 Btu_IT per hour, named
# `ton_refrigeration`, and a bare "ton" stays what it was: refused, pint's short ton of mass, nothing substituted.

BTU_IT = Fraction(105505585262, 10**8)  # J, exactly


def test_a_btu_is_exactly_the_international_table_btu():
    assert U.atom("Btu").factor == BTU_IT
    assert U.atom("Btu").dimension == U.atom("J").dimension
    assert value(inp("a", "1 Btu"), op("r", "convert", "a", unit="J")) == "1055.05585262 J"


def test_btu_per_hour_is_a_rate_and_a_heat_pumps_rating_converts_exactly():
    w = Fraction(18000) * BTU_IT / 3600
    got = evaluation_json(evaluate(read_graph(graph(inp("a", "18000 Btu/h"), op("r", "convert", "a", unit="W")))))["result"]
    shown = got.get("exact") or got["value"]
    assert Fraction(shown.split()[0]) == w and shown.endswith(" W")


def test_a_u_factor_in_btu_per_hour_square_foot_degree_converts_exactly():
    # 1 Btu/(h*ft^2*degF) = 1055.05585262 J / (3600 s * 0.09290304 m^2 * 5/9 K)
    expected = BTU_IT / (3600 * Fraction(9290304, 10**8) * Fraction(5, 9))
    got = evaluation_json(evaluate(read_graph(graph(inp("u", "0.056 Btu/(h*ft^2*delta_degF)"), op("r", "convert", "u", unit="W/(m^2*K)")))))
    assert got["status"] == "ok", got
    shown = got["result"].get("exact") or got["result"]["value"]
    assert Fraction(shown.split()[0]) == Fraction(56, 1000) * expected


def test_a_refrigeration_ton_is_exactly_12000_btu_per_hour():
    assert U.atom("ton_refrigeration").factor == 12000 * BTU_IT / 3600
    got = evaluation_json(evaluate(read_graph(graph(inp("c", "1 ton_refrigeration"), op("r", "convert", "c", unit="Btu/h")))))
    assert got["result"]["value"] == "12000 Btu/h"
    w = evaluation_json(evaluate(read_graph(graph(inp("c", "1 ton_refrigeration"), op("r", "convert", "c", unit="W")))))["result"]
    assert Fraction((w.get("exact") or w["value"]).split()[0]) == Fraction(105505585262, 30000000)


@pytest.mark.parametrize("text", ["BTU", "Btu_iso", "Btu_th", "british_thermal_unit"])
def test_every_other_btu_is_refused_as_ambiguous_with_its_reason(text):
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", f"2 {text}")))
    said = caught.value.problem
    assert "International Table" in said and "1055.05585262 J" in said and '"Btu"' in said, said
    assert "1055.056 J" in said and "thermochemical" in said, said


def test_a_bare_ton_is_still_refused_and_never_becomes_a_refrigeration_ton():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", "2 ton")))
    said = caught.value.problem
    assert "pint reads it as ton (mass)" in said and "substitutes nothing" in said, said
    assert "ton_refrigeration" not in said
