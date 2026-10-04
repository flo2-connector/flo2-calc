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
    arcsec and the two gallons; degC and degF as temperatures with an offset.

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
    temperature, and multiplies like any other unit.
  - "mil" is the thousandth of an inch (pint's "thou"), not pint's angular mil.
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
from dataclasses import dataclass
from fractions import Fraction
from functools import cache

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
    # mass
    "kg": ("kilogram", "mass"),
    "g": ("gram", "mass"),
    "mg": ("milligram", "mass"),
    "ug": ("microgram", "mass"),
    "t": ("metric_ton", "mass"),
    "ct": ("carat", "mass"),
    "lb": ("pound", "mass"),
    "oz": ("ounce", "mass"),
    # time
    "s": ("second", "time"),
    "ms": ("millisecond", "time"),
    "us": ("microsecond", "time"),
    "ns": ("nanosecond", "time"),
    "min": ("minute", "time"),
    "h": ("hour", "time"),
    "d": ("day", "time"),
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
    # money (see the module note)
    **{code: (None, f"money in {code}") for code in CURRENCIES},
}

# The spellings above that carry no SI prefix. Every other spelling is an SI
# prefix and one of these (or an SI symbol in OTHER_SYMBOLS), and means
# exactly that: tests/test_units.py holds each to it.
UNPREFIXED: frozenset[str] = frozenset({
    "m", "in", "ft", "mil", "g", "t", "ct", "lb", "oz", "s", "min", "h", "d", "A", "V", "W", "J", "Wh", "eV",
    "coulomb", "Ah", "ohm", "farad", "H", "Hz", "N", "lbf", "Pa", "bar", "psi", "ksi", "K", "degC", "degF",
    "delta_degC", "delta_degF", "L", "gal_us", "gal_imp", "deg", "arcmin", "arcsec", "rad", "%", *CURRENCIES,
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
    "inch": "in", "inches": "in", '"': "in", "feet": "ft", "foot": "ft", "thou": "mil",
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
PERCENT = "%"
SCALES = ("degC", "degF")  # a temperature reading when one is a value's whole unit (temperature.py)
INTERVAL_OF = {"degC": "delta_degC", "degF": "delta_degF"}
MAX_POWER = 12

Unit = tuple[tuple[str, int], ...]
"""A unit: (spelling, exponent) pairs in the order they first appeared, no
zero exponents, each spelling once. () is a plain number."""

PLAIN: Unit = ()
KELVIN: Unit = (("K", 1),)


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
        return ""
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
    return as_change(unit) if len(pairs) > 1 else unit


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


def as_change(unit: Unit) -> Unit:
    """A computed unit that came out as a bare degC or degF is a change of
    temperature (2.5 degC/W * 4 W is a rise of 10 delta_degC), never a reading."""
    scale = scale_of(unit)
    return ((INTERVAL_OF[scale], 1),) if scale else unit


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
    return as_change(unit), scale * fold


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
    return as_change(out), fold


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
