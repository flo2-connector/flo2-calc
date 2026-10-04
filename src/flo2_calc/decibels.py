"""Decibels: gains in dB, and power levels in dBm and dBW (dec:round-2-fixes).

A GAIN (or a loss) is a value in dB: the logarithm of a ratio. dB is its own
dimension (units.py), so it adds to dB, compares with dB, scales by a plain
number, and dB/m times m is dB, but dB with a plain ratio is refused. Whether
"10 dB" is a power ratio of 10 or an amplitude ratio of about 3.16 is not in
the number, so turning dB into a ratio, or a ratio into dB, is done only by
db_to_ratio and ratio_to_db, and each must be told which: "kind": "power"
(10 log10) or "amplitude" (20 log10). flo2-calc never picks one.

A LEVEL is a value whose whole unit is dBm or dBW: a power, written as dB
above 1 mW or 1 W. Like a temperature on a scale with an offset
(temperature.py), a level is not a quantity that adds or multiplies, so:

  convert     a level to dBm or dBW (exact: x dBW is x + 30 dBm), or to a
              power unit, W, mW ... (P = 10^(L/10) times 1 mW or 1 W: rounded
              unless L/10 is whole); and a power to a level
              (L = 10 log10(P / 1 mW): rounded unless P / 1 mW is a power of
              ten; P must be more than 0). dBm is a power level by its
              definition, so no kind is needed here.
  add         at most one level, and everything added to it a gain in dB: the
              sum is a level on the level's scale. Two levels are refused: the
              sum of two levels is not the level of their total power.
  sub         level - level is a gain, in dB (on the first one's scale);
              level - gain is a level; gain - level is refused.
  eq ne lt le gt ge, min, max
              levels with levels, on one scale; min and max answer in the
              first one's unit. A level is never compared with a gain.
  ceil, floor, round
              in the level's own unit, like any value.
  anything else (mul, div, pow, neg, abs, a function, a distribution ...)
              refused: convert the level to a power first, or work with gains.

This file holds the rules and their refusals; the evaluator does the
arithmetic (exactly, or on the rounded class where a power of ten is
irrational).
"""

from __future__ import annotations

from fractions import Fraction

from flo2_calc import units as U
from flo2_calc.errors import Refusal

KIND = "decibel_level"
COMPARISONS = ("eq", "ne", "lt", "le", "gt", "ge")
REFERENCE_W = {"dBm": Fraction(1, 1000), "dBW": Fraction(1)}  # the power each level is dB above, in W
POWER = U.dimension((("W", 1),))
KINDS = ("power", "amplitude")
DB_FACTOR = {"power": 10, "amplitude": 20}


def level_of(unit: U.Unit) -> str | None:
    """"dBm" or "dBW" when a value with this unit is a power level."""
    if len(unit) == 1 and unit[0][1] == 1 and unit[0][0] in U.LEVELS:
        return unit[0][0]
    return None


def involved(op: str, units: list[U.Unit], target: U.Unit | None) -> bool:
    """Whether an operation takes a power level, or converts to one."""
    return any(level_of(u) for u in units) or (op == "convert" and target is not None and level_of(target) is not None)


def kind_of(unit: U.Unit) -> str:
    if level_of(unit):
        return "level"
    if U.gain_in(unit):
        return "gain"
    if U.dimension(unit) == POWER:
        return "power"
    return "other"


def offset_db(scale: str, to: str) -> Fraction:
    """What is added to a level on `scale` to write it on `to`: 30 from dBW to dBm."""
    return Fraction(10) * _log10_exact(REFERENCE_W[scale] / REFERENCE_W[to])


def _log10_exact(q: Fraction) -> Fraction:
    # REFERENCE_W's ratios are powers of ten (1000, 1, 1/1000).
    k = 0
    while q >= 10:
        q /= 10
        k += 1
    while q < 1:
        q *= 10
        k -= 1
    assert q == 1
    return Fraction(k)


def _named(*units: U.Unit) -> tuple[str, ...]:
    return tuple(U.format_unit(u) for u in units)


def plan(op: str, units: list[U.Unit], names: tuple[str, ...], target: U.Unit | None) -> str:
    """What an operation on a level is, or a Refusal saying why it is not one.

    Returns one of: "shift" (convert between dBm and dBW), "to_power",
    "to_level" (convert), "add" (a level plus gains), "difference" (level -
    level), "level_minus_gain", "compare" (levels on one scale, also min and
    max)."""
    kinds = [kind_of(u) for u in units]
    if op == "convert":
        assert target is not None
        to = kind_of(target)
        if kinds[0] == "level" and to == "level":
            return "shift"
        if kinds[0] == "level" and to == "power":
            return "to_power"
        if kinds[0] == "power" and to == "level":
            return "to_level"
        if kinds[0] == "level" or to == "level":
            level, other = (units[0], target) if kinds[0] == "level" else (target, units[0])
            hint = ""
            if kind_of(other) == "gain":
                hint = " A level less another level is a gain in dB: subtract a reference level (sub) to get one."
            elif not U.dimension(other):
                hint = " A level is a power, not a ratio: divide its power by another power for a ratio."
            raise Refusal(
                f"convert cannot turn {U.show(units[0])} into {U.show(target)}: {U.format_unit(level)} is a power "
                f"level, which converts to another level (dBm, dBW) or to a power (W, mW ...), and "
                f"{U.show(other)} is neither.{hint}",
                kind=KIND,
                units=_named(units[0], target),
            )
    if op == "add":
        levels = [i for i, k in enumerate(kinds) if k == "level"]
        if len(levels) > 1:
            raise Refusal(
                f"add cannot take two power levels, {U.show(units[levels[0]])} and {U.show(units[levels[1]])}: the sum "
                "of two levels in dB is not the level of their total power. Convert each to a power (convert to mW), "
                "add the powers, and convert the sum back, or add a gain in dB to one level.",
                kind=KIND,
                units=_named(units[levels[0]], units[levels[1]]),
            )
        for i, k in enumerate(kinds):
            if k not in ("level", "gain"):
                raise _not_a_gain("add", units[levels[0]], units[i], names[i])
        return "add"
    if op == "sub":
        (ka, kb), (ua, ub) = kinds, units
        if ka == "level" and kb == "level":
            return "difference"
        if ka == "level" and kb == "gain":
            return "level_minus_gain"
        if ka == "level":
            raise _not_a_gain("sub", ua, ub, names[1])
        raise Refusal(
            f'sub cannot take a power level ("{names[1]}", {U.show(ub)}) from {U.show(ua)}: that means nothing. To lower '
            "a level, subtract a gain in dB from it.",
            kind=KIND,
            units=_named(ua, ub),
        )
    if op in COMPARISONS or op in ("min", "max"):
        ref = kinds.index("level")
        for i, k in enumerate(kinds):
            if k != "level":
                raise Refusal(
                    f'{op} cannot compare a power level ("{names[ref]}", {U.show(units[ref])}) with "{names[i]}", '
                    f"{U.show(units[i])}: only a level compares with a level. Convert the one you mean, or compare "
                    "gains with gains.",
                    kind=KIND,
                    units=_named(units[ref], units[i]),
                )
        return "compare"
    i = kinds.index("level")
    raise Refusal(
        f'{op} cannot take "{names[i]}", a power level in {U.format_unit(units[i])}: a level is a logarithm of a power '
        "against a reference, so it does not multiply, divide, raise to a power, change sign or go into a function. "
        "Convert it to a power first (convert to mW or W), or work with a gain in dB.",
        kind=KIND,
        units=_named(units[i]),
    )


def _not_a_gain(op: str, level: U.Unit, other: U.Unit, name: str) -> Refusal:
    extra = " " + U.DB_IS_NOT_A_RATIO[0].upper() + U.DB_IS_NOT_A_RATIO[1:] if not U.dimension(other) else ""
    return Refusal(
        f'{op} can change a power level ({U.show(level)}) only by a gain in dB, and "{name}" is {U.show(other)} '
        f"({U.describe_dimension(other)}).{extra}",
        kind=KIND,
        units=_named(level, other),
    )
