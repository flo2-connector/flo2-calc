"""The rounded class: correctly rounded values, and rigorous error bounds.

dec:round-1-fixes-one-to-six (groups 1, 2, 5 and 6) in design 0bee0c00b35845f6:
pi, e, deg-rad conversion, sqrt, exp, ln, log10, non-whole powers,
trigonometry and the normal, chi-square and Student-t distributions. Their
results are irrational in general, so no exact fraction holds them. Under
dec:quality-reliability (every result is correct or refused) such a result
is CORRECTLY ROUNDED, LABELLED as rounded with its precision, and never
called exact.

THE METHOD, AND WHY IT IS CORRECT.

1. A rigorous enclosure. Every function is evaluated with Arb (FLINT's ball
   arithmetic, through python-flint). Arb's contract is that every result is
   a ball [m - r, m + r] that CONTAINS the true value: each operation bounds
   its own rounding error and every error it inherits, so the enclosure holds
   at any working precision (Johansson, "Arb: efficient arbitrary-precision
   midpoint-radius interval arithmetic", IEEE Trans. Computers 66(8), 2017).
   The arguments go in as exact rationals; one that is not a binary float is
   itself enclosed in a ball, so the true argument is inside too.
2. Ziv's rounding test. The enclosure [lo, hi] is read back as decimals
   (lo and hi exact rationals, rounded outward), and each end is rounded
   half-even to the digits asked for, with integers only. Rounding is
   monotone, so when both ends round to the same decimal, every number in
   [lo, hi], the true value among them, rounds to it: that decimal IS the
   correctly rounded result. When they differ, the working precision is
   doubled and the test repeated (Ziv, "Fast evaluation of elementary
   mathematical functions with correctly rounded last bit", ACM TOMS 17(3),
   1991).
3. Termination, and exact results. The test cannot succeed when the true
   value is exactly a rounding tie (a decimal of digits + 1 places ending in
   5). Ties are rational, so every case where a function takes a rational
   value at a rational argument is found FIRST and answered exactly
   (`exact_*` below): sqrt and roots of perfect powers, exp(0), ln(1),
   log10(10^k), trigonometry at the degree angles where it is rational
   (Niven's theorem), the distributions at their centre. At every other
   rational argument these functions are irrational (Lindemann-Weierstrass
   for exp, ln, sin, cos, tan and their inverses in radians and for pi and
   e; Gelfond-Schneider for log10; Niven for trigonometry in degrees; an
   algebraic non-rational value for a root), so no tie exists and the loop
   ends. For the distributions irrationality is not proven in general, so
   the loop is bounded: past the host's digits budget it stops with a
   refusal (limits.py, exceeds_limits), never with a guess.
4. The inverse distributions. The Student-t quantile is found by narrowing a
   bracket [lo, hi] whose two signs are each DECIDED by an Arb enclosure of
   the t tail (strictly monotone), until both ends round to the same decimal:
   the same rounding test, on an inverse. The normal quantile uses Arb's own
   enclosure of erfcinv.

ROUNDED ARGUMENTS. A rounded value is a ball: its decimal and its bound. A
function of rounded arguments is written as the correctly rounded result at
their written decimals (deterministic), and its error bound is the widest
distance from that to Arb's enclosure of the function over the arguments'
whole balls, rounded UP to two significant digits. It is then labelled "not
correctly rounded" (its arguments were not exact), with the bound.

python-flint keeps its working precision in one global, so every use of it
holds one lock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from math import isqrt
from typing import Any, Callable

from flo2_calc import limits as L
from flo2_calc.errors import Refusal
from flo2_calc.numbers import decade, half_unit, round_significant, round_up_significant

DEFAULT_DIGITS = 30
MAX_DIGITS = 1000
_LOCK = threading.Lock()
HALF = Fraction(1, 2)


@cache
def flint() -> Any:
    import flint as F

    return F


def flint_version() -> str:
    return flint().__version__


@dataclass(frozen=True)
class Ball:
    """A real number known to lie within `rad` of `mid` (exact when rad is 0)."""

    mid: Fraction
    rad: Fraction = Fraction(0)

    @property
    def exact(self) -> bool:
        return self.rad == 0

    @property
    def lo(self) -> Fraction:
        return self.mid - self.rad

    @property
    def hi(self) -> Fraction:
        return self.mid + self.rad


@dataclass(frozen=True)
class Outcome:
    value: Fraction
    error: Fraction  # 0: exact
    correctly_rounded: bool  # with error > 0: the true value, correctly rounded; else from rounded arguments


@dataclass(frozen=True)
class Fn:
    """A real function: its Arb evaluation on balls, and the rational values it
    takes at rational arguments (None where its value is proven irrational).
    `arb_exact`, when given, evaluates at exact rational arguments directly
    (sine in degrees reduces the angle exactly first)."""

    name: str
    arb: Callable[..., Any]
    exact: Callable[..., Fraction | None]
    arb_exact: Callable[..., Any] | None = None


def _bits(places: int) -> int:
    return places * 3322 // 1000 + 24


def _arb(q: Fraction) -> Any:
    F = flint()
    return F.arb(F.fmpq(q.numerator, q.denominator))


def _ball(b: Ball) -> Any:
    F = flint()
    x = _arb(b.mid)
    if b.rad:
        x = x + F.arb(0, F.fmpq(b.rad.numerator, b.rad.denominator))
    return x


def _at(places: int, compute: Callable[[], Any]) -> tuple[int, int, int] | None:
    """Run `compute` at a working precision of `places` decimal digits and
    read its enclosure back as (mid, rad, exp): the true value lies in
    [(mid - rad) 10^exp, (mid + rad) 10^exp]. None when Arb could not bound it
    (an infinite or undefined ball)."""
    F = flint()
    with _LOCK:
        saved = F.ctx.prec
        F.ctx.prec = _bits(places)
        try:
            y = compute()
            if not y.is_finite():
                return None
            m, r, e = y.mid_rad_10exp(places + 5)
        finally:
            F.ctx.prec = saved
    return int(m), int(r), int(e)


def _enclosure(found: tuple[int, int, int], places: int, guard: L.Guard, what: str) -> tuple[Fraction, Fraction] | None:
    """[lo, hi] as exact fractions, sized before they are built. None when
    the enclosure still holds zero (not yet decided)."""
    m, r, e = found
    if abs(m) <= r:
        return None
    guard.check_rounded_size(e + L.digits(m) - 1, places, what)
    scale = Fraction(10) ** e
    return Fraction(m - r) * scale, Fraction(m + r) * scale


def _next(working: int, guard: L.Guard) -> int:
    cap = guard.limits.max_digits
    return min(2 * working, cap) if working < cap else 2 * working


def correctly_rounded(fn: Fn, args: list[Fraction], places: int, guard: L.Guard) -> Fraction:
    """fn at exact rational arguments, correctly rounded half-even to `places`
    significant digits (Ziv's test on Arb's enclosure). Call only where the
    value is not rational (fn.exact returned None)."""
    working = places + 10
    what = f"the correctly rounded {fn.name}"
    while True:
        guard.check_precision(working, what)
        if fn.arb_exact is not None:
            found = _at(working, lambda: fn.arb_exact(*args))
        else:
            found = _at(working, lambda: fn.arb(*[_arb(a) for a in args]))
        if found is not None:
            bounds = _enclosure(found, places, guard, fn.name)
            if bounds is not None:
                lo, hi = bounds
                a, b = round_significant(lo, places), round_significant(hi, places)
                if a == b:
                    return a
        working = _next(working, guard)


def enclose(fn: Fn, args: list[Ball], places: int, guard: L.Guard) -> tuple[Fraction, Fraction]:
    """A rigorous [lo, hi] for fn over the arguments' whole balls."""
    working = places + 20
    for _ in range(4):
        guard.check_precision(working, f"a bound on {fn.name}")
        found = _at(working, lambda: fn.arb(*[_ball(a) for a in args]))
        if found is not None:
            m, r, e = found
            guard.check_rounded_size(e + L.digits(max(abs(m), r, 1)) - 1, places, fn.name)
            scale = Fraction(10) ** e
            return Fraction(m - r) * scale, Fraction(m + r) * scale
        working = _next(working, guard)
    raise Refusal(
        f"{fn.name}: its arguments are rounded values whose error bounds are too wide for any bound on the result, "
        "so flo2-calc gives none. Ask the rounded values that feed it for more digits.",
        kind="undecidable",
    )


def evaluate(fn: Fn, args: list[Ball], places: int, guard: L.Guard) -> Outcome:
    """fn on its arguments: exact where its value is rational at exact
    arguments; correctly rounded at exact arguments otherwise; and from
    rounded arguments, the correctly rounded value at their written decimals
    with a rigorous bound on the distance to the true value."""
    mids = [a.mid for a in args]
    value = fn.exact(*mids)
    if all(a.exact for a in args):
        if value is not None:
            guard.check_number(value)
            return Outcome(value, Fraction(0), False)
        c = correctly_rounded(fn, mids, places, guard)
        return Outcome(c, half_unit(c, places), True)
    if value is not None:
        guard.check_number(value)
        c = round_significant(value, places)
    else:
        c = correctly_rounded(fn, mids, places, guard)
    lo, hi = enclose(fn, args, places, guard)
    error = round_up_significant(max(hi - c, c - lo, Fraction(0)), 2)
    return Outcome(c, error, False)


# ---------------------------------------------------------------- rational values at rational arguments


def iroot(n: int, k: int) -> int:
    """The integer k-th root of n >= 0, rounded down. Integers only."""
    if n < 2 or k == 1:
        return n
    if n.bit_length() <= k:  # n < 2^k: the root is 1
        return 1
    x = 1 << ((n.bit_length() + k - 1) // k)  # >= the root
    while True:
        y = ((k - 1) * x + n // x ** (k - 1)) // k
        if y >= x:
            return x
        x = y


def exact_root(q: Fraction, k: int) -> Fraction | None:
    """q^(1/k) when it is rational (q >= 0), else None."""
    a, b = q.numerator, q.denominator
    ra, rb = iroot(a, k), iroot(b, k)
    if ra**k == a and rb**k == b:
        return Fraction(ra, rb)
    return None


def exact_sqrt(x: Fraction) -> Fraction | None:
    ra, rb = isqrt(x.numerator), isqrt(x.denominator)
    return Fraction(ra, rb) if ra * ra == x.numerator and rb * rb == x.denominator else None


def exact_log10(x: Fraction) -> Fraction | None:
    for n, sign in ((x.numerator, 1), (x.denominator, -1)):
        other = x.denominator if sign == 1 else x.numerator
        if other != 1:
            continue
        k = L.digits(n) - 1
        if n == L.ten_to(k):
            return Fraction(sign * k)
    return None


def _niven(table: dict[Fraction, Fraction], angle: Fraction, period: int) -> Fraction | None:
    return table.get(angle % period)


_F = Fraction
SIN_DEG = {_F(0): _F(0), _F(30): HALF, _F(90): _F(1), _F(150): HALF, _F(180): _F(0), _F(210): -HALF, _F(270): _F(-1), _F(330): -HALF}
COS_DEG = {_F(0): _F(1), _F(60): HALF, _F(90): _F(0), _F(120): -HALF, _F(180): _F(-1), _F(240): -HALF, _F(270): _F(0), _F(300): HALF}
TAN_DEG = {_F(0): _F(0), _F(45): _F(1), _F(135): _F(-1)}
ASIN_DEG = {_F(0): _F(0), HALF: _F(30), _F(1): _F(90), -HALF: _F(-30), _F(-1): _F(-90)}
ACOS_DEG = {_F(1): _F(0), HALF: _F(60), _F(0): _F(90), -HALF: _F(120), _F(-1): _F(180)}
ATAN_DEG = {_F(0): _F(0), _F(1): _F(45), _F(-1): _F(-45)}


def exact_atan2_deg(y: Fraction, x: Fraction) -> Fraction | None:
    if y == 0:
        return _F(0) if x > 0 else _F(180)
    if x == 0:
        return _F(90) if y > 0 else _F(-90)
    if abs(y) == abs(x):
        return {(True, True): _F(45), (True, False): _F(135), (False, True): _F(-45), (False, False): _F(-135)}[(y > 0, x > 0)]
    return None


# ---------------------------------------------------------------- the functions


def _pi() -> Any:
    return flint().arb.pi()


def _deg(x: Any) -> Any:
    """An angle in radians, as degrees."""
    return x * 180 / _pi()


def _rad(x: Any) -> Any:
    """An angle in degrees, as radians."""
    return x * _pi() / 180


def _fmpq(q: Fraction) -> Any:
    return flint().fmpq(q.numerator, q.denominator)


def _sin_cos_deg(x: Fraction) -> tuple[Any, Any]:
    """sin and cos of an exact angle in degrees: the angle is reduced modulo
    360 exactly, then Arb's sin(pi q) of the rational q = angle / 180."""
    return flint().arb.sin_cos_pi_fmpq(_fmpq((x % 360) / 180))


def _sqrt2() -> Any:
    return flint().arb(2).sqrt()


SQRT = Fn("sqrt", lambda x: x.sqrt(), exact_sqrt)
EXP = Fn("exp", lambda x: x.exp(), lambda x: _F(1) if x == 0 else None)
LN = Fn("ln", lambda x: x.log(), lambda x: _F(0) if x == 1 else None)
LOG10 = Fn("log10", lambda x: x.log() / flint().arb.const_log10(), exact_log10)
PI = Fn("pi", _pi, lambda: None)
E = Fn("e", lambda: flint().arb.const_e(), lambda: None)

SIN = {
    "rad": Fn("sin", lambda x: x.sin(), lambda x: _F(0) if x == 0 else None),
    "deg": Fn("sin", lambda x: _rad(x).sin(), lambda x: _niven(SIN_DEG, x, 360), lambda x: _sin_cos_deg(x)[0]),
}
COS = {
    "rad": Fn("cos", lambda x: x.cos(), lambda x: _F(1) if x == 0 else None),
    "deg": Fn("cos", lambda x: _rad(x).cos(), lambda x: _niven(COS_DEG, x, 360), lambda x: _sin_cos_deg(x)[1]),
}
TAN = {
    "rad": Fn("tan", lambda x: x.tan(), lambda x: _F(0) if x == 0 else None),
    "deg": Fn("tan", lambda x: _rad(x).tan(), lambda x: _niven(TAN_DEG, x, 180), lambda x: (lambda s, c: s / c)(*_sin_cos_deg(x))),
}
ASIN = {
    "rad": Fn("asin", lambda x: x.asin(), lambda x: _F(0) if x == 0 else None),
    "deg": Fn("asin", lambda x: _deg(x.asin()), lambda x: ASIN_DEG.get(x)),
}
ACOS = {
    "rad": Fn("acos", lambda x: x.acos(), lambda x: _F(0) if x == 1 else None),
    "deg": Fn("acos", lambda x: _deg(x.acos()), lambda x: ACOS_DEG.get(x)),
}
ATAN = {
    "rad": Fn("atan", lambda x: x.atan(), lambda x: _F(0) if x == 0 else None),
    "deg": Fn("atan", lambda x: _deg(x.atan()), lambda x: ATAN_DEG.get(x)),
}
ATAN2 = {
    "rad": Fn("atan2", lambda y, x: flint().arb.atan2(y, x), lambda y, x: _F(0) if y == 0 and x > 0 else None),
    "deg": Fn("atan2", lambda y, x: _deg(flint().arb.atan2(y, x)), exact_atan2_deg),
}


def scaled(fn: Fn, k: Fraction) -> Fn:
    """fn's value times the exact k: an angle in degrees or radians written in
    another unit of the same kind. Arb multiplies the enclosure by k, so the
    rounding test still decides the value in that unit."""
    if k == 1:
        return fn

    def exact(*a: Fraction) -> Fraction | None:
        v = fn.exact(*a)
        return None if v is None else v * k

    arb_exact = (lambda *a: fn.arb_exact(*a) * _arb(k)) if fn.arb_exact is not None else None
    return Fn(fn.name, lambda *a: fn.arb(*a) * _arb(k), exact, arb_exact)


def integer_power(n: int, guard: L.Guard) -> Fn:
    """x^n for a whole n: for a rounded base (any exponent), or for an exact
    base asked for "digits" whose exact power passes the host's digits budget.
    It is rational at a rational x, and its exact value is used wherever it fits
    the budget. Where it does not, the value is decided by Ziv's test on Arb's
    enclosure of x^n (binary powering, so the exponent's size costs nothing):
    a power that large cannot be a rounding tie unless its digits stop short,
    and a true tie is never decided, only stopped at the budget."""

    def exact(x: Fraction) -> Fraction | None:
        if not guard.power_fits(x, n, power_digits):
            return None
        return x**n

    return Fn("pow", lambda x: x**n, exact)


def power_digits(b: int, n: int) -> int | None:
    """The exact number of decimal digits of b^n (b >= 2, n >= 1):
    floor(n log10 b) + 1, the floor decided by Arb (log10 b is irrational
    unless b is a power of ten, so the floor is always decided at some
    precision). None when a few precisions do not decide it."""
    k = L.digits(b) - 1
    if b == L.ten_to(k):
        return n * k + 1
    F = flint()
    with _LOCK:
        saved = F.ctx.prec
        try:
            for extra in (64, 128, 256, 512):
                F.ctx.prec = n.bit_length() + b.bit_length() + extra
                y = F.arb(b).log() / F.arb(10).log() * F.arb(n)
                f = y.floor().unique_fmpz()
                if f is not None:
                    return int(f) + 1
        finally:
            F.ctx.prec = saved
    return None


def power_decade(x: Fraction, n: int) -> int:
    """About floor(n log10 |x|), the decimal exponent of x^n (x != 0): to size a
    rounded power before it is made. An estimate: the enclosure is sized
    exactly again when it is read back (`_enclosure`)."""
    F = flint()
    with _LOCK:
        saved = F.ctx.prec
        try:
            F.ctx.prec = 64 + abs(n).bit_length()
            y = _arb(abs(x)).log() / F.arb(10).log() * F.arb(n)
            f = y.floor().unique_fmpz()
            if f is not None:
                return int(f)
            return int(y.mid().floor().unique_fmpz())
        finally:
            F.ctx.prec = saved


def angle_factor(k: int) -> Fn:
    """x times (pi/180)^k: degrees to radians for k = 1, radians to degrees
    for k = -1 (and k = 2, -2 ... for a unit with a squared angle)."""
    name = "convert (deg to rad)" if k > 0 else "convert (rad to deg)"

    def times(x: Any) -> Any:
        f = (_pi() / 180) ** abs(k)
        return x * f if k > 0 else x / f

    return Fn(name, times, lambda x: _F(0) if x == 0 else None)


def pow_fn(guard: L.Guard) -> Fn:
    """x^y for x > 0 (or x = 0 with y > 0), y not a whole number. Exact when
    x is a perfect power for y's denominator, the power sized first."""

    def exact(x: Fraction, y: Fraction) -> Fraction | None:
        if x == 0:
            return _F(0)
        if x == 1:
            return _F(1)
        root = exact_root(x, y.denominator)
        if root is None:
            return None
        guard.check_power(root, y.numerator)
        return root**y.numerator

    return Fn("pow", lambda x, y: x**y, exact)


# The distributions. Each takes (x, mean, sd) or (p, mean, sd), with mean 0
# and sd 1 for the standard normal. The tails go through erfc, so a far tail
# keeps its relative accuracy: Q(40) is about 3.7e-350, not 0.


def _z(x: Any, mean: Any, sd: Any) -> Any:
    return (x - mean) / sd


NORMAL_CDF = Fn(
    "normal_cdf",
    lambda x, m, s: (-_z(x, m, s) / _sqrt2()).erfc() / 2,
    lambda x, m, s: HALF if x == m else None,
)
NORMAL_SF = Fn(
    "normal_sf",
    lambda x, m, s: (_z(x, m, s) / _sqrt2()).erfc() / 2,
    lambda x, m, s: HALF if x == m else None,
)


def _normal_quantile_exact(p: Fraction, m: Fraction, s: Fraction) -> Any:
    """mean + sd z(p), from the exact p. Near p = 1/2 through erfinv(2p - 1),
    and in the tails through erfcinv of the nearer tail: either way the
    argument is computed exactly first (1 - p loses nothing as a fraction),
    so no digits are spent on a difference."""
    d = 2 * p - 1
    if abs(d) <= HALF:
        z = _arb(d).erfinv() * _sqrt2()
    else:
        z = _arb(2 * min(p, 1 - p)).erfcinv() * _sqrt2()
        z = z if p > HALF else -z
    return _arb(m) + _arb(s) * z


NORMAL_QUANTILE = Fn(
    "normal_quantile",
    lambda p, m, s: m - s * _sqrt2() * (2 * p).erfcinv(),
    lambda p, m, s: m if p == HALF else None,
    _normal_quantile_exact,
)
CHI2_SF = Fn(
    "chi2_sf",
    lambda x, k: (x / 2).gamma_upper(k / 2, regularized=1),
    lambda x, k: _F(1) if x == 0 else None,
)


# ---------------------------------------------------------------- the Student-t quantile


def _t_excess(t: Fraction, nu: Fraction, q: Fraction) -> tuple[Callable[[], Any], Fraction, int]:
    """2 (G(t) - q), where G(t) = P(T > t) for t >= 0 is half the regularized
    incomplete beta I_x(nu/2, 1/2), x = nu / (nu + t^2): strictly decreasing
    from 1/2 at t = 0. Returned as (an Arb computation, an exact target, a
    sign): the excess is sign * (target - computed).

    Near t = 0, x is near 1 and the series for I_x converges slowly, so there
    it uses I_x(a, b) = 1 - I_{1-x}(b, a) with 1 - x = t^2 / (nu + t^2), and
    compares I_{1-x}(1/2, nu/2) with the exact 1 - 2q: a p near 1/2 then
    needs no extra digits to tell G(t) from q."""
    F = flint()
    if t * t < nu:

        def small() -> Any:
            tt = _arb(t) * _arb(t)
            return (tt / (_arb(nu) + tt)).beta_lower(F.fmpq(1, 2), _arb(nu) / 2, regularized=1)

        return small, 1 - 2 * q, 1

    def large() -> Any:
        n = _arb(nu)
        return (n / (n + _arb(t) * _arb(t))).beta_lower(n / 2, F.fmpq(1, 2), regularized=1)

    return large, 2 * q, -1


def _t_quantile_cr(p: Fraction, nu: Fraction, places: int, guard: L.Guard) -> Fraction:
    """The Student-t quantile at p (p != 1/2), correctly rounded.

    It narrows a bracket lo < t* < hi on the upper tail, G(t*) = q with
    q = min(p, 1 - p), each step DECIDING the sign of G(x) - q from Arb's
    enclosure of G(x) (the working precision grows until the enclosure
    excludes q). G is strictly decreasing, so the bracket always holds t*. It
    ends when lo and hi round to the same decimal: t* then rounds to it too.
    Steps are secant steps (Illinois), kept inside the bracket, with a
    bisection when they stall; across decades it takes the geometric middle;
    near the end it tests the rounding boundaries themselves. A true tie (t*
    exactly on a boundary) is never decided: the working precision then grows
    until the host's budget stops it."""
    q = min(p, 1 - p)
    working = [places + 10]
    what = "the correctly rounded t_quantile"

    def decide(x: Fraction, patience: int | None = None) -> tuple[int, Fraction]:
        """(+1 if G(x) > q, -1 if G(x) < q), and G(x) - q roughly; (0, 0)
        when `patience` more doublings of the precision do not decide it (x
        is then t* itself, or within the precision of it). With no patience
        given it goes on to the host's budget, which stops it."""
        tries = 0
        compute, target, sign = _t_excess(x, nu, q)
        while True:
            guard.check_precision(working[0], what)
            found = _at(working[0], compute)
            if found is not None:
                m, r, e = found
                scale = Fraction(10) ** e
                low, high = sign * (target - Fraction(m + r) * scale), sign * (target - Fraction(m - r) * scale)
                if low > high:
                    low, high = high, low
                if low > 0:
                    return 1, sign * (target - Fraction(m) * scale)
                if high < 0:
                    return -1, sign * (target - Fraction(m) * scale)
            if patience is not None and tries >= patience:
                return 0, Fraction(0)
            tries += 1
            working[0] = _next(working[0], guard)

    # A bracket: G(0) = 1/2 > q; hi grows until G(hi) < q.
    lo, g_lo = Fraction(0), 1 - 2 * q
    hi = Fraction(1)
    while True:
        guard.check_rounded_size(decade(hi), places, "t_quantile")
        s, g = decide(hi, patience=2)
        if s < 0:
            g_hi = g
            break
        if s > 0:
            lo, g_lo = hi, g
        hi = hi * hi * 4  # undecided (hi is t* or next to it): t* is below the next hi all the same

    side = 0
    widths: list[Fraction] = []
    while True:
        if lo > 0:
            a = round_significant(lo, places)
            if a == round_significant(hi, places):
                return a if p > HALF else -a
        width = hi - lo
        mid = (lo + hi) / 2
        stalled = len(widths) >= 3 and width * 2 > widths[-3]
        widths.append(width)
        boundary = False
        if lo > 0 and width <= 16 * half_unit(mid, places):
            c = round_significant(mid, places)
            x = c + half_unit(c, places) if c <= mid else c - half_unit(c, places)
            boundary = lo < x < hi
        elif lo > 0 and decade(hi) > decade(lo) + 1:
            x = Fraction(10) ** ((decade(lo) + decade(hi)) // 2)
        elif not stalled and g_lo != g_hi:
            x = round_significant((lo * g_hi - hi * g_lo) / (g_hi - g_lo), working[0] + 5)
        else:
            x = mid
        if not lo < x < hi:
            x = mid
        # A rounding boundary is decided or refused (a tie is never guessed); any
        # other point that cannot be decided is t*, or next to it: the bracket
        # then closes on it from both sides, just off it.
        s, g = decide(x) if boundary else decide(x, patience=2)
        if s == 0:
            step = half_unit(x, working[0]) if x else width / 2**64
            below, above = max(x - step, (lo + x) / 2), min(x + step, (x + hi) / 2)
            s_below, g_below = decide(below)
            s_above, g_above = decide(above)
            if s_below > 0:
                lo, g_lo = below, g_below
            else:
                hi, g_hi = below, g_below
            if s_above < 0 and above < hi:
                hi, g_hi = above, g_above
            elif s_above > 0:
                lo, g_lo = above, g_above
            side = 0
            continue
        if s > 0:
            lo, g_lo = x, g
            if side > 0:
                g_hi /= 2  # Illinois: an end kept twice is halved, so the secant moves on
            side = 1
        else:
            hi, g_hi = x, g
            if side < 0:
                g_lo /= 2
            side = -1


def t_quantile(p: Ball, nu: Fraction, places: int, guard: L.Guard) -> Outcome:
    """The Student-t quantile with nu degrees of freedom (nu exact, > 0, and
    p inside (0, 1): the evaluator checks both). Exact at p = 1/2, correctly
    rounded at any other exact p. From a rounded p: the correctly rounded
    value at its decimal, and, the quantile being increasing in p, a bound
    from the quantiles at the ends of its ball."""
    if p.mid == HALF and p.exact:
        return Outcome(Fraction(0), Fraction(0), False)

    def at(x: Fraction, digits_: int) -> Fraction:
        return Fraction(0) if x == HALF else _t_quantile_cr(x, nu, digits_, guard)

    c = at(p.mid, places)
    if p.exact:
        return Outcome(c, half_unit(c, places), True)
    finer = places + 5
    top, bottom = at(p.hi, finer), at(p.lo, finer)
    hi = top + (half_unit(top, finer) if top else 0)
    lo = bottom - (half_unit(bottom, finer) if bottom else 0)
    return Outcome(c, round_up_significant(max(hi - c, c - lo), 2), False)


# ---------------------------------------------------------------- the skewed distributions (flo2-calc 0.8.0)
#
# req:skewed-distributions, dec:v0-8-0-bayes-randomization-shapley-choices (choice 8). The lognormal
# by its median and the sd of ln X; the gamma by its shape and scale; the beta by a and b. The cdf
# and tail go through erfc and Arb's regularized incomplete gamma and beta, so a far tail keeps its
# relative accuracy. Their values are irrational in general, but not proven so: as for the other
# distributions, the rounding loop is held to the host's digits budget. Every case where a value
# is known to be rational is answered exactly first: the lognormal's centre, the ends of each
# support, and the beta with whole parameters, which is a binomial tail (a polynomial in x).


def _log_ratio(x: Any, m: Any) -> Any:
    return (x / m).log()


LOGNORMAL_CDF = Fn(
    "lognormal_cdf",
    lambda x, m, s: (-_log_ratio(x, m) / (s * _sqrt2())).erfc() / 2,
    lambda x, m, s: HALF if x == m else None,
)
LOGNORMAL_SF = Fn(
    "lognormal_sf",
    lambda x, m, s: (_log_ratio(x, m) / (s * _sqrt2())).erfc() / 2,
    lambda x, m, s: HALF if x == m else None,
)


def _lognormal_quantile_exact(p: Fraction, m: Fraction, s: Fraction) -> Any:
    """median exp(sigma z(p)), z from the exact p as _normal_quantile_exact finds it."""
    return _arb(m) * (_arb(s) * _normal_quantile_exact(p, Fraction(0), Fraction(1))).exp()


LOGNORMAL_QUANTILE = Fn(
    "lognormal_quantile",
    lambda p, m, s: m * (-s * _sqrt2() * (2 * p).erfcinv()).exp(),
    lambda p, m, s: m if p == HALF else None,
    _lognormal_quantile_exact,
)

GAMMA_CDF = Fn(
    "gamma_cdf",
    lambda x, k, t: (x / t).gamma_lower(k, regularized=1),
    lambda x, k, t: _F(0) if x == 0 else None,
)
GAMMA_SF = Fn(
    "gamma_sf",
    lambda x, k, t: (x / t).gamma_upper(k, regularized=1),
    lambda x, k, t: _F(1) if x == 0 else None,
)


def _beta_tail_exact(x: Fraction, a: Fraction, b: Fraction, guard: L.Guard) -> Fraction | None:
    """I_x(a, b) where it is rational: 0 and 1 at the ends, 1/2 at the centre of
    a symmetric beta, and for whole a and b the binomial tail P(Bin(a + b - 1, x) >= a),
    a polynomial in x, when its exact value fits the digits budget (else None:
    it is then correctly rounded like any other value)."""
    if x <= 0:
        return _F(0)
    if x >= 1:
        return _F(1)
    if a == b and x == HALF:
        return HALF
    if a.denominator != 1 or b.denominator != 1:
        return None
    n = int(a + b - 1)
    u, v = x.numerator, x.denominator
    if L.power_digits_at_most(v, n) > guard.limits.max_digits:
        return None
    from flo2_calc import evaluator as E  # the binomial's own exact sum, in whole numbers

    return Fraction(E._binomial_sum(n, u, v - u, int(a), n, guard), v**n)


def beta_fn(guard: L.Guard, upper: bool = False) -> Fn:
    """beta_cdf (I_x(a, b)) or beta_sf (1 - I_x(a, b) = I_{1-x}(b, a), so the upper
    tail is computed from 1 - x, which an exact x keeps exactly)."""

    def exact(x: Fraction, a: Fraction, b: Fraction) -> Fraction | None:
        v = _beta_tail_exact(x, a, b, guard)
        return None if v is None else (1 - v if upper else v)

    if upper:
        return Fn("beta_sf", lambda x, a, b: (1 - x).beta_lower(b, a, regularized=1), exact)
    return Fn("beta_cdf", lambda x, a, b: x.beta_lower(a, b, regularized=1), exact)


# The gamma and beta quantiles have no closed form. Each is found in two steps:
#   1. APPROXIMATE: Newton's method on Arb's midpoints, kept inside a bracket (a bisection, geometric
#      across decades, where a step would leave it), its working precision raised as the digits it
#      has agree, until the step is far below the digits asked for;
#   2. VERIFY: the candidate c is the approximation rounded to the digits asked for; it IS the
#      correctly rounded quantile when the cdf is decided, by Arb's enclosures, to lie below p at
#      the lower edge of c's rounding cell and above p at its upper edge (the cdf is strictly
#      monotone, so the true quantile is then inside the cell). Otherwise c moves to its neighbour.
#      An edge that is the quantile itself (a tie) is never decided: the working precision grows
#      until the host's digits budget stops it, never a guess.
# For p > 1/2 the upper tail is solved for 1 - p, which an exact p keeps exactly.


@dataclass(frozen=True)
class _Tails:
    """A distribution for the quantile solver, at exact parameters: its cdf, its upper
    tail and its density, as Arb functions of x, and its support (hi None: unbounded)."""

    name: str
    cdf: Callable[[Any], Any]
    sf: Callable[[Any], Any]
    pdf: Callable[[Any], Any]
    hi: Fraction | None
    start: Fraction


def _gamma_tails(k: Fraction, t: Fraction) -> _Tails:
    def cdf(x: Any) -> Any:
        return (x / _arb(t)).gamma_lower(_arb(k), regularized=1)

    def sf(x: Any) -> Any:
        return (x / _arb(t)).gamma_upper(_arb(k), regularized=1)

    def pdf(x: Any) -> Any:
        y = x / _arb(t)
        return ((_arb(k) - 1) * y.log() - y - _arb(k).lgamma()).exp() / _arb(t)

    return _Tails("gamma_quantile", cdf, sf, pdf, None, k * t)


def _beta_tails(a: Fraction, b: Fraction) -> _Tails:
    def cdf(x: Any) -> Any:
        return x.beta_lower(_arb(a), _arb(b), regularized=1)

    def sf(x: Any) -> Any:
        return (1 - x).beta_lower(_arb(b), _arb(a), regularized=1)

    def pdf(x: Any) -> Any:
        lbeta = _arb(a).lgamma() + _arb(b).lgamma() - _arb(a + b).lgamma()
        return ((_arb(a) - 1) * x.log() + (_arb(b) - 1) * (1 - x).log() - lbeta).exp()

    return _Tails("beta_quantile", cdf, sf, pdf, _F(1), a / (a + b))


def _mid(y: Any) -> Fraction:
    man, exp = y.mid().man_exp()
    man, exp = int(man), int(exp)
    return Fraction(man) * Fraction(2) ** exp if exp >= 0 else Fraction(man, 1 << -exp)


def _with_prec(digits_: int, compute: Callable[[], Any]) -> Any:
    F = flint()
    with _LOCK:
        saved = F.ctx.prec
        F.ctx.prec = _bits(digits_)
        try:
            return compute()
        finally:
            F.ctx.prec = saved


def _cell(c: Fraction, places: int) -> tuple[Fraction, Fraction]:
    """The edges of the rounding cell of c > 0 at `places` digits: halfway to the
    decimals either side (below a power of ten the digits are ten times finer)."""
    u = 2 * half_unit(c, places)
    below = u / 10 if c == Fraction(10) ** decade(c) else u
    return c - below / 2, c + u / 2


def _approximate(d: _Tails, q: Fraction, upper: bool, places: int, guard: L.Guard) -> Fraction:
    """Step 1: the quantile to well past `places` digits, by Newton's method in a bracket.
    Only its accuracy, not its correctness, rests on this: step 2 decides the rounding."""
    tail = d.sf if upper else d.cdf
    sign = -1 if upper else 1  # the cdf rises with x, the sf falls: tail' = sign * pdf
    goal = places + 12

    def excess(x: Fraction, w: int) -> tuple[Fraction, Fraction, Fraction] | None:
        """(tail(x) - q, the radius of that, the density at x), at w digits; None where Arb gives no finite ball."""
        guard.check_precision(w, f"the {d.name}")

        def compute() -> Any:
            ax = _arb(x)
            return tail(ax), d.pdf(ax)

        y, f = _with_prec(w, compute)
        if not (y.is_finite() and f.is_finite()):
            return None
        return _mid(y) - q, _mid(y.rad()), _mid(f)

    lo, hi = Fraction(0), d.hi  # the quantile lies in (lo, hi); hi None: unbounded
    x = d.start
    w = 20
    for _ in range(4000):
        guard.check_rounded_size(decade(x), places, d.name)
        got = excess(x, w)
        if got is None:
            if w >= guard.limits.max_digits:
                break
            w = _next(w, guard)
            continue
        e, rad, f = got
        if abs(e) <= rad:  # the quantile, to this precision
            if w >= goal:
                return x
            w = min(2 * w, goal)
            continue
        if sign * e > 0:
            hi = x  # past the quantile
        else:
            lo = x
        nxt = x - e / (sign * f) if f > 0 else None  # Newton's step
        if nxt is None or not (lo < nxt and (hi is None or nxt < hi)):
            if hi is None:
                nxt = x * 4
            elif lo > 0 and hi / lo > 4:
                nxt = round_significant(_mid(_with_prec(30, lambda: (_arb(lo) * _arb(hi)).sqrt())), 20)
            else:
                nxt = (lo + hi) / 2
        moved = abs(nxt - x)
        x = round_significant(nxt, w + 8)
        if moved == 0 or moved < x * Fraction(1, 10 ** (places + 8)):
            if w >= goal:
                return x
            w = min(2 * w, goal)
            continue
        # Newton doubles the digits that agree each step: work at twice them, and a margin.
        agreed = max(0, -decade(moved / x))
        w = max(w, min(2 * agreed + 10, goal))
    raise Refusal(f"{d.name}: the quantile could not be approximated, so flo2-calc gives none.", kind="undecidable")


def _decide(d: _Tails, x: Fraction, q: Fraction, upper: bool, places: int, guard: L.Guard) -> int:
    """The sign of tail(x) - q (tail the cdf, or the sf when `upper`), DECIDED by
    Arb's enclosure; the working precision grows until it is, held to the
    host's digits budget. Outside the support it is known."""
    if x <= 0 or (d.hi is not None and x >= d.hi):
        at_top = x > 0
        value = (0 if at_top else 1) if upper else (1 if at_top else 0)
        return 1 if value > q else -1
    tail = d.sf if upper else d.cdf
    working = places + 10
    while True:
        guard.check_precision(working, f"the correctly rounded {d.name}")
        found = _at(working, lambda: tail(_arb(x)))
        if found is not None:
            m, r, e = found
            guard.check_rounded_size(e + L.digits(max(abs(m), 1)) - 1, places, d.name)
            scale = Fraction(10) ** e
            if Fraction(m - r) * scale > q:
                return 1
            if Fraction(m + r) * scale < q:
                return -1
        working = _next(working, guard)


def _quantile_cr(d: _Tails, p: Fraction, places: int, guard: L.Guard) -> Fraction:
    """Step 2: the quantile at the exact p, correctly rounded and verified."""
    upper = p > HALF
    q = 1 - p if upper else p
    x = _approximate(d, q, upper, places, guard)
    c = round_significant(x, places)
    for _ in range(64):
        low, high = _cell(c, places)
        s_low = _decide(d, low, q, upper, places, guard)
        s_high = _decide(d, high, q, upper, places, guard)
        # the cdf rises through p inside the cell; the sf falls through 1 - p
        below = s_low < 0 if not upper else s_low > 0  # the quantile is above the low edge
        above = s_high > 0 if not upper else s_high < 0  # and below the high edge
        if below and above:
            return c
        u = 2 * half_unit(c, places)
        if not below:
            c = c - (u / 10 if c == Fraction(10) ** decade(c) else u)
        else:
            c = c + u
    raise Refusal(f"{d.name}: the correctly rounded quantile could not be settled, so flo2-calc gives none.", kind="undecidable")


def _exact_beta_quantile(p: Fraction, a: Fraction, b: Fraction) -> Fraction | None:
    """The beta quantile where it is rational: p itself for the uniform Beta(1, 1); p^(1/a)
    for Beta(a, 1) and 1 - (1 - p)^(1/b) for Beta(1, b) when the root is rational; and 1/2
    at the centre of a symmetric beta."""
    if a == b and p == HALF:
        return HALF
    if a == 1 and b == 1:
        return p
    if b == 1 and a.denominator == 1:
        return exact_root(p, int(a))
    if a == 1 and b.denominator == 1:
        r = exact_root(1 - p, int(b))
        return None if r is None else 1 - r
    return None


def skewed_quantile(kind: str, p: Ball, params: list[Ball], places: int, guard: L.Guard) -> Outcome:
    """The gamma ([shape, scale]) or beta ([a, b]) quantile at p (the evaluator has
    checked p inside (0, 1) and the parameters > 0, over their whole balls).
    Exact where rational, correctly rounded at exact arguments, and from rounded
    arguments the correctly rounded value at their decimals with a bound from the
    quantiles at the corners of their balls: each quantile rises with p, with the
    gamma's shape and scale and the beta's a, and falls with the beta's b."""

    def at(pp: Fraction, ps: list[Fraction], digits_: int) -> Fraction:
        if kind == "beta":
            v = _exact_beta_quantile(pp, *ps)
            if v is not None:
                return v
            return _quantile_cr(_beta_tails(*ps), pp, digits_, guard)
        return _quantile_cr(_gamma_tails(*ps), pp, digits_, guard)

    mids = [a.mid for a in params]
    exact_value = _exact_beta_quantile(p.mid, *mids) if kind == "beta" else None
    if p.exact and all(a.exact for a in params):
        if exact_value is not None:
            guard.check_number(exact_value)
            return Outcome(exact_value, Fraction(0), False)
        c = at(p.mid, mids, places)
        return Outcome(c, half_unit(c, places), True)
    c = round_significant(exact_value, places) if exact_value is not None else at(p.mid, mids, places)
    finer = places + 5
    if kind == "beta":
        a, b = params
        low_args, high_args = [a.lo, b.hi], [a.hi, b.lo]
    else:
        low_args, high_args = [x.lo for x in params], [x.hi for x in params]
    bottom, top = at(p.lo, low_args, finer), at(p.hi, high_args, finer)
    hi = top + (half_unit(top, finer) if top else 0)
    lo = bottom - (half_unit(bottom, finer) if bottom else 0)
    return Outcome(c, round_up_significant(max(hi - c, c - lo, Fraction(0)), 2), False)


# ---------------------------------------------------------------- hypothesis tests and power (flo2-calc 0.10.0)
#
# req:calc-computes-named-hypothesis-tests-as-kept-records and req:calc-computes-power-and-sample-size-up-front
# (hypothesis.py, power.py). A named test's p-value is a function of EXACT rational arguments (the statistic's
# square, its sign, the degrees of freedom), so it is correctly rounded by the same Ziv test as every other
# rounded value. A power is computed from a critical value that is itself a quantile; that quantile is found
# correctly rounded at the working precision first (outside the lock), and enters the power's Arb computation
# as a ball holding the true quantile, so the enclosure of the power stays rigorous and narrows as the working
# precision grows. The noncentral t and chi-square are Poisson-weighted series whose truncation is bounded
# rigorously: past the term where each ratio of terms is at most 1/2, the rest is at most twice the next term.


def _alt_tail(two: Any, s: int, alternative: str) -> Any:
    """A one-sided p-value from the two-sided one, P(|S| >= |s_obs|), and the statistic's sign s: the side the
    alternative looks at holds half of it, the other side the rest (a continuous statistic)."""
    if alternative == "two_sided":
        return two
    toward = (s > 0) == (alternative == "greater")
    return two / 2 if toward else 1 - two / 2


def _z_two_sided(z2: Fraction) -> Any:
    return (_arb(z2 / 2).sqrt()).erfc()


def z_p_value(alternative: str) -> Fn:
    """The z-test's p-value, args [z^2, sign of z]: P(|Z| >= |z|) = erfc(|z| / sqrt 2), or one tail of it. Exact
    (1, or 1/2) at z = 0."""

    def exact(z2: Fraction, s: Fraction) -> Fraction | None:
        if z2 == 0:
            return Fraction(1) if alternative == "two_sided" else HALF
        return None

    def on_exact(z2: Fraction, s: Fraction) -> Any:
        return _alt_tail(_z_two_sided(z2), int(s), alternative)

    return Fn(f"the z-test's p-value ({alternative})", lambda z2, s: on_exact(_mid(z2), _mid(s)), exact, on_exact)


def _t_two_sided(t2: Fraction, nu: Fraction) -> Any:
    """P(|T| >= |t|) with nu degrees of freedom: I_x(nu/2, 1/2) at x = nu / (nu + t^2), or, where t^2 < nu (x near
    1, where that series converges slowly), 1 - I_{1-x}(1/2, nu/2), 1 - x = t^2 / (nu + t^2), computed exactly first."""
    F = flint()
    if t2 < nu:
        return 1 - _arb(t2 / (nu + t2)).beta_lower(F.fmpq(1, 2), _arb(nu / 2), regularized=1)
    return _arb(nu / (nu + t2)).beta_lower(_arb(nu / 2), F.fmpq(1, 2), regularized=1)


def t_two_sided_exact(t2: Fraction, nu: Fraction) -> Fraction | None:
    """P(|T| >= |t|) where it is rational: 1 at t = 0; and for an even whole nu, where it is
    1 - sqrt(x) sum_{j < nu/2} C(2j, j) / 4^j (1 - x)^j with x = t^2 / (nu + t^2), exactly when sqrt(x) is rational
    (for an even nu it is irrational otherwise, so the rounding test ends)."""
    if t2 == 0:
        return Fraction(1)
    if nu.denominator != 1 or nu.numerator % 2:
        return None
    x = t2 / (nu + t2)
    root = exact_sqrt(x)
    if root is None:
        return None
    total, term = Fraction(0), Fraction(1)
    for j in range(nu.numerator // 2):
        total += term
        term = term * (1 - x) * (2 * j + 1) / (2 * j + 2)
    return 1 - root * total


def t_p_value(alternative: str) -> Fn:
    """A t-test's p-value, args [t^2, nu, sign of t]: from P(|T| >= |t|) by the alternative."""

    def exact(t2: Fraction, nu: Fraction, s: Fraction) -> Fraction | None:
        two = t_two_sided_exact(t2, nu)
        if two is None:
            return None
        if alternative == "two_sided":
            return two
        return HALF if t2 == 0 else (two / 2 if (s > 0) == (alternative == "greater") else 1 - two / 2)

    def on_exact(t2: Fraction, nu: Fraction, s: Fraction) -> Any:
        return _alt_tail(_t_two_sided(t2, nu), int(s), alternative)

    return Fn(f"the t-test's p-value ({alternative})", lambda t2, nu, s: on_exact(_mid(t2), _mid(nu), _mid(s)), exact, on_exact)


def correctly_rounded_by(compute: Callable[[int], Callable[[], Any]], places: int, guard: L.Guard, what: str) -> Fraction:
    """A real value correctly rounded to `places` significant digits, from compute(working): a computation run at
    `working` decimal digits whose Arb ball holds the true value (it may do work of its own first, outside the
    lock: a quantile it needs). Ziv's test, as correctly_rounded: the working precision doubles until both ends of
    the enclosure round alike, up to the host's digits budget."""
    working = places + 10
    while True:
        guard.check_precision(working, what)
        found = _at(working, compute(working))
        if found is not None:
            bounds = _enclosure(found, places, guard, what)
            if bounds is not None:
                lo, hi = bounds
                a = round_significant(lo, places)
                if a == round_significant(hi, places):
                    return a
        working = _next(working, guard)


def compare_by(compute: Callable[[int], Callable[[], Any]], target: Fraction, guard: L.Guard, what: str) -> int:
    """+1 when the true value is above `target`, -1 when below, decided from enclosures at a growing precision. A
    value exactly at the target is never decided: the precision grows until the host's budget stops it."""
    working = 30
    while True:
        guard.check_precision(working, what)
        found = _at(working, compute(working))
        if found is not None:
            m, r, e = found
            scale = Fraction(10) ** e
            if Fraction(m - r) * scale > target:
                return 1
            if Fraction(m + r) * scale < target:
                return -1
        working = _next(working, guard)


def fn_at(fn: Fn, args: list[Fraction]) -> Callable[[int], Callable[[], Any]]:
    """An Fn at exact arguments, as a computation for correctly_rounded_by and compare_by."""
    if fn.arb_exact is not None:
        return lambda working: lambda: fn.arb_exact(*args)  # type: ignore[misc]
    return lambda working: lambda: fn.arb(*[_arb(a) for a in args])


def _phi(x: Any) -> Any:
    """The standard normal cdf, erfc(-x / sqrt 2) / 2: accurate in either tail."""
    return (-x / _sqrt2()).erfc() / 2


def z_power(alternative: str) -> Fn:
    """The power of a z-test, args [lambda^2, sign of lambda, alpha], lambda = delta sqrt(n) / sigma:
    Phi(lambda - z_(1-alpha)) for "greater", Phi(-lambda - z_(1-alpha)) for "less", and
    Phi(lambda - z_(1-alpha/2)) + Phi(-lambda - z_(1-alpha/2)) two-sided; z_(1-q) = sqrt(2) erfcinv(2q). Exactly
    alpha when lambda is 0."""

    def exact(l2: Fraction, s: Fraction, a: Fraction) -> Fraction | None:
        return a if l2 == 0 else None

    def on_exact(l2: Fraction, s: Fraction, a: Fraction) -> Any:
        lam = int(s) * _arb(l2).sqrt()
        if alternative == "two_sided":
            c = _sqrt2() * _arb(a).erfcinv()
            return _phi(lam - c) + _phi(-lam - c)
        c = _sqrt2() * _arb(2 * a).erfcinv()
        return _phi(lam - c) if alternative == "greater" else _phi(-lam - c)

    return Fn(f"the z-test's power ({alternative})", lambda l2, s, a: on_exact(_mid(l2), _mid(s), _mid(a)), exact, on_exact)


def _small(working: int) -> Any:
    """A truncation target well below the working precision's last digit."""
    return flint().arb(10) ** (-(working + 10))


def nct_cdf(t: Any, nu: Fraction, lam: Any, working: int, guard: L.Guard) -> Any:
    """P(T' <= t) for the noncentral t with nu degrees of freedom and noncentrality lam, for t > 0 (a ball), by
    the series of Guenther (1978) and Lenth (1989, AS 243):

        Phi(-lam) + 1/2 sum_j [p_j I_x(j + 1/2, nu/2) + q_j I_x(j + 1, nu/2)],   x = t^2 / (t^2 + nu),
        p_j = e^(-mu) mu^j / j!,  q_j = lam e^(-mu) mu^j / (sqrt(2) Gamma(j + 3/2)),  mu = lam^2 / 2.

    I_x(a + 1, b) = I_x(a, b) - x^a (1 - x)^b Gamma(a + b) / (Gamma(a + 1) Gamma(b)) carries each incomplete beta
    to the next. The sum stops past the term where both ratios of terms, mu / (j + 1) and mu / (j + 3/2), are at
    most 1/2 and twice the next terms are below 10^-(working + 10); since every I is in [0, 1], the rest is at
    most twice the next terms, and that bound is added to the ball."""
    F = flint()
    arb = F.arb
    half = arb(F.fmpq(1, 2))
    eps = _small(working)
    tt = t * t
    v = _arb(nu)
    x = tt / (tt + v)
    rest = v / (tt + v)
    b = v / 2
    i_half = x.beta_lower(half, b, regularized=1)
    i_one = x.beta_lower(arb(1), b, regularized=1)
    lg_b = b.lgamma()
    t_half = ((half + b).lgamma() - (half + 1).lgamma() - lg_b).exp() * x.sqrt() * rest**b
    t_one = ((1 + b).lgamma() - lg_b).exp() * x * rest**b
    a_half, a_one = half, arb(1)
    mu = lam * lam / 2
    e = (-mu).exp()
    p = e
    q = lam * e * (arb(2) / arb.pi()).sqrt()
    total = arb(0)
    j = 0
    while True:
        total += p * i_half + q * i_one
        i_half -= t_half
        t_half *= x * (a_half + b) / (a_half + 1)
        a_half += 1
        i_one -= t_one
        t_one *= x * (a_one + b) / (a_one + 1)
        a_one += 1
        p *= mu / (j + 1)
        q *= mu / (j + 1 + half)
        j += 1
        if j % 64 == 0:
            guard.check_time()
        if 2 * mu < j + 1 and 2 * (p + abs(q)) < eps:
            break
    tail = 2 * (p + abs(q))
    return _phi(-lam) + total / 2 + (tail / 2) * arb(0, 1)


def ncx2_sf(c: Any, df: int, lam: Any, working: int, guard: L.Guard) -> Any:
    """P(X > c) for the noncentral chi-square with df degrees of freedom and noncentrality lam, the Poisson
    mixture sum_j e^(-lam/2) (lam/2)^j / j! Q(df/2 + j, c/2) (Q the regularized upper incomplete gamma, carried by
    Q(a + 1, y) = Q(a, y) + y^a e^(-y) / Gamma(a + 1)); past the term where lam/2 / (j + 1) <= 1/2 and twice the
    next weight is below 10^-(working + 10), the rest is at most twice the next weight (every Q is in [0, 1])."""
    F = flint()
    arb = F.arb
    eps = _small(working)
    y = c / 2
    a = arb(df) / 2
    big_q = y.gamma_upper(a, regularized=1)
    term = (a * y.log() - y - (a + 1).lgamma()).exp()
    h = lam / 2
    w = (-h).exp()
    total = arb(0)
    j = 0
    while True:
        total += w * big_q
        big_q += term
        term *= y / (a + 1 + j)
        w *= h / (j + 1)
        j += 1
        if j % 64 == 0:
            guard.check_time()
        if 2 * h < j + 1 and 2 * w < eps:
            break
    return total + (2 * w) * arb(0, 1)


def quantile_ball(value: Fraction, places: int) -> Any:
    """The ball holding the true value of a quantile correctly rounded to `places` digits."""
    F = flint()
    if value == 0:
        return F.arb(0)
    r = half_unit(value, places)
    return _arb(value) + F.arb(0, F.fmpq(r.numerator, r.denominator))


def t_critical(alpha: Fraction, nu: Fraction, two_sided: bool, places: int, guard: L.Guard) -> Fraction:
    """t_(1 - alpha) (or t_(1 - alpha/2) two-sided) with nu degrees of freedom, correctly rounded to `places`."""
    return _t_quantile_cr(1 - (alpha / 2 if two_sided else alpha), nu, places, guard)


def chi2_critical(alpha: Fraction, df: int, places: int, guard: L.Guard) -> Fraction:
    """The chi-square quantile at 1 - alpha with df degrees of freedom (a gamma of shape df/2, scale 2),
    correctly rounded to `places`."""
    return _quantile_cr(_gamma_tails(Fraction(df, 2), Fraction(2)), 1 - alpha, places, guard)
