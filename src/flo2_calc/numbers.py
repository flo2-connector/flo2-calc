"""Exact numbers: read from text, carried as fractions, written back as text.

THE ARITHMETIC CONTRACT (dec:quality-reliability: every result is correct or
refused). Every number is an exact rational (Python's `fractions.Fraction`).
No binary float is ever made, so 0.1 + 0.2 is exactly 0.3. Addition,
subtraction, multiplication, division and integer powers are exact, and so is
every unit conversion flo2-calc offers.

EXACT FOR THESE INPUTS. A value is exact for the inputs AS WRITTEN, and no
more accurate than they are. flo2-calc cannot know that "3.14159265" was typed
for pi: it takes it as exactly that decimal. So a value built from a truncated
pi or e is the exact value of the given inputs, not of the math they stand
for, and every reply and record says so (EXACT_FOR_THESE_INPUTS,
ARITHMETIC_NOTE). Round 1 of the question set found results built on a typed
pi labelled "exact" with nothing more said.

HOW A VALUE IS WRITTEN BACK. When its decimal ends (the denominator has no
prime factor but 2 and 5) and has at most 40 significant digits, it is written
exactly, e.g. "0.3", "25.4", "1.602176634e-19". Otherwise it is written rounded
half-even to 30 significant digits AND given exactly as a fraction beside it
("0.333333333333333333333333333333", exact "1/3"). Comparisons and later
operations always use the exact value, never the rounded text.

HOW A NUMBER IS READ. From text: a decimal ("0.1", "-2.5e3") or a fraction of
integers ("1/3"). A JSON integer is accepted too. A JSON number with a fraction
part is REFUSED: it reached Python as a binary float, so its exact value is
already lost. Write it as text ("0.1"). A value is ONE number: text that holds
arithmetic ("3 + 4", "2^10", "2 1/2") is refused as an expression, with how to
build it as nodes, rather than read as a number and a strange unit.
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
    "Exact rational arithmetic on the inputs as written: no binary floating point. + - * / and integer powers are "
    "exact, and so is every unit conversion, so every value is exact FOR THESE INPUTS and no more accurate than "
    "they are: a decimal typed for an irrational number (a truncated pi or e) is taken as exactly that decimal, "
    "not as the number it stands for. A value whose decimal ends (at most 40 significant digits) is written "
    "exactly; any other is written rounded half-even to 30 significant digits, and its exact value for these "
    "inputs is given beside it as a fraction. Comparisons use exact values."
)

EXACT_FOR_THESE_INPUTS = (
    "Exact for these inputs: every value follows exactly from the inputs as written, and is no more accurate than "
    "they are. A decimal typed for pi, e or another irrational number is taken as exactly that decimal, so a value "
    "built from it is exact for that decimal, not for the number it stands for."
)

_DECIMAL = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_FRACTION = r"[+-]?\d+/\d+"
NUMBER_THEN_REST = re.compile(rf"^\s*({_FRACTION}|{_DECIMAL})(.*)$", re.S)

# What a unit's text never holds: an operator at its start, a + = × or ÷, a
# minus that is not a negative power (m^-2), or a number that is not a power
# (mm^2) and not the 1 of "1/s".
_OPERATOR_FIRST = re.compile(r"^\s*[-+*/^×÷=]")
_NO_UNIT_HOLDS = re.compile(r"[+=×÷]|(?<!\^)-")
_LONE_NUMBER = re.compile(r"(?<![A-Za-z_µμ°%\d.^])(?<!\^-)\d+(?:\.\d*)?")
_ARITHMETIC = re.compile(r"[-+*/^()×÷=]")


def looks_like_expression(text: str, whole: bool = False) -> bool:
    """Whether `text` is arithmetic rather than a unit: the text after a
    value's number ("+ * 4", "*4", "^10", "/3", "1/2"), or, with `whole`, a
    value that does not start with a number ("(3+4)", "pi*2")."""
    t = text.strip()
    if not t:
        return False
    if whole:
        return bool(_ARITHMETIC.search(t)) and any(c.isdigit() for c in t)
    if _OPERATOR_FIRST.match(t) or _NO_UNIT_HOLDS.search(t):
        return True
    lone = [m for m in _LONE_NUMBER.finditer(t) if not (m.start() == 0 and m.group() == "1" and t.startswith("1/"))]
    return bool(lone)


def expression_problem(raw: str) -> str:
    return (
        f'"{raw}" looks like an expression, and flo2-calc does not read arithmetic inside a value: a value is one '
        'number with an optional unit ("1.4 mm", "1/3", "-2.5e3"). Build the expression as a graph of nodes, one '
        'operation each, e.g. {"id": "a", "value": "3"}, {"id": "b", "value": "4"}, '
        '{"id": "sum", "op": "add", "args": ["a", "b"]}.'
    )


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
