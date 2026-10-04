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
    guessed. A near miss ("MM", "µm", "Ω") is answered with the spelling to
    use, and still refused.

WHO DOES WHAT. The vocabulary below maps each spelling to a pint unit. pint,
loaded with exact fractions, says what each unit measures (its dimension) and
its exact factor to SI base units; flo2-calc's own code does every piece of
arithmetic on those fractions. pint's float arithmetic is never used.

TWO DELIBERATE DEPARTURES FROM pint:
  - Angles are their own dimension. pint calls deg and rad dimensionless, so
    it would let "30 deg + 1" through; flo2-calc refuses it. And deg and rad
    are never mixed in one operation, because their ratio is pi/180, which no
    fraction holds exactly. Only `convert` turns one into the other
    (`pi_conversion`), and its result is a correctly rounded value labelled
    rounded (realmath.py), never an exact one.
  - Temperatures are kelvin only. A scale with an offset (degC, degF) does
    not add or multiply like a unit, so it is not in the vocabulary.

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

# spelling -> (pint unit, what it measures, for the reader)
VOCABULARY: dict[str, tuple[str, str]] = {
    # length
    "m": ("meter", "length"),
    "km": ("kilometer", "length"),
    "cm": ("centimeter", "length"),
    "mm": ("millimeter", "length"),
    "um": ("micrometer", "length"),
    "nm": ("nanometer", "length"),
    "in": ("inch", "length"),
    "ft": ("foot", "length"),
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
    "Wh": ("watt_hour", "energy"),
    "mWh": ("milliwatt_hour", "energy"),
    "kWh": ("kilowatt_hour", "energy"),
    "eV": ("electron_volt", "energy"),
    # electric charge
    "C": ("coulomb", "charge"),
    "Ah": ("ampere_hour", "charge"),
    "mAh": ("milliampere_hour", "charge"),
    # resistance, capacitance, inductance
    "ohm": ("ohm", "resistance"),
    "kohm": ("kiloohm", "resistance"),
    "Mohm": ("megaohm", "resistance"),
    "F": ("farad", "capacitance"),
    "mF": ("millifarad", "capacitance"),
    "uF": ("microfarad", "capacitance"),
    "nF": ("nanofarad", "capacitance"),
    "pF": ("picofarad", "capacitance"),
    "H": ("henry", "inductance"),
    "mH": ("millihenry", "inductance"),
    "uH": ("microhenry", "inductance"),
    # frequency
    "Hz": ("hertz", "frequency"),
    "kHz": ("kilohertz", "frequency"),
    "MHz": ("megahertz", "frequency"),
    "GHz": ("gigahertz", "frequency"),
    # force and pressure
    "N": ("newton", "force"),
    "kN": ("kilonewton", "force"),
    "Pa": ("pascal", "pressure"),
    "kPa": ("kilopascal", "pressure"),
    "MPa": ("megapascal", "pressure"),
    "GPa": ("gigapascal", "pressure"),
    "bar": ("bar", "pressure"),
    # temperature, absolute only
    "K": ("kelvin", "temperature"),
    # volume
    "L": ("liter", "volume"),
    "mL": ("milliliter", "volume"),
    # angle (its own dimension here; see the module note)
    "deg": ("degree", "angle"),
    "rad": ("radian", "angle"),
    # a plain ratio
    "%": ("percent", "ratio"),
}

# Spellings people and agents reach for that flo2-calc refuses, each with the
# spelling to use instead. A hint, never a guess: the call is still refused.
NEAR_MISSES: dict[str, str] = {
    "µm": "um", "μm": "um", "micron": "um", "microns": "um",
    "µg": "ug", "μg": "ug", "µs": "us", "μs": "us", "µA": "uA", "μA": "uA", "µV": "uV", "μV": "uV",
    "µW": "uW", "μW": "uW", "µF": "uF", "μF": "uF", "µH": "uH", "μH": "uH",
    "Ω": "ohm", "kΩ": "kohm", "MΩ": "Mohm", "ohms": "ohm",
    "sec": "s", "secs": "s", "second": "s", "seconds": "s", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "mins": "min", "minute": "min", "minutes": "min", "day": "d", "days": "d",
    "inch": "in", "inches": "in", '"': "in", "feet": "ft", "foot": "ft",
    "°": "deg", "degree": "deg", "degrees": "deg", "radian": "rad", "radians": "rad",
    "l": "L", "ml": "mL", "litre": "L", "liter": "L",
    "amp": "A", "amps": "A", "volt": "V", "volts": "V", "watt": "W", "watts": "W",
    "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg", "tonne": "t",
    "mm2": "mm^2", "mm3": "mm^3", "m2": "m^2", "m3": "m^3", "cm2": "cm^2", "cm3": "cm^3",
    "mm²": "mm^2", "mm³": "mm^3", "m²": "m^2", "m³": "m^3",
    "percent": "%", "pct": "%",
}

ANGLE_PSEUDO_DIMENSION = {"deg": "[angle, in deg]", "rad": "[angle, in rad]"}
PERCENT = "%"
OFFSET_SCALES = {"°C", "degC", "℃", "°F", "degF", "℉", "C°"}
MAX_POWER = 12

Unit = tuple[tuple[str, int], ...]
"""A unit: (spelling, exponent) pairs in the order they first appeared, no
zero exponents, each spelling once. () is a plain number."""

PLAIN: Unit = ()


@dataclass(frozen=True)
class Atom:
    spelling: str
    factor: Fraction  # exact, to SI base units (to itself, for deg and rad)
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


@cache
def atom(spelling: str) -> Atom:
    pint_name, _measures = VOCABULARY[spelling]
    if spelling in ANGLE_PSEUDO_DIMENSION:
        return Atom(spelling, Fraction(1), ((ANGLE_PSEUDO_DIMENSION[spelling], 1),))
    ureg = registry()
    base = ureg.Quantity(Fraction(1), pint_name).to_base_units()
    factor = base.magnitude
    if not isinstance(factor, Fraction):
        factor = Fraction(factor)
    dims = ureg.get_dimensionality(pint_name)
    dimension = tuple(sorted((str(k), int(v)) for k, v in dims.items() if v != 0))
    return Atom(spelling, factor, dimension)


def measures(spelling: str) -> str:
    return VOCABULARY[spelling][1]


# ---------------------------------------------------------------- reading


_ATOM_POWER = re.compile(r"^(?P<atom>[^*/^()\s]+)(?:\^(?P<exp>-?\d+))?$")


class UnitTextError(ValueError):
    """A unit's text that cannot be read, with the reason."""


def _hint(text: str) -> str:
    if text in OFFSET_SCALES:
        return (
            f' "{text}" is a temperature scale with an offset, which does not add or multiply like a unit; '
            "flo2-calc takes absolute temperatures in K."
        )
    if text in NEAR_MISSES:
        return f' Write "{NEAR_MISSES[text]}".'
    for known in VOCABULARY:
        if known.lower() == text.lower():
            return f' Write "{known}" (units are case-sensitive).'
    return ""


def _read_atom_power(text: str, whole: str) -> tuple[str, int]:
    m = _ATOM_POWER.match(text)
    if not m:
        raise UnitTextError(
            f'"{whole}" is not a unit flo2-calc reads: join units with "*", raise them with "^n", '
            'and divide with one "/", e.g. "mm^2", "m/s^2", "kg/(m*s^2)".'
        )
    spelling = m.group("atom")
    if spelling not in VOCABULARY:
        hint = _hint(spelling) or _hint(whole)
        raise UnitTextError(
            f'"{spelling}" is not a unit flo2-calc knows.{hint} Units are spelled as reflow2 spells them '
            "(mm, g, V, mA ...); an unknown one is refused, never guessed."
        )
    exp = int(m.group("exp")) if m.group("exp") is not None else 1
    if exp == 0 or abs(exp) > MAX_POWER:
        raise UnitTextError(f'"{text}": a power in a unit is a whole number from -{MAX_POWER} to {MAX_POWER}, not 0.')
    return spelling, exp


def parse_unit(text: str) -> Unit:
    """A unit from its text ("" is a plain number). Raises UnitTextError."""
    whole = text.strip()
    if whole == "":
        return PLAIN
    if len(whole) > 80:
        raise UnitTextError("a unit is at most 80 characters")
    if whole in NEAR_MISSES or whole in OFFSET_SCALES:
        raise UnitTextError(
            f'"{whole}" is not a unit flo2-calc knows.{_hint(whole)} Units are spelled as reflow2 spells them '
            "(mm, g, V, mA ...); an unknown one is refused, never guessed."
        )
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
    return _combine(pairs)


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
    return {s for s, _ in unit if s in ANGLE_PSEUDO_DIMENSION}


def conversion(from_unit: Unit, to_unit: Unit, operation: str) -> Fraction:
    """The exact factor turning a value in `from_unit` into `to_unit`.

    Raises Refusal when they measure different things. For an operation that
    combines values, `to_unit` is the first operand's, so the message names
    the units in the order the operands came; for convert it says which unit
    could not be turned into which."""
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
        if (_angle_kinds(first) | _angle_kinds(second)) == {"deg", "rad"}:
            raise Refusal(
                f"{said}: deg and rad differ by the factor pi/180, which no exact number holds, so they are never "
                "mixed silently. Convert one first: a convert node turns deg into rad, or rad into deg, as a "
                "correctly rounded value labelled rounded.",
                kind="unit_mismatch",
                units=named,
            )
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
    plain percentage, so 200 g * 5 % is 10 g and 10 % * 2 is 20 %."""
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
    return unit, scale * fold


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
    return fold_percent(tuple((s, e * n) for s, e in unit if e * n != 0))


# ---------------------------------------------------------------- angles, for trigonometry and deg-rad conversion

ANGLE_DIMENSIONS = {dim: spelling for spelling, dim in ANGLE_PSEUDO_DIMENSION.items()}


def angle_kind(unit: Unit) -> tuple[str, Fraction] | None:
    """("deg" or "rad", the exact factor turning a magnitude in `unit` into
    that) when the unit measures one plain angle; None otherwise."""
    dims = dimension(unit)
    if len(dims) == 1 and dims[0][1] == 1 and dims[0][0] in ANGLE_DIMENSIONS:
        return ANGLE_DIMENSIONS[dims[0][0]], factor(unit)
    return None


def pi_conversion(from_unit: Unit, to_unit: Unit) -> tuple[Fraction, int] | None:
    """For two units that measure the same thing except that one counts
    angles in deg and the other in rad (deg into rad, rad/s into deg/s ...):
    (f, k) such that a value v in from_unit is v * f * (pi/180)^k in to_unit,
    f exact. None when they differ in anything else."""

    def split(unit: Unit) -> tuple[int, int, dict[str, int]]:
        dims = dict(dimension(unit))
        deg = dims.pop(ANGLE_PSEUDO_DIMENSION["deg"], 0)
        rad = dims.pop(ANGLE_PSEUDO_DIMENSION["rad"], 0)
        return deg, rad, dims

    deg_f, rad_f, rest_f = split(from_unit)
    deg_t, rad_t, rest_t = split(to_unit)
    if rest_f != rest_t or deg_f + rad_f != deg_t + rad_t or deg_f == deg_t:
        return None
    return factor(from_unit) / factor(to_unit), deg_f - deg_t
