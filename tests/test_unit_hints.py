"""A near-miss hint never changes what was written, in size or in kind.

ver:units-carry-and-convert and ver:refusals-reach-the-agent in design
0bee0c00b35845f6. Round 1 of the question set (ver:question-set-round-1, q022)
found flo2-calc 0.1.0 (and 0.2.0, unchanged) answering "mJ" with 'Write "MJ"', 10^9 too large: the
hint matched spellings case-insensitively, and an SI prefix's case is its
size. These tests hold the fix:

- THE WALK. Every SI prefix, with every unit symbol in the vocabulary (and the
  SI symbols flo2-calc does not know), in every case variation of the whole
  text. For each text that gets a 'Write "X"' hint, X means what the text means
  as written (the same factor, the same dimension, the same zero), the text
  has exactly one such meaning, and X keeps every prefix letter as typed.
- The round-1 list, one by one, and the two the grader did not list (Nm, mS).
- Every listed near miss means what its target means.

"As written" is this file's own reading, independent of units.readings: its
own prefix table (the SI Brochure, 9th edition, and the prefixes of 2022), its
own list of SI symbols, and pint for what a symbol it does not share with the
vocabulary is. A prefix is read exactly as typed; the symbol after it in any
case, because a slip in a symbol's case is what a hint exists to catch.
"""

from __future__ import annotations

import itertools
import re
from fractions import Fraction

import pytest

from flo2_calc import units as U

PREFIXES = {
    "Q": 30, "R": 27, "Y": 24, "Z": 21, "E": 18, "P": 15, "T": 12, "G": 9, "M": 6, "k": 3, "h": 2, "da": 1,
    "d": -1, "c": -2, "m": -3, "u": -6, "µ": -6, "μ": -6, "n": -9, "p": -12, "f": -15, "a": -18, "z": -21,
    "y": -24, "r": -27, "q": -30,
}

# The SI's base and derived units' symbols, the units accepted for use with
# it, and two more symbols in wide use (M, molar; a, the year), with pint's
# name for each that the vocabulary does not hold.
SI_SYMBOLS = {
    "mol": "mole", "cd": "candela", "sr": "steradian", "C": "coulomb", "F": "farad", "S": "siemens",
    "Wb": "weber", "T": "tesla", "lm": "lumen", "lx": "lux", "Bq": "becquerel", "Gy": "gray", "Sv": "sievert",
    "kat": "katal", "au": "astronomical_unit", "ha": "hectare", "l": "liter", "Da": "dalton", "Ω": "ohm",
    "M": "molar", "a": "year",
}
ZERO = {"degC": Fraction(27315, 100), "degF": Fraction(45967, 180)}  # where each scale's zero is, in K


def meaning(symbol: str):
    if symbol in U.VOCABULARY:
        a = U.atom(symbol)
        return a.factor, a.dimension, ZERO.get(symbol, Fraction(0))
    ureg = U.registry()
    name = SI_SYMBOLS[symbol]
    f = ureg.Quantity(Fraction(1), name).to_base_units().magnitude
    dims = tuple(sorted((str(k), int(v)) for k, v in ureg.get_dimensionality(name).items() if v != 0))
    return Fraction(f), dims, Fraction(0)


BASES = sorted(U.UNPREFIXED | set(SI_SYMBOLS))


def as_written(text: str) -> set:
    """Every unit `text` is: its prefix read exactly as typed, then a symbol
    typed exactly; or, only when no symbol is typed exactly, a symbol in another
    case (a slip in the symbol's case, never the prefix's)."""
    if text in PREFIXES:
        return {(Fraction(10) ** PREFIXES[text], (), Fraction(0))}  # a prefix alone is its number
    exact, slipped = set(), set()
    for prefix, exponent in [("", 0), *PREFIXES.items()]:
        rest = text[len(prefix):]
        if text.startswith(prefix) and rest:
            for b in BASES:
                if b.casefold() == rest.casefold():
                    f, dims, zero = meaning(b)
                    (exact if b == rest else slipped).add((f * Fraction(10) ** exponent, dims, zero))
    return exact or slipped


def variations(text: str):
    """Every case variation of the whole text, prefix and symbol alike."""
    choices = [sorted({c.lower(), c.upper()}) if c.lower() != c.upper() else [c] for c in text]
    return {"".join(p) for p in itertools.product(*choices)}


WRITE = re.compile(r'Write "([^"]+)"')


def refusal(text: str) -> str | None:
    """The refusal's text for a unit, or None when flo2-calc reads it."""
    try:
        U.parse_unit(text)
    except U.UnitTextError as e:
        return str(e)
    return None


def hinted(text: str) -> str | None:
    said = refusal(text)
    m = WRITE.search(said) if said else None
    return m.group(1) if m else None


def prefix_of(spelling: str) -> str:
    """The SI prefix a vocabulary spelling carries ("" for none)."""
    if spelling in U.UNPREFIXED:
        return ""
    return next(p for p in PREFIXES if spelling.startswith(p) and spelling[len(p):] in (U.UNPREFIXED | set(SI_SYMBOLS)))


def keeps_the_prefix(text: str, spelling: str) -> bool:
    """Whether `text` starts with a prefix of the same size as `spelling`'s (µ and u are both micro)."""
    px = prefix_of(spelling)
    return px == "" or any(text.startswith(p) and PREFIXES[p] == PREFIXES[px] for p in PREFIXES)


# ---------------------------------------------------------------- the walk


def test_no_hint_ever_changes_the_size_or_kind_of_what_was_written():
    texts = set()
    for base in BASES:
        for prefix in ["", *PREFIXES]:
            texts |= variations(prefix + base)
    checked = 0
    hints: dict[str, str] = {}
    for text in sorted(texts):
        if text in U.VOCABULARY:
            continue
        checked += 1
        x = hinted(text)
        if x is None or x not in U.VOCABULARY:  # a listed near miss to a compound ("mm^2") is checked below
            continue
        hints[text] = x
        written = as_written(text)
        assert written, f'"{text}" reads as no unit, yet the hint says "{x}"'
        assert written == {meaning(x)}, f'"{text}" is {written} as written; the hint "{x}" is {meaning(x)}'
        assert keeps_the_prefix(text, x), f'"{text}" -> "{x}" changes the prefix as typed'
    assert checked > 70_000, f"the walk covers every prefix, base and case: {checked} texts"
    # The walk is not empty: safe case slips are still hinted.
    for text, x in {"khz": "kHz", "MHZ": "MHz", "kOhm": "kohm", "MOhm": "Mohm", "mw": "mW", "Mw": "MW",
                    "ev": "eV", "hz": "Hz", "kpa": "kPa", "DEGC": "degC", "usd": "USD", "Gal_Us": "gal_us"}.items():
        assert hints.get(text) == x, (text, hints.get(text))


# ---------------------------------------------------------------- round 1's list (q022), one by one

# (written, the unit the old hint proposed, how far off it was)
ROUND_1 = [
    ("mJ", "MJ", "10^9 too large"),
    ("mohm", "Mohm", "10^9 too large"),
    ("mHz", "MHz", "10^9 too large"),
    ("mPa", "MPa", "10^9 too large"),
    ("mw", "MW", "10^9 too large"),
    ("MWh", "mWh", "10^9 too small"),
    ("MV", "mV", "10^9 too small"),
    ("MA", "mA", "10^9 too small"),
    ("Mg", "mg", "10^9 too small"),
    ("Ms", "ms", "10^9 too small"),
    ("MF", "mF", "10^9 too small"),
    ("MH", "mH", "10^9 too small"),
    ("ML", "mL", "10^9 too small"),
    ("MAh", "mAh", "10^9 too small"),
    ("PF", "pF", "10^27 too small"),
    ("pA", "Pa", "a pressure for a current"),
    ("PA", "Pa", "a pressure for a current"),
    ("EV", "eV", "an energy for a voltage"),
    # Not in the grader's list, found by the walk: the old hint made the same mistake.
    ("Nm", "nm", "a length for a torque written without *"),
    ("mS", "ms", "a time for a conductance (millisiemens)"),
    ("mM", "mm", "a length for a concentration (millimolar)"),
    ("MM", "mm", "Mm (megametre) as typed, or MM (megamolar)"),
    ("S", "s", "a time for a conductance"),
    ("k", "K", "a temperature for a bare kilo"),
    ("pct", "%", "p + ct is a picocarat as written: the old list called it percent"),
]


@pytest.mark.parametrize("text, wrong, off", ROUND_1, ids=[t for t, _, _ in ROUND_1])
def test_a_round_1_hint_never_comes_back(text, wrong, off):
    said = refusal(text)
    if said is None:
        assert text in U.VOCABULARY, text  # now a unit flo2-calc knows, meaning what it says
        return
    assert f'Write "{wrong}"' not in said, off
    x = hinted(text)
    assert x is None or as_written(text) == {meaning(x)}


@pytest.mark.parametrize("text", ["mJ", "uJ", "mohm", "mHz", "mPa", "MWh", "pA", "nA"])
def test_the_spellings_round_1_found_missing_are_known_and_mean_what_they_say(text):
    assert text in U.VOCABULARY
    assert as_written(text) == {meaning(text)}, "the spelling's prefix and symbol are exactly its size and kind"


def test_a_case_slip_that_could_change_a_size_says_why_there_is_no_hint():
    said = refusal("MV")
    assert "Write" not in said
    assert "case-sensitive" in said and "m is milli" in said and "M is mega" in said


# ---------------------------------------------------------------- the listed near misses

# Sources pint cannot read, or reads as something else, each checked by hand.
BY_HAND = {
    '"': "the inch mark",
    "amps": "pint reads it as attometre per second",
    "℃": "U+2103 DEGREE CELSIUS",
    "℉": "U+2109 DEGREE FAHRENHEIT",
    "€": "the euro sign, one currency's",
    "mm2": "a square written without ^", "mm3": "a cube written without ^", "m2": "", "m3": "", "cm2": "",
    "cm3": "", "mm²": "", "mm³": "", "m²": "", "m³": "",
    "decibel": "pint's decibel is a logarithmic unit; flo2-calc's dB is its own dimension (decibels.py)",
    "decibels": "the same",
    "furlongs": "pint's furlong is the US survey furlong; flo2-calc's is the international 660 ft (tests/test_units.py)",
}
PINT_NAME = {"degC": "degree_Celsius", "degF": "degree_Fahrenheit"}  # a reading, not a change


def pint_meaning(name: str):
    ureg = U.registry()
    one = ureg.Quantity(Fraction(1), name).to_base_units()
    zero = ureg.Quantity(Fraction(0), name).to_base_units()
    dims = tuple(sorted((str(k), int(v)) for k, v in one.dimensionality.items() if v != 0))
    return Fraction(one.magnitude - zero.magnitude), dims, Fraction(zero.magnitude)


@pytest.mark.parametrize("source, target", sorted(U.NEAR_MISSES.items()))
def test_every_listed_near_miss_means_what_its_target_means(source, target):
    if source in BY_HAND:
        return
    written = as_written(source)
    if written:
        assert written == {meaning(target)}, (source, target)
    target_name = PINT_NAME.get(target, U.VOCABULARY[target][0])
    assert pint_meaning(U.registry().parse_units(source)) == pint_meaning(target_name), (source, target)


def test_the_by_hand_list_holds_only_listed_near_misses():
    assert set(BY_HAND) <= set(U.NEAR_MISSES)
