"""Units, spelled as reflow2 spells them, measured by pint, converted exactly.

THE DECISIONS THIS HOLDS (design 0bee0c00b35845f6):
  - dec:optional-units: a value may carry a unit; a value without one is a
    plain number (or true/false);
  - dec:unit-mismatch-rejects: combining units that measure different things
    is refused, naming the operation and both units, and a unit is never
    silently stripped;
  - dec:units-use-reflow2-spellings: every unit is written the way reflow2
    designs write it (mm, g, V, mA ...), because reflow2 compares units by
    exact spelling. A spelling flo2-calc does not know is refused, never
    guessed;
  - dec:round-1-fixes-one-to-six, groups 3 and 4: psi, ksi, lbf, mil, arcmin,
    arcsec and the two gallons; degC and degF as temperatures with an offset;
  - dec:round-2-fixes: furlong and fortnight; dB as its own kind of value, and
    dBm and dBW as power levels (decibels.py); a computed value's compound unit
    shown in a simpler unit of the same size where one exists (`simplify`);
  - round 3's fixes (flo2-calc 0.7.0): the troy ounce, pennyweight, grain and
    week; delta_K, a change of temperature in kelvin, so that a change stays a
    change through convert (`converted_unit`) and through a product; and an
    unknown spelling that pint reads is named for what pint reads it as, with
    the units of that kind flo2-calc carries, and nothing substituted.

WHO DOES WHAT. The vocabulary below maps each spelling to a pint unit. pint,
loaded with exact fractions, says what each unit measures (its dimension) and
its exact factor to SI base units; flo2-calc's own code does every piece of
arithmetic on those fractions. pint's float arithmetic is never used.

DELIBERATE DEPARTURES FROM pint:
  - Angles are their own dimension. pint calls deg and rad dimensionless, so
    it would let "30 deg + 1" through; flo2-calc refuses it. arcmin and arcsec
    are exact fractions of a deg (1/60 and 1/3600). deg and rad are never
    mixed in one operation, because their ratio is pi/180, which no fraction
    holds exactly. Only `convert` turns one into the other (`pi_conversion`),
    arcmin and arcsec through deg, and its result is a correctly rounded value
    labelled rounded (realmath.py), never an exact one.
  - Money. Each currency (an ISO 4217 code) is its own dimension, and
    flo2-calc holds no exchange rates, so USD + EUR is refused, naming both.
    Only a rate the caller gives, as an input with its source ("0.92 EUR/USD"),
    turns one into another, by multiplying.
  - Temperatures. K, degC and degF. A value whose whole unit is degC or degF
    is a temperature READING on a scale with an offset; temperature.py holds
    what may be done with one. Anywhere else (inside a compound unit such as
    degC/W, or as delta_degC and delta_degF) a degree is a CHANGE of
    temperature, and multiplies like any other unit. A value in K can be a
    temperature or a change, so a K that is KNOWN to be a change is written
    delta_K (exactly the size of K): a change converted to K
    (`converted_unit`), a product that comes out in K through a compound
    (2.5 K/W * 4 W is 10 delta_K, as 2.5 degC/W * 4 W is 10 delta_degC), and
    K minus a temperature (temperature.py). A delta_K is never read as a
    temperature: convert to degC or degF refuses it. Round 3 (q036) found
    convert(18 delta_degF, K) giving a bare 10 K, which then converted to
    -263.15 degC as if it were a temperature.
  - "gr" is not read: it is written for both the grain and the gram (AMBIGUOUS).
  - "mil" is the thousandth of an inch (pint's "thou"), not pint's angular mil.
  - "furlong" is the international furlong, 660 ft (exactly 201.168 m). pint's
    furlong is the US survey furlong (40 rods of 16.5 survey feet, 201.1684 m).
  - Decibels. "dB" is its own dimension, like a currency: dB adds to dB, dB/m
    times m is dB, and dB with a plain ratio is refused, because a gain in dB
    and a linear ratio are different things (10 dB is a ratio of 10 in power
    and of about 3.16 in amplitude). "dBm" and "dBW" are power LEVELS, dB above
    1 mW and 1 W: decibels.py holds what may be done with one, and they are
    read only as a value's whole unit.
  - A bare "C" or "F" is not read at all (AMBIGUOUS below): C is the SI symbol
    for the coulomb and F for the farad, but both are written for degrees
    Celsius and Fahrenheit, and a temperature read silently as a charge or a
    capacitance is a wrong answer that looks right. "coulomb" and "farad" say
    which is meant.

NEAR-MISS HINTS. A refused spelling may get a hint, and A HINT NEVER CHANGES
WHAT WAS WRITTEN, IN SIZE OR IN KIND. Two kinds of hint exist:
  - a listed near miss (NEAR_MISSES: "µm" -> "um", "Ω" -> "ohm", "°C" ->
    "degC"), each one tested to mean exactly what its target means;
  - a slip in the case of a unit's NAME, never of its prefix ("khz" ->
    "kHz", "kOhm" -> "kohm"). The text is read as written (`readings`): its
    SI prefix exactly as typed, because a prefix's case is its size (m is
    milli, M is mega; p is pico, P is peta), and its unit symbol in any case,
    against every SI symbol, not only flo2-calc's own. It is hinted only when
    every such reading is one and the same unit, and the hint is that unit.
    So "mJ" (a millijoule) is never answered with MJ, "pA" (a picoampere, or a
    miscased pascal) and "mS" (a millisiemens, or a miscased millisecond) get
    no hint, and "Nm" (which reads as nothing: N is not a prefix) is never
    answered with nm.
flo2-calc 0.1.0 and 0.2.0 matched spellings case-insensitively instead, and so answered
"mJ" with "Write MJ", 10^9 too large (round 1, q022).

A UNIT'S TEXT. Atoms joined by "*", a power as "^n", one "/" with a single
atom or a parenthesised product after it: "mm", "mm^2", "m/s^2", "N*m",
"kg/(m*s^2)", "1/s". Results are written the same way, with atoms in the order
they first appeared, so a unit flo2-calc writes is one it reads back.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from typing import Iterator

from flo2_calc.errors import Refusal

# The currencies flo2-calc knows: the ten most traded in the BIS Triennial
# Central Bank Survey of 2022, by ISO 4217 code. Each is its own dimension.
CURRENCIES: dict[str, str] = {
    "USD": "US dollar",
    "EUR": "euro",
    "JPY": "Japanese yen",
    "GBP": "pound sterling",
    "CNY": "Chinese renminbi",
    "AUD": "Australian dollar",
    "CAD": "Canadian dollar",
    "CHF": "Swiss franc",
    "HKD": "Hong Kong dollar",
    "SGD": "Singapore dollar",
}

# spelling -> (pint unit, what it measures, for the reader). A currency has no
# pint unit: flo2-calc gives it its own dimension (atom()).
VOCABULARY: dict[str, tuple[str | None, str]] = {
    # length
    "m": ("meter", "length"),
    "km": ("kilometer", "length"),
    "cm": ("centimeter", "length"),
    "mm": ("millimeter", "length"),
    "um": ("micrometer", "length"),
    "nm": ("nanometer", "length"),
    "in": ("inch", "length"),
    "ft": ("foot", "length"),
    "mil": ("thou", "length"),  # a thousandth of an inch, exactly 0.0254 mm
    "furlong": (None, "length"),  # the international furlong, 660 ft (DEFINED below), not pint's survey furlong
    # mass
    "kg": ("kilogram", "mass"),
    "g": ("gram", "mass"),
    "mg": ("milligram", "mass"),
    "ug": ("microgram", "mass"),
    "t": ("metric_ton", "mass"),
    "ct": ("carat", "mass"),
    "lb": ("pound", "mass"),
    "oz": ("ounce", "mass"),  # the avoirdupois ounce, exactly 28.349523125 g
    "ozt": ("troy_ounce", "mass"),  # the troy ounce, exactly 31.1034768 g (NIST Handbook 44, Appendix C)
    "dwt": ("pennyweight", "mass"),  # the pennyweight, 1/20 troy ounce, exactly 1.55517384 g
    "grain": ("grain", "mass"),  # exactly 64.79891 mg ("gr" alone is not read: AMBIGUOUS)
    # time
    "s": ("second", "time"),
    "ms": ("millisecond", "time"),
    "us": ("microsecond", "time"),
    "ns": ("nanosecond", "time"),
    "min": ("minute", "time"),
    "h": ("hour", "time"),
    "d": ("day", "time"),
    "week": ("week", "time"),  # 7 d, exactly
    "fortnight": ("fortnight", "time"),  # 14 d, exactly
    # electric current
    "A": ("ampere", "current"),
    "kA": ("kiloampere", "current"),
    "mA": ("milliampere", "current"),
    "uA": ("microampere", "current"),
    "nA": ("nanoampere", "current"),
    "pA": ("picoampere", "current"),
    # voltage
    "V": ("volt", "voltage"),
    "kV": ("kilovolt", "voltage"),
    "mV": ("millivolt", "voltage"),
    "uV": ("microvolt", "voltage"),
    # power
    "W": ("watt", "power"),
    "MW": ("megawatt", "power"),
    "kW": ("kilowatt", "power"),
    "mW": ("milliwatt", "power"),
    "uW": ("microwatt", "power"),
    # energy
    "J": ("joule", "energy"),
    "kJ": ("kilojoule", "energy"),
    "MJ": ("megajoule", "energy"),
    "mJ": ("millijoule", "energy"),
    "uJ": ("microjoule", "energy"),
    "Wh": ("watt_hour", "energy"),
    "mWh": ("milliwatt_hour", "energy"),
    "kWh": ("kilowatt_hour", "energy"),
    "MWh": ("megawatt_hour", "energy"),
    "eV": ("electron_volt", "energy"),
    # electric charge ("C" alone is not read: AMBIGUOUS)
    "coulomb": ("coulomb", "charge"),
    "Ah": ("ampere_hour", "charge"),
    "mAh": ("milliampere_hour", "charge"),
    # resistance, capacitance ("F" alone is not read: AMBIGUOUS), inductance
    "ohm": ("ohm", "resistance"),
    "mohm": ("milliohm", "resistance"),
    "kohm": ("kiloohm", "resistance"),
    "Mohm": ("megaohm", "resistance"),
    "farad": ("farad", "capacitance"),
    "mF": ("millifarad", "capacitance"),
    "uF": ("microfarad", "capacitance"),
    "nF": ("nanofarad", "capacitance"),
    "pF": ("picofarad", "capacitance"),
    "H": ("henry", "inductance"),
    "mH": ("millihenry", "inductance"),
    "uH": ("microhenry", "inductance"),
    # frequency
    "Hz": ("hertz", "frequency"),
    "mHz": ("millihertz", "frequency"),
    "kHz": ("kilohertz", "frequency"),
    "MHz": ("megahertz", "frequency"),
    "GHz": ("gigahertz", "frequency"),
    # force and pressure
    "N": ("newton", "force"),
    "kN": ("kilonewton", "force"),
    "lbf": ("force_pound", "force"),
    "Pa": ("pascal", "pressure"),
    "mPa": ("millipascal", "pressure"),
    "kPa": ("kilopascal", "pressure"),
    "MPa": ("megapascal", "pressure"),
    "GPa": ("gigapascal", "pressure"),
    "bar": ("bar", "pressure"),
    "psi": ("psi", "pressure"),
    "ksi": ("ksi", "pressure"),
    # temperature: K; degC and degF (a reading when a value's whole unit, else a change); a change of temperature
    "K": ("kelvin", "temperature"),
    "degC": ("delta_degree_Celsius", "temperature"),
    "degF": ("delta_degree_Fahrenheit", "temperature"),
    "delta_degC": ("delta_degree_Celsius", "temperature change"),
    "delta_degF": ("delta_degree_Fahrenheit", "temperature change"),
    "delta_K": ("kelvin", "temperature change"),  # a change of temperature in kelvin: never read as a temperature
    # volume
    "L": ("liter", "volume"),
    "mL": ("milliliter", "volume"),
    "gal_us": ("US_liquid_gallon", "volume"),  # 231 in^3, exactly 3.785411784 L
    "gal_imp": ("imperial_gallon", "volume"),  # exactly 4.54609 L
    # angle (its own dimension here; see the module note)
    "deg": ("degree", "angle"),
    "arcmin": ("arcminute", "angle"),
    "arcsec": ("arcsecond", "angle"),
    "rad": ("radian", "angle"),
    # a plain ratio
    "%": ("percent", "ratio"),
    # decibels: a gain or a loss (its own dimension), and power levels (decibels.py)
    "dB": (None, "a gain or loss in decibels"),
    "dBm": (None, "a power level, in dB above 1 mW"),
    "dBW": (None, "a power level, in dB above 1 W"),
    # money (see the module note)
    **{code: (None, f"money in {code}") for code in CURRENCIES},
}

# The spellings above that carry no SI prefix. Every other spelling is an SI
# prefix and one of these (or an SI symbol in OTHER_SYMBOLS), and means
# exactly that: tests/test_units.py holds each to it.
UNPREFIXED: frozenset[str] = frozenset({
    "m", "in", "ft", "mil", "furlong", "g", "t", "ct", "lb", "oz", "ozt", "dwt", "grain", "s", "min", "h", "d", "week",
    "fortnight", "A", "V", "W", "J", "Wh", "eV", "coulomb", "Ah", "ohm", "farad", "H", "Hz", "N", "lbf", "Pa", "bar",
    "psi", "ksi", "K", "degC", "degF", "delta_degC", "delta_degF", "delta_K", "L", "gal_us", "gal_imp", "deg", "arcmin",
    "arcsec", "rad", "%", "dB", "dBm", "dBW", *CURRENCIES,
})

# SI prefixes, case-sensitive: the case of a prefix is its size. "u", "µ"
# (micro sign) and "μ" (Greek mu) are all micro.
SI_PREFIXES: dict[str, int] = {
    "Q": 30, "R": 27, "Y": 24, "Z": 21, "E": 18, "P": 15, "T": 12, "G": 9, "M": 6, "k": 3, "h": 2, "da": 1,
    "d": -1, "c": -2, "m": -3, "u": -6, "µ": -6, "μ": -6, "n": -9, "p": -12, "f": -15, "a": -18, "z": -21,
    "y": -24, "r": -27, "q": -30,
}

# Unit symbols of the SI and of units accepted with it that are not in the
# vocabulary, each with pint's name for it. flo2-calc never reads them as a
# unit; a hint reads text against them, so that "mS" (a millisiemens) is
# never answered with "ms", nor "mM" (a millimolar) with "mm".
OTHER_SYMBOLS: dict[str, str] = {
    "C": "coulomb", "F": "farad", "S": "siemens", "T": "tesla", "Wb": "weber", "mol": "mole", "cd": "candela",
    "lm": "lumen", "lx": "lux", "Bq": "becquerel", "Gy": "gray", "Sv": "sievert", "kat": "katal",
    "sr": "steradian", "Da": "dalton", "ha": "hectare", "au": "astronomical_unit", "l": "liter", "Ω": "ohm",
    "M": "molar", "a": "year",
}

# Spellings people and agents reach for that flo2-calc refuses, each with the
# spelling to use instead. A hint, never a guess: the call is still refused.
# Each one means exactly what its target means (tests/test_units.py).
NEAR_MISSES: dict[str, str] = {
    "µm": "um", "μm": "um", "micron": "um", "microns": "um",
    "µg": "ug", "μg": "ug", "µs": "us", "μs": "us", "µA": "uA", "μA": "uA", "µV": "uV", "μV": "uV",
    "µW": "uW", "μW": "uW", "µF": "uF", "μF": "uF", "µH": "uH", "μH": "uH", "µJ": "uJ", "μJ": "uJ",
    "Ω": "ohm", "mΩ": "mohm", "kΩ": "kohm", "MΩ": "Mohm", "ohms": "ohm",
    "coulombs": "coulomb", "farads": "farad",
    "sec": "s", "secs": "s", "second": "s", "seconds": "s", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "mins": "min", "minute": "min", "minutes": "min", "day": "d", "days": "d",
    "inch": "in", "inches": "in", '"': "in", "feet": "ft", "foot": "ft", "thou": "mil", "furlongs": "furlong",
    "fortnights": "fortnight", "weeks": "week", "decibel": "dB", "decibels": "dB",
    "troy_ounce": "ozt", "troy_ounces": "ozt", "pennyweight": "dwt", "pennyweights": "dwt", "grains": "grain",
    "°": "deg", "degree": "deg", "degrees": "deg", "radian": "rad", "radians": "rad",
    "arcminute": "arcmin", "arcminutes": "arcmin", "arcsecond": "arcsec", "arcseconds": "arcsec",
    "°C": "degC", "℃": "degC", "°F": "degF", "℉": "degF",
    "l": "L", "ml": "mL", "litre": "L", "liter": "L",
    "amp": "A", "amps": "A", "volt": "V", "volts": "V", "watt": "W", "watts": "W",
    "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg", "tonne": "t", "lbs": "lb",
    "mm2": "mm^2", "mm3": "mm^3", "m2": "m^2", "m3": "m^3", "cm2": "cm^2", "cm3": "cm^3",
    "mm²": "mm^2", "mm³": "mm^3", "m²": "m^2", "m³": "m^3",
    "percent": "%",
    "€": "EUR",
}

# Spellings that name more than one unit. Each is refused with every reading
# named, and none chosen.
AMBIGUOUS: dict[str, str] = {
    "C": (
        '"C" is the SI symbol for the coulomb, but it is often written for degrees Celsius, so flo2-calc reads it '
        'as neither. For a temperature write "degC" (a reading, "25 degC") or "delta_degC" (a change, '
        '"5 delta_degC"); for an electric charge write "coulomb" (or "Ah", "mAh").'
    ),
    "F": (
        '"F" is the SI symbol for the farad, but it is often written for degrees Fahrenheit, so flo2-calc reads it '
        'as neither. For a temperature write "degF" (a reading, "77 degF") or "delta_degF" (a change); for a '
        'capacitance write "farad" (or "mF", "uF", "nF", "pF").'
    ),
    "C°": '"C°" could be a temperature ("degC") or a change of temperature ("delta_degC"); write the one you mean.',
    "F°": '"F°" could be a temperature ("degF") or a change of temperature ("delta_degF"); write the one you mean.',
    "gr": (
        '"gr" is written for the grain and, in some places, for the gram, which is about 15 times larger, so '
        'flo2-calc reads it as neither. Write "grain" (exactly 64.79891 mg) or "g".'
    ),
    **dict.fromkeys(
        ("gal", "gallon", "gallons"),
        "A gallon is two different units: the US gallon (\"gal_us\", 231 in^3, exactly 3.785411784 L) and the "
        "imperial gallon (\"gal_imp\", exactly 4.54609 L). Write the one you mean.",
    ),
    "$": (
        '"$" is the sign of many currencies (USD, CAD, AUD, HKD, SGD and others), so flo2-calc does not guess one. '
        "Write the ISO 4217 code of the one you mean."
    ),
    "¥": '"¥" is the sign of both the Japanese yen (JPY) and the Chinese renminbi (CNY). Write the code of the one you mean.',
    "£": '"£" is the sign of the pound sterling (GBP) and of other pounds. Write the ISO 4217 code of the one you mean.',
}

ANGLES: dict[str, tuple[str, Fraction]] = {
    # spelling -> (its dimension, its exact factor to the first unit of that dimension)
    "deg": ("[angle, in deg]", Fraction(1)),
    "arcmin": ("[angle, in deg]", Fraction(1, 60)),
    "arcsec": ("[angle, in deg]", Fraction(1, 3600)),
    "rad": ("[angle, in rad]", Fraction(1)),
}
# Units flo2-calc defines itself, as an exact multiple of another vocabulary unit, where pint's differs.
DEFINED: dict[str, tuple[Fraction, str]] = {
    "furlong": (Fraction(660), "ft"),  # the international furlong; pint's is the US survey one
}
# Decibels, each its own dimension (decibels.py holds the levels' rules).
DECIBELS: dict[str, str] = {"dB": "[gain, in dB]", "dBm": "[power level, in dB above 1 mW]", "dBW": "[power level, in dB above 1 W]"}
LEVELS = ("dBm", "dBW")  # a power level: read only as a value's whole unit
PERCENT = "%"
SCALES = ("degC", "degF")  # a temperature reading when one is a value's whole unit (temperature.py)
INTERVAL_OF = {"degC": "delta_degC", "degF": "delta_degF"}
MAX_POWER = 12
# What a few spellings are, where the spelling alone may not say (named in a hint's list of units of one kind).
CALLED: dict[str, str] = {
    "oz": "the avoirdupois ounce", "ozt": "the troy ounce", "dwt": "the pennyweight", "lb": "the avoirdupois pound",
    "ct": "the metric carat", "t": "the tonne", "mil": "a thousandth of an inch", "furlong": "660 ft",
    "gal_us": "the US gallon", "gal_imp": "the imperial gallon", "K": "a temperature or a change",
    "degC": "a temperature", "degF": "a temperature", "delta_degC": "a change", "delta_degF": "a change",
    "delta_K": "a change",
}

Unit = tuple[tuple[str, int], ...]
"""A unit: (spelling, exponent) pairs in the order they first appeared, no
zero exponents, each spelling once. () is a plain number."""

PLAIN: Unit = ()
KELVIN: Unit = (("K", 1),)
KELVIN_CHANGE: Unit = (("delta_K", 1),)

# Records of schema version 6 and older were made before delta_K: re-running
# one (record.py) evaluates it under the rules it was made with, where a
# change converted to K, a product in K and K minus a temperature were all a
# bare K. `before_delta_k()` sets that for the re-run only.
_DELTA_K: ContextVar[bool] = ContextVar("flo2_calc_delta_k", default=True)


def delta_k() -> bool:
    """Whether a K known to be a change of temperature is written delta_K (0.7.0
    and later, and every reply), or a bare K (a record of version 6 or older)."""
    return _DELTA_K.get()


@contextmanager
def before_delta_k() -> Iterator[None]:
    """Evaluate under the temperature rules of flo2-calc 0.6.1 and earlier."""
    token = _DELTA_K.set(False)
    try:
        yield
    finally:
        _DELTA_K.reset(token)


@dataclass(frozen=True)
class Atom:
    spelling: str
    factor: Fraction  # exact, to SI base units (to the first unit of its own dimension, for angles and money)
    dimension: tuple[tuple[str, int], ...]  # sorted base dimensions


@cache
def registry():
    """pint's registry, loaded once, with exact fractions for every number in
    its definitions (so 1 inch is exactly 127/5 mm)."""
    import pint

    return pint.UnitRegistry(non_int_type=Fraction, autoconvert_offset_to_baseunit=False)


def pint_version() -> str:
    import pint

    return pint.__version__


def _pint_atom(spelling: str, pint_name: str) -> Atom:
    ureg = registry()
    base = ureg.Quantity(Fraction(1), pint_name).to_base_units()
    factor = base.magnitude
    if not isinstance(factor, Fraction):
        factor = Fraction(factor)
    dims = ureg.get_dimensionality(pint_name)
    dimension = tuple(sorted((str(k), int(v)) for k, v in dims.items() if v != 0))
    return Atom(spelling, factor, dimension)


@cache
def atom(spelling: str) -> Atom:
    pint_name, _measures = VOCABULARY[spelling]
    if spelling in ANGLES:
        dim, f = ANGLES[spelling]
        return Atom(spelling, f, ((dim, 1),))
    if spelling in CURRENCIES:
        return Atom(spelling, Fraction(1), ((f"[money, in {spelling}]", 1),))
    if spelling in DECIBELS:
        return Atom(spelling, Fraction(1), ((DECIBELS[spelling], 1),))
    if spelling in DEFINED:
        times, of = DEFINED[spelling]
        base = atom(of)
        return Atom(spelling, times * base.factor, base.dimension)
    assert pint_name is not None
    return _pint_atom(spelling, pint_name)


@cache
def zero_in_kelvin(scale: str) -> Fraction:
    """Where a scale's zero is, in K: 273.15 for degC, 255.372... (45967/180) for degF. From pint, exactly."""
    absolute = {"degC": "degree_Celsius", "degF": "degree_Fahrenheit"}[scale]
    zero = registry().Quantity(Fraction(0), absolute).to("kelvin").magnitude
    return zero if isinstance(zero, Fraction) else Fraction(zero)


def measures(spelling: str) -> str:
    return VOCABULARY[spelling][1]


# ---------------------------------------------------------------- what text means as written (for hints)

Meaning = tuple[Fraction, tuple[tuple[str, int], ...], Fraction]
"""A unit's exact factor, its dimension, and where its zero is (in K, for a
temperature reading; 0 for every other unit)."""


@cache
def meaning(spelling: str) -> Meaning:
    """What a vocabulary spelling or an OTHER_SYMBOLS symbol means."""
    if spelling in VOCABULARY:
        a = atom(spelling)
        return a.factor, a.dimension, (zero_in_kelvin(spelling) if spelling in SCALES else Fraction(0))
    a = _pint_atom(spelling, OTHER_SYMBOLS[spelling])
    return a.factor, a.dimension, Fraction(0)


@cache
def _symbols_by_fold() -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {}
    for s in [*UNPREFIXED, *OTHER_SYMBOLS]:
        out.setdefault(s.casefold(), []).append(s)
    return {k: tuple(v) for k, v in out.items()}


@cache
def _vocabulary_by_fold() -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {}
    for s in VOCABULARY:
        out.setdefault(s.casefold(), []).append(s)
    return {k: tuple(v) for k, v in out.items()}


def readings(text: str) -> set[Meaning]:
    """Every unit `text` is, read as written: an SI prefix exactly as typed (or
    none), then a unit symbol. When some reading matches a symbol exactly, those
    are what was written ("pA" is a picoampere, whatever "Pa" is); only when
    none does is the symbol's case taken as a slip ("hz", "kOhm"). A prefix
    alone ("k") is its number. Empty when the text reads as nothing ("Nm")."""
    if text in SI_PREFIXES:
        return {(Fraction(10) ** SI_PREFIXES[text], (), Fraction(0))}
    exact: set[Meaning] = set()
    slipped: set[Meaning] = set()
    by_fold = _symbols_by_fold()
    for prefix, exponent in [("", 0), *SI_PREFIXES.items()]:
        rest = text[len(prefix):]
        if not text.startswith(prefix) or not rest:
            continue
        for symbol in by_fold.get(rest.casefold(), ()):
            f, dim, zero = meaning(symbol)
            (exact if symbol == rest else slipped).add((f * Fraction(10) ** exponent, dim, zero))
    return exact or slipped


CASE_NOTE = (
    " Units are case-sensitive, and flo2-calc does not guess a case: another case can be another size (m is milli, "
    "M is mega; p is pico, P is peta) or another quantity (Pa is pascal, pA is picoampere)."
)


def _hint(text: str) -> str:
    if text in AMBIGUOUS:
        return " " + AMBIGUOUS[text]
    if text in NEAR_MISSES:
        target = NEAR_MISSES[text]
        read = readings(text)
        if target in VOCABULARY and read and read != {meaning(target)}:
            return ""  # the text is another unit as written: never hinted (a guard; the list is tested)
        return f' Write "{target}".'
    candidates = _vocabulary_by_fold().get(text.casefold(), ())
    if not candidates:
        return _what_pint_reads(text)
    if len(text) == 1:
        # A one-letter symbol's case is all it has: S is siemens and s second, T tesla and t tonne.
        return CASE_NOTE
    # A case slip is hinted only when the text, read as written, is one unit and
    # that unit is the candidate: the same size and the same kind, never another.
    read = readings(text)
    safe = [c for c in candidates if read == {meaning(c)}]
    if len(safe) == 1:
        return f' Write "{safe[0]}" (units are case-sensitive).'
    return CASE_NOTE


@cache
def _by_pint_name() -> dict[str, tuple[str, ...]]:
    """The vocabulary's spellings by pint's name for the unit each one is (a
    reading's degC and degF, which flo2-calc maps to a change for its factor,
    and the units flo2-calc defines itself, left out)."""
    out: dict[str, list[str]] = {}
    for s, (pint_name, _measures) in VOCABULARY.items():
        if pint_name is not None and s not in SCALES and s not in DEFINED:
            out.setdefault(registry().get_name(pint_name), []).append(s)
    return {k: tuple(v) for k, v in out.items()}


def _pint_reading(text: str) -> tuple[str, tuple[tuple[str, int], ...], Meaning | None] | None:
    """(pint's name for `text`, what it measures, its meaning when pint can give
    it exactly), or None when pint reads `text` as no unit. Never raises."""
    if not re.fullmatch(r"[A-Za-z_]{2,40}", text):
        return None
    try:
        ureg = registry()
        name = ureg.get_name(text)
        dims = tuple(sorted((str(k), int(v)) for k, v in ureg.get_dimensionality(text).items() if v != 0))
    except Exception:  # noqa: BLE001 - pint reads it as nothing, or cannot say: no reading
        return None
    try:
        one = ureg.Quantity(Fraction(1), text).to_base_units().magnitude
        exact: Meaning | None = (Fraction(one), dims, Fraction(0))
    except Exception:  # noqa: BLE001 - an offset unit, or a definition pint cannot load exactly
        exact = None
    return name, dims, exact


def _what_pint_reads(text: str) -> str:
    """For a spelling flo2-calc does not know but pint reads ("ozt" before
    0.7.0, "mile", "kilometer"): what pint reads it as, and the units of that
    kind flo2-calc carries. Nothing is substituted: it says 'Write' only for a
    spelling of the vocabulary that IS that same pint unit (the same factor,
    kind and zero), and only when the text as written (`readings`) is that
    unit too. A dimensionless reading (pint's angular mil, its radian) is not
    named: angles and ratios are flo2-calc's own."""
    read = _pint_reading(text)
    if read is None:
        return ""
    name, dims, exact = read
    if not dims:
        return ""
    same = _by_pint_name().get(name, ())
    as_written = readings(text)
    if len(same) == 1 and exact is not None and meaning(same[0]) == exact and as_written == {exact}:
        return f' pint reads it as {name}, which is exactly "{same[0]}": Write "{same[0]}".'
    kind = [s for s in VOCABULARY if s not in CURRENCIES and s not in DECIBELS and s not in ANGLES
            and s != PERCENT and atom(s).dimension == dims]
    what = measures(kind[0]) if kind else " ".join(f"{d}^{p}" if p != 1 else d for d, p in dims)
    if as_written and exact is not None and exact not in as_written:
        return ""  # pint reads it as something other than its own prefix and symbol: say nothing either way
    listed = ", ".join(f"{s} ({CALLED[s]})" if s in CALLED else s for s in kind)
    carries = (
        f"The units of that kind flo2-calc knows: {listed}. Give the value in one of them, from a source that states it."
        if kind else "flo2-calc carries no unit of that kind."
    )
    return f" pint reads it as {name} ({what}), which flo2-calc does not carry, and flo2-calc substitutes nothing for it. {carries}"


# ---------------------------------------------------------------- reading


_ATOM_POWER = re.compile(r"^(?P<atom>[^*/^()\s]+)(?:\^(?P<exp>-?\d+))?$")


class UnitTextError(ValueError):
    """A unit's text that cannot be read, with the reason."""


def _unknown(spelling: str, whole: str) -> UnitTextError:
    hint = _hint(spelling) or (_hint(whole) if whole != spelling else "")
    return UnitTextError(
        f'"{spelling}" is not a unit flo2-calc knows.{hint} Units are spelled as reflow2 spells them '
        "(mm, g, V, mA ...); an unknown one is refused, never guessed."
    )


def _read_atom_power(text: str, whole: str) -> tuple[str, int]:
    m = _ATOM_POWER.match(text)
    if not m:
        raise UnitTextError(
            f'"{whole}" is not a unit flo2-calc reads: join units with "*", raise them with "^n", '
            'and divide with one "/", e.g. "mm^2", "m/s^2", "kg/(m*s^2)".'
        )
    spelling = m.group("atom")
    if spelling not in VOCABULARY:
        raise _unknown(spelling, whole)
    exp = int(m.group("exp")) if m.group("exp") is not None else 1
    if exp == 0 or abs(exp) > MAX_POWER:
        raise UnitTextError(f'"{text}": a power in a unit is a whole number from -{MAX_POWER} to {MAX_POWER}, not 0.')
    return spelling, exp


def parse_unit(text: str) -> Unit:
    """A unit from its text ("" is a plain number). Raises UnitTextError.

    "degC" or "degF" alone is a temperature reading. Written inside a compound
    that reduces to it ("degC*W/W"), it is a change of temperature, and is
    read as delta_degC (delta_degF)."""
    whole = text.strip()
    if whole == "":
        return PLAIN
    if len(whole) > 80:
        raise UnitTextError("a unit is at most 80 characters")
    if whole in NEAR_MISSES or whole in AMBIGUOUS:
        raise _unknown(whole, whole)
    if whole.count("/") > 1:
        raise UnitTextError(f'"{whole}" has more than one "/"; write one, with a product in brackets after it, e.g. "kg/(m*s^2)".')
    numerator, _, denominator = whole.partition("/")
    pairs: list[tuple[str, int]] = []
    if numerator != "1":
        for part in numerator.split("*"):
            pairs.append(_read_atom_power(part, whole))
    if denominator:
        if denominator.startswith("(") and denominator.endswith(")"):
            parts = denominator[1:-1].split("*")
        elif "*" in denominator or "(" in denominator or ")" in denominator:
            raise UnitTextError(f'"{whole}": after "/", put a product in brackets, e.g. "kg/(m*s^2)".')
        else:
            parts = [denominator]
        for part in parts:
            spelling, exp = _read_atom_power(part, whole)
            pairs.append((spelling, -exp))
    elif numerator == "1":
        raise UnitTextError(f'"{whole}" is not a unit; a plain number has no unit at all.')
    unit = _combine(pairs)
    levels = [s for s, _ in pairs if s in LEVELS]
    if levels and unit != ((levels[0], 1),):
        raise UnitTextError(
            f'"{whole}": {levels[0]} is a power level (dB above a reference power), and flo2-calc reads a level only '
            f'as a value\'s whole unit ("-30 {levels[0]}"), never inside a compound unit or raised to a power.'
        )
    return as_change(unit, compound=True) if len(pairs) > 1 else unit


def _combine(pairs: list[tuple[str, int]]) -> Unit:
    out: dict[str, int] = {}
    for spelling, exp in pairs:
        out[spelling] = out.get(spelling, 0) + exp
    return tuple((s, e) for s, e in out.items() if e != 0)


# ---------------------------------------------------------------- writing


def _power(spelling: str, exp: int) -> str:
    return spelling if exp == 1 else f"{spelling}^{exp}"


def format_unit(unit: Unit) -> str:
    if not unit:
        return ""
    num = [_power(s, e) for s, e in unit if e > 0]
    den = [_power(s, -e) for s, e in unit if e < 0]
    top = "*".join(num) if num else "1"
    if not den:
        return top
    bottom = den[0] if len(den) == 1 else "(" + "*".join(den) + ")"
    return f"{top}/{bottom}"


def show(unit: Unit) -> str:
    """A unit as a message names it: plain numbers say so."""
    return format_unit(unit) or "a plain number (no unit)"


# ---------------------------------------------------------------- temperatures


def scale_of(unit: Unit) -> str | None:
    """"degC" or "degF" when a value with this unit is a temperature reading on
    that scale: the scale is its whole unit. None for every other unit."""
    if len(unit) == 1 and unit[0][1] == 1 and unit[0][0] in SCALES:
        return unit[0][0]
    return None


def as_change(unit: Unit, compound: bool = False) -> Unit:
    """A computed unit that came out as a bare degC or degF is a change of
    temperature (2.5 degC/W * 4 W is a rise of 10 delta_degC), never a reading.
    So is a bare K that came out of a `compound` (2.5 K/W * 4 W is 10 delta_K):
    a degree inside a compound unit is a change."""
    scale = scale_of(unit)
    if scale:
        return ((INTERVAL_OF[scale], 1),)
    if compound and unit == KELVIN and delta_k():
        return KELVIN_CHANGE
    return unit


def _plain_or_percent(unit: Unit) -> bool:
    return all(s == PERCENT for s, _ in unit)


def converted_unit(from_unit: Unit, to_unit: Unit) -> Unit:
    """The unit convert writes its result in: the node's, except that a change
    of temperature converted to K stays a change, delta_K (exactly the size of
    K). A change is never turned into a temperature, by convert or by what
    convert writes."""
    if to_unit == KELVIN and delta_k() and from_unit != KELVIN and scale_of(from_unit) is None and dimension(from_unit) == dimension(KELVIN):
        return KELVIN_CHANGE
    return to_unit


# ---------------------------------------------------------------- what a unit measures


def dimension(unit: Unit) -> tuple[tuple[str, int], ...]:
    total: dict[str, int] = {}
    for spelling, exp in unit:
        for dim, power in atom(spelling).dimension:
            total[dim] = total.get(dim, 0) + power * exp
    return tuple(sorted((d, p) for d, p in total.items() if p != 0))


def factor(unit: Unit) -> Fraction:
    """The exact factor from this unit to SI base units."""
    f = Fraction(1)
    for spelling, exp in unit:
        f *= atom(spelling).factor ** exp
    return f


def describe_dimension(unit: Unit) -> str:
    if len(unit) == 1 and unit[0][1] == 1:
        return measures(unit[0][0])
    dims = dimension(unit)
    if not dims:
        return "a plain ratio" if unit else "a plain number"
    return " ".join(f"{d}^{p}" if p != 1 else d for d, p in dims)


def _angle_kinds(unit: Unit) -> set[str]:
    return {ANGLES[s][0] for s, _ in unit if s in ANGLES}


def currencies_in(unit: Unit) -> set[str]:
    return {s for s, _ in unit if s in CURRENCIES}


def gain_in(unit: Unit) -> bool:
    """Whether a unit measures a gain in dB (dB, or dB inside a compound that still measures one)."""
    return dimension(unit) == ((DECIBELS["dB"], 1),)


DB_IS_NOT_A_RATIO = (
    "a gain or loss in dB and a plain ratio are different things, so they are never mixed silently. A gain in dB "
    "becomes a ratio only through db_to_ratio, and a ratio becomes dB only through ratio_to_db, each told whether it "
    'is a power ratio ("kind": "power", 10 log10) or an amplitude ratio ("kind": "amplitude", 20 log10): 10 dB is a '
    "power ratio of 10 and an amplitude ratio of about 3.16, and flo2-calc never picks one."
)


NO_RATES = (
    "flo2-calc holds no exchange rates, so it never turns one currency into another. Give the rate as an input, "
    'with its date and source (for example "0.92 EUR/USD", source "ECB reference rate, 2026-10-02"), and multiply '
    "by it."
)


def conversion(from_unit: Unit, to_unit: Unit, operation: str) -> Fraction:
    """The exact factor turning a value in `from_unit` into `to_unit`.

    Raises Refusal when they measure different things. For an operation that
    combines values, `to_unit` is the first operand's, so the message names
    the units in the order the operands came; for convert it says which unit
    could not be turned into which. (A temperature reading is converted by
    temperature.py, never here: it has an offset, not only a factor.)"""
    if from_unit == to_unit:
        return Fraction(1)
    if dimension(from_unit) != dimension(to_unit):
        if operation == "convert":
            said = f"convert cannot turn {show(from_unit)} into {show(to_unit)}"
            first, second = from_unit, to_unit
        else:
            said = f"{operation} cannot combine {show(to_unit)} and {show(from_unit)}"
            first, second = to_unit, from_unit
        named = (format_unit(first), format_unit(second))
        if (_angle_kinds(first) | _angle_kinds(second)) == {"[angle, in deg]", "[angle, in rad]"}:
            raise Refusal(
                f"{said}: deg and rad differ by the factor pi/180, which no exact number holds, so they are never "
                "mixed silently. Convert one first: a convert node turns deg into rad, or rad into deg, as a "
                "correctly rounded value labelled rounded.",
                kind="unit_mismatch",
                units=named,
            )
        if currencies_in(first) and currencies_in(second) and currencies_in(first) != currencies_in(second):
            raise Refusal(f"{said}: they are different currencies. {NO_RATES}", kind="unit_mismatch", units=named)
        if (gain_in(first) and not dimension(second)) or (gain_in(second) and not dimension(first)):
            raise Refusal(f"{said}: {DB_IS_NOT_A_RATIO}", kind="unit_mismatch", units=named)
        raise Refusal(
            f"{said}: they measure different things ({describe_dimension(first)} and "
            f"{describe_dimension(second)}). Nothing was computed, and no unit was dropped.",
            kind="unit_mismatch",
            units=named,
        )
    return factor(from_unit) / factor(to_unit)


def multiply(left: Unit, right: Unit) -> tuple[Unit, Fraction]:
    """The unit of left * right, and the exact factor the magnitude takes.

    A right-hand atom that measures the same single thing as a left-hand one
    is converted into it, so 2 m * 3 mm is 0.006 m^2, not 6 m*mm. A "%" is
    folded into the magnitude (it is exactly 1/100) unless the result is a
    plain percentage, so 200 g * 5 % is 10 g and 10 % * 2 is 20 %. A result
    that comes out as a bare degC or degF is a change of temperature."""
    out: dict[str, int] = dict(left)
    scale = Fraction(1)
    for spelling, exp in right:
        if spelling in out:
            out[spelling] += exp
            continue
        dim = atom(spelling).dimension
        twin = next(
            (s for s in out if s != PERCENT and dim and atom(s).dimension == dim),
            None,
        )
        if twin is not None:
            scale *= (atom(spelling).factor / atom(twin).factor) ** exp
            out[twin] += exp
        else:
            out[spelling] = exp
    unit, fold = fold_percent(tuple((s, e) for s, e in out.items() if e != 0))
    # A bare K is a change when it came through a compound, not straight from a K scaled by a plain number.
    straight = (fold_percent(left)[0] == KELVIN and _plain_or_percent(right)) or (_plain_or_percent(left) and fold_percent(right)[0] == KELVIN)
    return as_change(unit, compound=not straight), scale * fold


def fold_percent(unit: Unit) -> tuple[Unit, Fraction]:
    """Fold a "%" into the magnitude unless the unit is a plain percentage."""
    if unit == ((PERCENT, 1),) or not any(s == PERCENT for s, _ in unit):
        return unit, Fraction(1)
    exp = dict(unit)[PERCENT]
    return tuple((s, e) for s, e in unit if s != PERCENT), Fraction(1, 100) ** exp


def invert(unit: Unit) -> Unit:
    return tuple((s, -e) for s, e in unit)


def power(unit: Unit, n: int) -> tuple[Unit, Fraction]:
    """The unit of a value raised to the whole number n, and the factor its
    magnitude takes (only a folded "%" gives one)."""
    out, fold = fold_percent(tuple((s, e * n) for s, e in unit if e * n != 0))
    return as_change(out, compound=fold_percent(unit)[0] != KELVIN), fold


# ---------------------------------------------------------------- angles, for trigonometry and deg-rad conversion

DEG_DIMENSION, RAD_DIMENSION = ANGLES["deg"][0], ANGLES["rad"][0]
ANGLE_DIMENSIONS = {DEG_DIMENSION: "deg", RAD_DIMENSION: "rad"}


def angle_kind(unit: Unit) -> tuple[str, Fraction] | None:
    """("deg" or "rad", the exact factor turning a magnitude in `unit` into
    that) when the unit measures one plain angle: deg, arcmin and arcsec are
    of the deg kind (factors 1, 1/60, 1/3600), rad of the rad kind. None
    otherwise."""
    dims = dimension(unit)
    if len(dims) == 1 and dims[0][1] == 1 and dims[0][0] in ANGLE_DIMENSIONS:
        return ANGLE_DIMENSIONS[dims[0][0]], factor(unit)
    return None


def pi_conversion(from_unit: Unit, to_unit: Unit) -> tuple[Fraction, int] | None:
    """For two units that measure the same thing except that one counts
    angles in deg (or arcmin, arcsec) and the other in rad (deg into rad,
    arcsec into rad, rad/s into deg/s ...):
    (f, k) such that a value v in from_unit is v * f * (pi/180)^k in to_unit,
    f exact. None when they differ in anything else."""

    def split(unit: Unit) -> tuple[int, int, dict[str, int]]:
        dims = dict(dimension(unit))
        deg = dims.pop(DEG_DIMENSION, 0)
        rad = dims.pop(RAD_DIMENSION, 0)
        return deg, rad, dims

    deg_f, rad_f, rest_f = split(from_unit)
    deg_t, rad_t, rest_t = split(to_unit)
    if rest_f != rest_t or deg_f + rad_f != deg_t + rad_t or deg_f == deg_t:
        return None
    return factor(from_unit) / factor(to_unit), deg_f - deg_t


# ---------------------------------------------------------------- a computed unit, shown simpler (dec:round-2-fixes)

# Never chosen as the unit to show a value in: a temperature reading (a degree
# inside a compound is a change), and a percentage.
_NEVER_SHOWN_IN = frozenset({"degC", "degF", PERCENT})
# Not chosen by size alone (rule 2), being one size with K: a change of temperature.
_NOT_BY_SIZE = frozenset({"delta_degC", "delta_degF", "delta_K", *LEVELS})


@cache
def _by_size() -> dict[tuple[tuple[tuple[str, int], ...], Fraction], str]:
    """Each single unit of the vocabulary (one spelling, to the power 1), keyed
    by what it measures and its exact size. No two share a key
    (tests/test_units.py), so rule 2 of `simplify` never has to choose."""
    out: dict[tuple[tuple[tuple[str, int], ...], Fraction], str] = {}
    for s in VOCABULARY:
        if s in _NEVER_SHOWN_IN or s in _NOT_BY_SIZE:
            continue
        a = atom(s)
        out.setdefault((a.dimension, a.factor), s)
    return out


def simplify(unit: Unit) -> tuple[Unit, Fraction] | None:
    """The unit to SHOW a computed value in, when it is simpler than the unit it
    was computed in, and the exact factor its number takes (the number in
    `unit` times the factor is the number in the simpler unit); None when the
    unit is shown as it is. Only what is shown changes: the value, its
    dimension and its exact fraction do not. The rule, in this order:

      0. A unit of one spelling (mm, mm^2, 1/s, degC, %) is shown as it is.
      1. A compound that measures nothing at all (mm/m, a plain ratio) is
         shown as a plain number.
      2. A compound that is exactly the size of one unit of the vocabulary that
         measures the same thing is shown in that unit, and the number does not
         change: mAh/mA is h, V/mA is kohm, V*mA is mW, kPa*m^2 is kN,
         uF*V^2 is uJ.
      3. Otherwise, a compound that measures what one of its own spellings
         measures is shown in the first such spelling: um^2/m (a length) in um.
         A degree inside a compound is a change of temperature, so degC is
         shown as delta_degC, and K as delta_K (rule 2's K too).
      4. Otherwise it is shown as it is: m/s, kg/(m*s^2), lbf*ft.

    It never chooses across dimensions, never a temperature reading or a
    percentage."""
    if len(unit) <= 1:
        return None
    dims = dimension(unit)
    size = factor(unit)
    if not dims:
        return PLAIN, size
    exact = _by_size().get((dims, size))
    if exact is not None:
        return as_change(((exact, 1),), compound=True), Fraction(1)
    for spelling, _exp in unit:
        if atom(spelling).dimension == dims and spelling != PERCENT:
            shown = as_change(((spelling, 1),), compound=True)
            return shown, size / factor(shown)
    return None


def latex(unit: Unit) -> str:
    """A unit as LaTeX: \\mathrm{mm}^{2}, \\mathrm{m}/\\mathrm{s}^{2}."""

    def one(spelling: str, exp: int) -> str:
        name = spelling.replace("\\", "").replace("%", r"\%").replace("_", r"\_")
        return r"\mathrm{" + name + "}" + ("" if exp == 1 else "^{" + str(exp) + "}")

    num = [one(s, e) for s, e in unit if e > 0]
    den = [one(s, -e) for s, e in unit if e < 0]
    top = r"\cdot ".join(num) if num else "1"
    if not den:
        return top
    bottom = den[0] if len(den) == 1 else r"\left(" + r"\cdot ".join(den) + r"\right)"
    return top + "/" + bottom
