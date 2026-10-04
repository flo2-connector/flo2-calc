"""Exact numbers: read from text, carried as fractions, written back as text.

THE ARITHMETIC CONTRACT (dec:quality-reliability: every result is correct or
refused). Every number is an exact rational (Python's `fractions.Fraction`).
No binary float is ever made, so 0.1 + 0.2 is exactly 0.3. Addition,
subtraction, multiplication, division and integer powers are exact, and so is
every unit conversion flo2-calc offers.

HOW A VALUE IS WRITTEN BACK. When its decimal ends (the denominator has no
prime factor but 2 and 5) and has at most 40 significant digits, it is written
exactly, e.g. "0.3", "25.4", "1.602176634e-19". Otherwise it is written rounded
half-even to 30 significant digits AND given exactly as a fraction beside it
("0.333333333333333333333333333333", exact "1/3"). Comparisons and later
operations always use the exact value, never the rounded text.

HOW A NUMBER IS READ. From text: a decimal ("0.1", "-2.5e3") or a fraction of
integers ("1/3"). A JSON integer is accepted too. A JSON number with a fraction
part is REFUSED: it reached Python as a binary float, so its exact value is
already lost. Write it as text ("0.1").
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction

SIGNIFICANT_DIGITS = 30
EXACT_DIGITS_MAX = 40
MAX_EXPONENT = 1000
MAX_NUMBER_TEXT = 80
# A value whose numerator or denominator outgrows this many bits is refused
# rather than carried: no decision rests on a 6,000-digit number, and an
# unbounded one could exhaust the memory of the process it runs in.
MAX_BITS = 20_000

ARITHMETIC_NOTE = (
    "Exact rational arithmetic: no binary floating point. + - * / and integer powers are exact, and so is "
    "every unit conversion. A value whose decimal ends (at most 40 significant digits) is written exactly; "
    "any other is written rounded half-even to 30 significant digits, and its exact value is given beside it "
    "as a fraction. Comparisons use exact values."
)

_DECIMAL = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_FRACTION = r"[+-]?\d+/\d+"
NUMBER_THEN_REST = re.compile(rf"^\s*({_FRACTION}|{_DECIMAL})(.*)$", re.S)


def parse_number(text: str) -> Fraction:
    """An exact number from its text. Raises ValueError with a reason."""
    t = text.strip()
    if len(t) > MAX_NUMBER_TEXT:
        raise ValueError(f"a number is at most {MAX_NUMBER_TEXT} characters")
    if re.fullmatch(_FRACTION, t):
        num, den = t.split("/")
        if int(den) == 0:
            raise ValueError(f'"{t}" divides by zero')
        return Fraction(int(num), int(den))
    if re.fullmatch(_DECIMAL, t):
        d = Decimal(t)
        if abs(d.adjusted()) > MAX_EXPONENT:
            raise ValueError(f'"{t}" is beyond 1e{MAX_EXPONENT}, the largest exponent flo2-calc reads')
        return Fraction(d)
    raise ValueError(f'"{t}" is not a number; write a decimal like "0.1" or "-2.5e3", or a fraction like "1/3"')


def check_size(q: Fraction) -> None:
    """Raise OverflowError when a value is too large to carry exactly."""
    if q.numerator.bit_length() > MAX_BITS or q.denominator.bit_length() > MAX_BITS:
        raise OverflowError(
            f"the value has grown past {MAX_BITS} bits in its numerator or denominator, "
            "too large to carry exactly"
        )


def _plain(d: Decimal) -> str:
    """A finite Decimal as text: plain notation near 1, scientific far from it."""
    d = d.normalize(Context(prec=10_000))
    if d.is_zero():
        return "0"
    sign, digits, _exp = d.as_tuple()
    adjusted = d.adjusted()
    if -7 <= adjusted < 21:
        text = format(d, "f")
    else:
        mantissa = "".join(map(str, digits))
        rest = mantissa[1:]
        text = ("-" if sign else "") + mantissa[0] + (f".{rest}" if rest else "") + f"e{adjusted:+d}"
    return text


def _short_terminating(q: Fraction) -> Decimal | None:
    """q as an exact Decimal when its decimal expansion ends within
    EXACT_DIGITS_MAX significant digits; None otherwise."""
    den = q.denominator
    twos = fives = 0
    while den % 2 == 0:
        den //= 2
        twos += 1
    while den % 5 == 0:
        den //= 5
        fives += 1
    if den != 1:
        return None
    k = max(twos, fives)
    scaled = q.numerator * (10**k // q.denominator)
    significant = str(abs(scaled)).rstrip("0") or "0"
    if len(significant) > EXACT_DIGITS_MAX:
        return None
    # Built from its digits, so no context precision can round it.
    return Decimal(scaled).scaleb(-k, Context(prec=EXACT_DIGITS_MAX + len(str(abs(scaled)))))


def format_number(q: Fraction) -> tuple[str, str | None]:
    """(text, exact) for a value: `exact` is None when `text` is already exact,
    else the exact fraction "p/q" the rounded text stands for."""
    exact = _short_terminating(q)
    if exact is not None:
        return _plain(exact), None
    with localcontext() as ctx:
        ctx.prec = SIGNIFICANT_DIGITS
        ctx.rounding = ROUND_HALF_EVEN
        rounded = Decimal(q.numerator) / Decimal(q.denominator)
    return _plain(rounded), f"{q.numerator}/{q.denominator}"
