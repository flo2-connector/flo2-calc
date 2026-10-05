"""Temperatures on a scale with an offset: degC and degF (dec:round-1-fixes-one-to-six, group 4).

A READING is a value whose whole unit is degC or degF ("25 degC"): a point on
a scale whose zero is not zero temperature. A CHANGE is a difference of
temperatures: delta_degC, delta_degF, delta_K, or a degree inside a compound
unit ("2.5 degC/W" is 2.5 K/W). K has no offset, so a value in K can be either;
each rule below says which it is, and where both are possible the operation is
refused rather than guessed. A K known to be a change is written delta_K
(flo2-calc 0.7.0, round 3's q036), so it is never read as a temperature.

  convert     a reading to degC, degF or K, and K to degC or degF, exactly
              (K = C + 273.15, F = C * 9/5 + 32). A reading is never turned
              into a change, nor a change into a reading: a change converted
              to K is delta_K (units.converted_unit), and delta_K to degC or
              degF is refused.
  add         at most one reading. Everything added to it is a change
              (delta_degC, delta_degF, or K), and the sum is a reading on the
              reading's scale, wherever it stands among the arguments. Two
              readings are refused: a sum of temperatures means nothing.
  sub         reading - reading: a change, in delta_ of the first one's scale
              (30 degC - 77 degF is 5 delta_degC).
              reading - delta_degC or delta_degF: a reading.
              reading - delta_K: a reading.
              reading - K: REFUSED, because "5 K" could be a change (giving a
              reading) or a temperature (giving a change).
              K - reading: K is a temperature here (a change minus a
              temperature means nothing), so the answer is a change, delta_K
              (a bare K before 0.7.0).
              a change - a reading: refused.
  eq ne lt le gt ge, min, max
              readings, and K (a temperature here), compared exactly on one
              scale; min and max answer in the first one's unit. A reading is
              never compared with a change.
  mul div pow neg abs
              refused on a reading: its zero is not zero temperature. Convert
              it to K first, or work with a change.

A product that comes out in a bare degC (2.5 degC/W * 4 W) is a change,
delta_degC (units.as_change). Everything not involving a reading is ordinary
unit arithmetic in units.py, where a degree is a change.
"""

from __future__ import annotations

from fractions import Fraction

from flo2_calc import units as U
from flo2_calc.errors import Refusal

Number = tuple[Fraction, U.Unit]
KIND = "offset_temperature"
COMPARISONS = ("eq", "ne", "lt", "le", "gt", "ge")


def involved(op: str, units: list[U.Unit], target: U.Unit | None) -> bool:
    """Whether an operation takes a temperature reading (or converts to one)."""
    return any(U.scale_of(u) for u in units) or (op == "convert" and target is not None and U.scale_of(target) is not None)


def _kind(unit: U.Unit) -> str:
    if U.scale_of(unit):
        return "reading"
    if unit == U.KELVIN:
        return "K"
    if U.dimension(unit) == U.dimension(U.KELVIN):
        return "change"
    return "other"


def kelvin_of(magnitude: Fraction, unit: U.Unit) -> Fraction:
    """A reading, or a value in K taken as a temperature, in K."""
    scale = U.scale_of(unit)
    if scale is None:
        assert unit == U.KELVIN
        return magnitude
    return magnitude * U.atom(scale).factor + U.zero_in_kelvin(scale)


def on_scale(kelvin: Fraction, unit: U.Unit) -> Fraction:
    """A temperature in K, written on `unit`'s scale (degC, degF, or K)."""
    scale = U.scale_of(unit)
    if scale is None:
        assert unit == U.KELVIN
        return kelvin
    return (kelvin - U.zero_in_kelvin(scale)) / U.atom(scale).factor


def _change_of(scale: str) -> U.Unit:
    return ((U.INTERVAL_OF[scale], 1),)


def _named(*units: U.Unit) -> tuple[str, ...]:
    return tuple(U.format_unit(u) for u in units)


def apply(op: str, args: list[Number], names: tuple[str, ...], target: U.Unit | None) -> Number | bool:
    """One operation that takes a temperature reading. Raises Refusal."""
    kinds = [_kind(u) for _, u in args]
    if op == "convert":
        return _convert(args[0], kinds[0], names[0], target)
    if op == "add":
        return _add(args, kinds, names)
    if op == "sub":
        return _sub(args, kinds, names)
    if op in COMPARISONS or op in ("min", "max"):
        return _compare(op, args, kinds, names)
    i = kinds.index("reading")
    raise Refusal(
        f'{op} cannot take "{names[i]}", a temperature in {U.format_unit(args[i][1])}: that scale\'s zero is not zero '
        "temperature, so a temperature on it does not multiply, divide, raise to a power or change sign. Convert it "
        "to K first, or work with a change of temperature (delta_degC, delta_degF).",
        kind=KIND,
        units=_named(args[i][1]),
    )


def _convert(x: Number, kind: str, name: str, target: U.Unit) -> Number:
    to_kind = _kind(target)
    if kind == "reading" and to_kind in ("reading", "K"):
        return on_scale(kelvin_of(*x), target), target
    if kind == "K" and to_kind == "reading":
        return on_scale(x[0], target), target
    if kind == "reading" and to_kind == "change":
        raise Refusal(
            f'convert cannot turn {U.show(x[1])} into {U.show(target)}: "{name}" is a temperature (a reading on a '
            f"scale), and {U.show(target)} is a change of temperature. A change is the difference of two "
            "temperatures (sub).",
            kind=KIND,
            units=_named(x[1], target),
        )
    if kind == "change" and to_kind == "reading":
        raise Refusal(
            f'convert cannot turn {U.show(x[1])} into {U.show(target)}: "{name}" is a change of temperature, not a '
            f"temperature, and a change converted as a temperature would be wrong by the scale's offset. Convert it "
            f"to {U.INTERVAL_OF[U.scale_of(target)]} for the same change on that scale, or add it to a temperature "
            "to get one.",
            kind=KIND,
            units=_named(x[1], target),
        )
    U.conversion(x[1], target, "convert")  # measures something else: refused, naming both
    raise AssertionError("a temperature conversion fell through")  # pragma: no cover


def _two_readings(op: str, u1: U.Unit, u2: U.Unit, why: str) -> Refusal:
    return Refusal(f"{op} cannot take two temperatures, {U.show(u1)} and {U.show(u2)}: {why}", kind=KIND, units=_named(u1, u2))


def _add(args: list[Number], kinds: list[str], names: tuple[str, ...]) -> Number:
    at = [i for i, k in enumerate(kinds) if k == "reading"]
    if len(at) > 1:
        raise _two_readings(
            "add",
            args[at[0]][1],
            args[at[1]][1],
            "a sum of temperatures on a scale with an offset means nothing. To find the change between two "
            "temperatures, use sub; to shift a temperature, add a change (delta_degC, delta_degF or K).",
        )
    magnitude, unit = args[at[0]]
    total = magnitude
    for i, (m, u) in enumerate(args):
        if i != at[0]:
            # K and delta_ are changes here; anything that is not a temperature is refused, naming both.
            total += m * U.conversion(u, unit, "add")
    return total, unit


def _sub(args: list[Number], kinds: list[str], names: tuple[str, ...]) -> Number:
    (ma, ua), (mb, ub) = args
    ka, kb = kinds
    if ka == "reading" and kb == "reading":
        scale = U.scale_of(ua)
        assert scale is not None
        return ma - on_scale(kelvin_of(mb, ub), ua), _change_of(scale)
    if ka == "reading":
        if kb == "K":
            raise Refusal(
                f'sub cannot tell whether "{names[1]}", in K, is a temperature or a change of temperature, and the '
                f"answers differ. Write a change as delta_K, delta_degC or delta_degF, or convert \"{names[0]}\" to K "
                "first.",
                kind=KIND,
                units=_named(ua, ub),
            )
        return ma - mb * U.conversion(ub, ua, "sub"), ua  # a change; anything else is refused, naming both
    if ka == "K":
        return ma - kelvin_of(mb, ub), (U.KELVIN_CHANGE if U.delta_k() else U.KELVIN)
    if ka == "change":
        raise Refusal(
            f'sub cannot take a temperature ("{names[1]}") from a change of temperature ("{names[0]}"): that means '
            "nothing. To shift a temperature, subtract the change from it.",
            kind=KIND,
            units=_named(ua, ub),
        )
    U.conversion(ub, ua, "sub")  # the first measures something else: refused, naming both
    raise AssertionError("a temperature subtraction fell through")  # pragma: no cover


def _compare(op: str, args: list[Number], kinds: list[str], names: tuple[str, ...]) -> Number | bool:
    ref = kinds.index("reading")
    for i, k in enumerate(kinds):
        if k == "change":
            raise Refusal(
                f'{op} cannot compare a temperature ("{names[ref]}", {U.show(args[ref][1])}) with a change of '
                f'temperature ("{names[i]}", {U.show(args[i][1])}).',
                kind=KIND,
                units=_named(args[ref][1], args[i][1]),
            )
        if k == "other":
            if i == 0:
                U.conversion(args[ref][1], args[0][1], op)
            U.conversion(args[i][1], args[0][1], op)  # measures something else: refused, naming both
    kelvins = [kelvin_of(m, u) for m, u in args]
    if op in COMPARISONS:
        a, b = kelvins
        return {"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]
    chosen = min(kelvins) if op == "min" else max(kelvins)
    return on_scale(chosen, args[0][1]), args[0][1]
