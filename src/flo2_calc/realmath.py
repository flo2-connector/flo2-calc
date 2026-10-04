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


def integer_power(n: int) -> Fn:
    """x^n for a whole n, used for a rounded base: rational at a rational x,
    so its exact value at the written decimal is always found (and sized)."""
    return Fn("pow", lambda x: x**n, lambda x: x**n)


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
