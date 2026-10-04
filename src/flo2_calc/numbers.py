"""Exact numbers: read from text, carried as fractions, written back as text.

THE ARITHMETIC CONTRACT (dec:quality-reliability: every result is correct or
refused). Every number is an exact rational (Python's `fractions.Fraction`).
No binary float is ever made, so 0.1 + 0.2 is exactly 0.3. Addition,
subtraction, multiplication, division and integer powers are exact, and so is
every unit conversion flo2-calc offers, but deg to rad.

A ROUNDED value (realmath.py: pi, sqrt, sin, a distribution ...) is carried
as the exact fraction of its decimal, with a bound on its distance from the
true value, and is written in full with that label instead of an "exact"
(the helpers at the end of this file).

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
from decimal import MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, Context, Decimal
from fractions import Fraction

from flo2_calc.limits import digits, ten_to

SIGNIFICANT_DIGITS = 30
EXACT_DIGITS_MAX = 40
MAX_EXPONENT = 1000
MAX_NUMBER_TEXT = 80
# How large a value may grow is the HOST's to set, not this file's: the digits
# budget in limits.py (--max-digits), checked by the guard on every value.

ARITHMETIC_NOTE = (
    "Exact rational arithmetic: no binary floating point. + - * / and integer powers are exact, and so is "
    "every unit conversion. A value whose decimal ends (at most 40 significant digits) is written exactly; "
    "any other is written rounded half-even to 30 significant digits, and its exact value is given beside it "
    "as a fraction. Comparisons use exact values. A value marked \"rounded\" is not exact: it comes from pi, e, "
    "a root, exp, ln, log10, a non-whole power, trigonometry, a deg-rad conversion or a distribution, or from "
    "arithmetic on such a value. It is a decimal of the stated number of significant digits, given no \"exact\" "
    "fraction, and \"error_at_most\" bounds its distance from the true value. Where it says "
    "\"correctly_rounded\", it is the true value rounded half-even, decided from a rigorous enclosure (Arb ball "
    "arithmetic, python-flint). A comparison, ceil, floor or round of a rounded value is answered only when its "
    "error bound decides it, and refused otherwise."
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


def _plain(d: Decimal) -> str:
    """A finite Decimal as text: plain notation near 1, scientific far from it."""
    d = d.normalize(Context(prec=10_000, Emax=MAX_EMAX, Emin=MIN_EMIN))
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


def _power_of_five(n: int) -> int | None:
    """j when n == 5 ** j, else None. Sized from n's bit length, never by
    dividing by 5 once per factor (a 20,000-digit denominator would take tens of
    thousands of divisions)."""
    if n == 1:
        return 0
    if n % 5:
        return None
    # 5^j has floor(j * log2(5)) + 1 bits; 2321929/1000000 is just over log2(5).
    j = ((n.bit_length() - 1) * 1_000_000) // 2_321_929
    for candidate in (j, j + 1, j + 2):
        if 5**candidate == n:
            return candidate
    return None


def _short_terminating(q: Fraction) -> Decimal | None:
    """q as an exact Decimal when its decimal expansion ends within
    EXACT_DIGITS_MAX significant digits; None otherwise. It never writes a large
    integer out as text: a 20,000-digit value is judged from its size."""
    num, den = q.numerator, q.denominator
    twos = (den & -den).bit_length() - 1  # the factors of 2 in den
    fives = _power_of_five(den >> twos)
    if fives is None:  # den has a prime factor other than 2 and 5: the decimal never ends
        return None
    exact = Context(prec=EXACT_DIGITS_MAX + 2, Emax=MAX_EMAX, Emin=MIN_EMIN)
    if den == 1:
        n = abs(num)
        d = digits(n)
        if d <= EXACT_DIGITS_MAX:
            return Decimal(num)
        drop = d - EXACT_DIGITS_MAX  # the trailing zeros it needs to be short
        if (n & -n).bit_length() - 1 < drop:  # fewer factors of 2 than that: fewer zeros
            return None
        kept, rest = divmod(n, ten_to(drop))
        if rest:
            return None
        return Decimal(kept if num > 0 else -kept).scaleb(drop, exact)
    # q = m / 10^k with m = num * 10^k / den. num shares no factor with den, so
    # m ends in no zero, and its digits are exactly q's significant digits.
    k = max(twos, fives)
    at_least_bits = abs(num).bit_length() + (k - twos) + ((k - fives) * 2_321_928) // 1_000_000 - 1
    if at_least_bits > 1 and ((at_least_bits - 1) * 30_102) // 100_000 + 1 > EXACT_DIGITS_MAX:
        return None
    m = num * (1 << (k - twos)) * 5 ** (k - fives)
    if digits(m) > EXACT_DIGITS_MAX:
        return None
    return Decimal(m).scaleb(-k, exact)


def _rounded(q: Fraction) -> Decimal:
    """q rounded half-even to SIGNIFICANT_DIGITS digits. Divides only as far as
    those digits need (a short quotient of two long numbers is quick), and keeps
    a sticky digit for whatever remains, so the rounding is exact."""
    num, den = abs(q.numerator), q.denominator
    # Scale so the quotient has SIGNIFICANT_DIGITS + 2 or + 3 digits.
    shift = SIGNIFICANT_DIGITS + 2 - (digits(num) - digits(den))
    if shift >= 0:
        quotient, rest = divmod(num * ten_to(shift), den)
    else:
        quotient, rest = divmod(num, den * ten_to(-shift))
    sticky = 1 if rest else 0
    raw = Decimal((0 if q >= 0 else 1, tuple(int(c) for c in str(quotient * 10 + sticky)), -(shift + 1)))
    ctx = Context(prec=SIGNIFICANT_DIGITS, rounding=ROUND_HALF_EVEN, Emax=MAX_EMAX, Emin=MIN_EMIN)
    return ctx.plus(raw)


def format_number(q: Fraction) -> tuple[str, str | None]:
    """(text, exact) for a value: `exact` is None when `text` is already exact,
    else the exact fraction "p/q" the rounded text stands for."""
    exact = _short_terminating(q)
    if exact is not None:
        return _plain(exact), None
    return _plain(_rounded(q)), f"{q.numerator}/{q.denominator}"


# ---------------------------------------------------------------- the rounded class (realmath.py)
#
# A ROUNDED value (sqrt, exp, sin, a distribution, pi ...) is a decimal of at
# most `digits` significant digits, carried as the exact fraction that decimal
# is, with a bound on its distance from the true value. These helpers round
# and write such decimals exactly, with integers only: no float is made.


def decade(q: Fraction) -> int:
    """E with 10^E <= |q| < 10^(E+1), for q != 0. Sized from the digits of
    numerator and denominator, then one comparison."""
    num, den = abs(q.numerator), q.denominator
    e = digits(num) - digits(den)
    # 10^(e-1) <= num/den < 10^(e+1): it is e or e - 1.
    if e >= 0:
        return e if num >= den * ten_to(e) else e - 1
    return e if num * ten_to(-e) >= den else e - 1


def _scaled(q: Fraction, e: int) -> Fraction:
    """q / 10^e, exactly."""
    return q / ten_to(e) if e >= 0 else q * ten_to(-e)


def _times_ten_to(whole: int, e: int) -> Fraction:
    return Fraction(whole * ten_to(e)) if e >= 0 else Fraction(whole, ten_to(-e))


def round_significant(q: Fraction, places: int) -> Fraction:
    """q rounded half-even to `places` significant digits, as the exact
    fraction of that decimal. 0 stays 0."""
    if q == 0:
        return q
    unit = decade(q) - places + 1  # the decimal exponent of the last digit kept
    s = _scaled(abs(q), unit)
    whole, rest = divmod(s.numerator, s.denominator)
    twice = 2 * rest
    if twice > s.denominator or (twice == s.denominator and whole % 2 == 1):
        whole += 1
    kept = _times_ten_to(whole, unit)
    return kept if q > 0 else -kept


def round_up_significant(q: Fraction, places: int = 2) -> Fraction:
    """The least decimal of `places` significant digits that is >= q (q >= 0):
    an error bound, rounded so that it stays a bound and stays short."""
    if q <= 0:
        return Fraction(0)
    unit = decade(q) - places + 1
    s = _scaled(q, unit)
    return _times_ten_to(-((-s.numerator) // s.denominator), unit)  # the ceiling


def half_unit(q: Fraction, places: int) -> Fraction:
    """Half a unit in the last of `places` significant digits of q (q != 0):
    how far a correctly rounded q can be from the true value. When q is a
    power of ten rounded up from just below it, the true value's own unit is
    ten times smaller, so this stays a bound."""
    unit = decade(q) - places + 1
    return Fraction(ten_to(unit), 2) if unit >= 0 else Fraction(1, 2 * ten_to(-unit))


def decimal_text(q: Fraction) -> str:
    """A value whose decimal ends, written exactly however many digits it has
    (a rounded value may be asked for up to 1000 significant digits)."""
    num, den = q.numerator, q.denominator
    twos = (den & -den).bit_length() - 1
    fives = _power_of_five(den >> twos)
    if fives is None:
        raise ValueError(f"{q} has no ending decimal")
    k = max(twos, fives)
    m = num * (1 << (k - twos)) * 5 ** (k - fives)
    return _plain(Decimal(m).scaleb(-k, Context(prec=digits(m) + 2, Emax=MAX_EMAX, Emin=MIN_EMIN)))
