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
    "exact, and so is every unit conversion but deg-rad and dBm-mW, so every value not marked \"rounded\" is exact "
    "FOR THESE INPUTS and no more accurate than they are: a decimal typed for an irrational number (a truncated pi or "
    "e) is taken as exactly that decimal, not as the number it stands for (the pi and e operators are the constants "
    "themselves). A whole number is written in full. Any other value whose decimal ends (at most 40 significant "
    "digits) is written exactly; any other is written rounded half-even to 30 significant digits, and its exact "
    "value for these inputs is given beside it as a fraction. A computed value whose compound unit is exactly a "
    "simpler unit is shown in it (\"simplified_from\" names the unit it was computed in); the value does not "
    "change. Comparisons use exact values. A value marked \"rounded\" is NOT exact: it comes from pi, e, a root, "
    "exp, ln, log10, a non-whole power, trigonometry, a deg-rad conversion, a decibel conversion or a distribution, "
    "or from arithmetic on such a value. It is a decimal of the stated number of significant digits, every one "
    "written, given no \"exact\" fraction, and \"error_at_most\" bounds its distance from the true value. Where it says "
    "\"correctly_rounded\", it is the true value rounded half-even, decided from a rigorous enclosure (Arb ball "
    "arithmetic, python-flint). A comparison, ceil, floor or round of a rounded value is answered only when its "
    "error bound decides it, and refused otherwise."
)

ARRAYS_NOTE = (
    "An ARRAY of exact numbers stays exact through rational "
    "operations, reductions and the statistics that are rational; a value marked \"float64\" is NOT exact: an FFT, "
    "a rounded-class function over an array, an array of more than 4,096 elements, or anything mixed with such a "
    "value, computed in IEEE 754 double precision. Every element of a float64 value lies within its "
    "\"error_at_most\" of the true value, a rigorous bound whose basis \"how\" names (the FFT's: Higham 2002, "
    "Theorem 24.2, for a power-of-two length; Arb's rigorous DFT for any other). An array of more than 1,024 "
    "elements is written as its sha256 over every element's text, which re-running compares."
)

EXACT_FOR_THESE_INPUTS = (
    "Exact for these inputs: every value follows exactly from the inputs as written, and is no more accurate than "
    "they are. A decimal typed for pi, e or another irrational number is taken as exactly that decimal, so a value "
    "built from it is exact for that decimal, not for the number it stands for."
)

EXACT_BUT_ROUNDED = (
    "Exact for these inputs, EXCEPT the values labelled \"rounded\". Every other value follows exactly from the "
    "inputs as written, and is no more accurate than they are (a decimal typed for pi is that decimal). A rounded "
    "value is NOT exact: it is written to its \"digits\" significant digits and lies within its \"error_at_most\" of "
    "the true value; where it says \"correctly_rounded\", it is the true value rounded half-even. A result computed "
    "from a rounded value is labelled rounded too."
)

EXACT_BUT_FLOAT64 = (
    "Exact for these inputs, EXCEPT the values labelled \"float64\". Every other value follows exactly from the "
    "inputs as written, and is no more accurate than they are. A float64 value (an FFT, a function over an array, a "
    "large array, or anything computed from one) is NOT exact: it was computed in IEEE 754 double precision, every "
    "element lies within its \"error_at_most\" of the true value, and \"how\" says what that bound rests on. A "
    "result computed from a float64 value is labelled float64 too."
)

EXACT_BUT_ROUNDED_AND_FLOAT64 = (
    "Exact for these inputs, EXCEPT the values labelled \"rounded\" or \"float64\". Every other value follows "
    "exactly from the inputs as written, and is no more accurate than they are. A rounded value is written to its "
    "\"digits\" and lies within its \"error_at_most\" of the true value (where it says \"correctly_rounded\", it "
    "is the true value rounded half-even). A float64 value was computed in IEEE 754 double precision, and every "
    "element lies within its \"error_at_most\" of the true value, on the basis \"how\" gives."
)

_DECIMAL = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_FRACTION = r"[+-]?\d+/\d+(?![\d.])"  # "1/0.725" is an expression, never the fraction 1/0
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


# How an input is built, in the refusal of an expression: the SHAPE of a node,
# with no number and no operator of the input's own, so it can never be read as
# a guess at what a malformed expression meant (round 2, q092: "3 + * 4" was
# answered with an example adding 3 and 4).
NODE_SHAPE = (
    'Build it as a graph of nodes, one operation each: an input is {"id": "<name>", "value": "<number> <unit>", '
    '"source": "<where it came from>"}, and an operation is {"id": "<name>", "op": "<operator>", "args": '
    '["<id>", "<id>"]}.'
)

_TOKEN = re.compile(
    r"\s*(?:(?P<num>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|(?P<op>[-+*/^×÷=])|(?P<open>\()|(?P<close>\))"
    r"|(?P<word>[^\s\-+*/^×÷=()\d][^\s\-+*/^×÷=()]*))"
)


def malformed_at(text: str) -> str | None:
    """Where an expression is malformed, in words, or None when it is a
    well-formed one (a number, with a unit, is one operand; + and - may be a
    sign)."""
    want_operand = True
    last: tuple[str, int] | None = None  # the last operator, sign or bracket, and where
    last_kind: str | None = None
    opened: list[int] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None or m.end() == pos:
            if text[pos:].strip() == "":
                break
            return f'"{text[pos]}" at character {pos + 1} is not part of a number, a unit or an operator'
        start = m.start(m.lastgroup) + 1  # 1-based, for people
        kind, tok = m.lastgroup, m.group(m.lastgroup)
        pos = m.end()
        if kind in ("num", "word"):
            if not want_operand:
                if kind == "word" and last_kind == "num":  # "4 mm": a number's unit
                    last_kind = "word"
                    continue
                return f'two values stand side by side with no operator between them, at character {start}'
            want_operand, last_kind = False, kind
        elif kind == "op":
            if want_operand:
                if tok in "+-":  # a sign
                    last = (tok, start)
                    continue
                if last is None:
                    return f'there is nothing before "{tok}" at character {start}'
                if last[0] == "(":
                    return f'there is nothing between "(" at character {last[1]} and "{tok}" at character {start}'
                return f'there is no operand between "{last[0]}" at character {last[1]} and "{tok}" at character {start}'
            want_operand, last = True, (tok, start)
        elif kind == "open":
            if not want_operand:
                return f'"(" at character {start} follows a value with no operator between them'
            opened.append(start)
            last = ("(", start)
        else:  # close
            if not opened:
                return f'")" at character {start} closes no "("'
            if want_operand:
                if last is not None and last[0] == "(":
                    return f'there is nothing between "(" at character {last[1]} and ")" at character {start}'
                return f'there is nothing after "{last[0]}" at character {last[1]}' if last else f'there is nothing before ")" at character {start}'
            opened.pop()
            last_kind = "close"
    if opened:
        return f'"(" at character {opened[-1]} is never closed'
    if want_operand:
        if last is None:
            return None
        return f'there is nothing after "{last[0]}" at character {last[1]}'
    return None


def expression_problem(raw: str) -> str:
    """The refusal of arithmetic typed inside a value. A malformed expression is
    called malformed, with where; it is never answered with an example built
    from its own numbers, which would be a guess at what it meant."""
    where = malformed_at(raw.strip())
    if where is not None:
        return (
            f'"{raw}" is a malformed expression: {where}. flo2-calc does not read arithmetic inside a value, and it '
            "does not guess what a malformed expression was meant to say: do not repair it yourself; send it back to "
            "whoever wrote it and ask what was meant. A value is one number with an optional unit. " + NODE_SHAPE
        )
    return (
        f'"{raw}" is an expression, and flo2-calc does not read arithmetic inside a value: a value is one number with '
        "an optional unit. " + NODE_SHAPE
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


def format_number(q: Fraction, whole_in_full: bool = False) -> tuple[str, str | None]:
    """(text, exact) for a value: `exact` is None when `text` is already exact,
    else the exact fraction "p/q" the rounded text stands for.

    With `whole_in_full` (records of schema version 4 and every reply, from
    flo2-calc 0.5.0), a whole number is written as an integer, every digit,
    never with "/1": 2^1000 is its 302 digits, not 30 of them and a fraction.
    Only a whole number of more than 40 digits whose significant digits number
    40 or fewer (1e+5000) keeps its short exact e-notation. The host's digits
    budget bounds how long one can be."""
    exact = _short_terminating(q)
    if whole_in_full and q.denominator == 1:
        if exact is not None and digits(abs(q.numerator)) > EXACT_DIGITS_MAX:
            return _plain(exact), None
        return str(q.numerator), None
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


def significant_text(q: Fraction, places: int) -> str:
    """A rounded value written with exactly `places` significant digits,
    trailing zeros kept: sqrt(2) at 40 digits is 1.414213562373095048801688724209698078570,
    not the 39 digits decimal_text writes. q is a decimal of at most `places`
    significant digits (a rounded value always is); if it ever had more, it is
    written in full rather than cut. 0 is written "0"."""
    if q == 0:
        return "0"
    num, den = q.numerator, q.denominator
    twos = (den & -den).bit_length() - 1
    fives = _power_of_five(den >> twos)
    if fives is None:
        raise ValueError(f"{q} has no ending decimal")
    k = max(twos, fives)
    m = abs(num) * (1 << (k - twos)) * 5 ** (k - fives)
    if k == 0:  # a whole number: its trailing zeros are not significant digits
        text = str(m)
        kept = text.rstrip("0")
        m, k = int(kept), -(len(text) - len(kept))
    have = digits(m)
    if have > places:
        return decimal_text(q)
    mantissa = str(m) + "0" * (places - have)  # exactly `places` digits
    adjusted = have - 1 - k  # the exponent of the first digit
    sign = "-" if num < 0 else ""
    if -7 <= adjusted < 21:
        if adjusted >= 0:
            whole, frac = mantissa[: adjusted + 1], mantissa[adjusted + 1:]
            whole = whole + "0" * (adjusted + 1 - len(whole))
            return sign + whole + (f".{frac}" if frac else "")
        return sign + "0." + "0" * (-adjusted - 1) + mantissa
    rest = mantissa[1:]
    return sign + mantissa[0] + (f".{rest}" if rest else "") + f"e{adjusted:+d}"


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
