"""An independent oracle for the rounded class: mpmath, at 80 digits or more.

flo2-calc decides its rounded values from Arb (python-flint). These tests check
them against a DIFFERENT implementation, mpmath, worked at far more digits than
the answer has, and round its value half-even with Python's decimal module (not
flo2-calc's own rounding). A hard case is built so that the true value lies
within about 1e-15 of a unit in the 30th digit from a rounding TIE: a value
computed to 32 or 33 digits and then rounded is a coin toss there, and only a
method that decides the rounding gets it right every time.

mpmath is a test dependency only (pyproject's `test` extra); the package never
imports it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal
from fractions import Fraction
from typing import Callable

import mpmath as mp

DPS = 120


def frac(x: mp.mpf) -> Fraction:
    """An mpf as the exact fraction it is (a binary float of DPS digits)."""
    man, exp = mp.mpf(x).man_exp
    return Fraction(man) * Fraction(2) ** exp if exp >= 0 else Fraction(man, 2 ** (-exp))


def mpq(q: Fraction) -> mp.mpf:
    return mp.mpf(q.numerator) / q.denominator


def rounded(y: mp.mpf, places: int = 30) -> Fraction:
    """y rounded half-even to `places` significant digits, by Python's decimal
    module from mpmath's digits (places + 40 of them)."""
    text = mp.nstr(y, places + 40, strip_zeros=False, min_fixed=1, max_fixed=0)
    d = Context(prec=places, rounding=ROUND_HALF_EVEN, Emax=10**6, Emin=-(10**6)).plus(Decimal(text))
    return Fraction(d)


def ulp(y: mp.mpf, places: int = 30) -> mp.mpf:
    return mp.mpf(10) ** (mp.floor(mp.log10(abs(y))) - places + 1)


def midpoint_near(y: mp.mpf, places: int = 30) -> mp.mpf:
    """The rounding tie (a decimal of places + 1 digits ending in 5) nearest y."""
    u = ulp(y, places)
    return (mp.floor(y / u) + mp.mpf(1) / 2) * u


def neighbours(tie: mp.mpf, places: int = 30) -> tuple[Fraction, Fraction]:
    """The two decimals of `places` digits a tie lies halfway between, exactly."""
    with mp.workdps(DPS):
        quarter = ulp(tie, places) / 4
        return rounded(tie - quarter, places), rounded(tie + quarter, places)


def truncations(x0: mp.mpf, keep: int = 45) -> tuple[Fraction, Fraction]:
    """The decimals of `keep` significant digits just below and just above x0."""
    e = int(mp.floor(mp.log10(abs(x0)))) - keep + 1
    scaled = x0 / mp.mpf(10) ** e
    below = int(mp.floor(scaled))
    ten = Fraction(10) ** e
    return Fraction(below) * ten, Fraction(below + 1) * ten


def hard_pair(f: Callable[[mp.mpf], mp.mpf], start: mp.mpf, places: int = 30) -> tuple[Fraction, Fraction, mp.mpf]:
    """Two exact arguments either side of the x0 where f(x0) is a rounding tie
    near f(start): f at the first and f at the second fall on opposite sides of
    the tie, each within about 1e-15 of a unit in the last place of it."""
    with mp.workdps(DPS):
        tie = midpoint_near(f(mp.mpf(start)), places)
        x0 = mp.findroot(lambda x: f(x) - tie, mp.mpf(start), tol=mp.mpf(10) ** (-DPS + 10))
        lo, hi = truncations(x0)
        return lo, hi, tie


def exact(f: Callable[..., mp.mpf], *args: Fraction, places: int = 30) -> Fraction:
    """f at exact arguments, correctly rounded, by the oracle."""
    with mp.workdps(DPS):
        return rounded(f(*[mpq(a) for a in args]), places)


def distance_to_tie_in_ulps(f: Callable[[mp.mpf], mp.mpf], x: Fraction, tie: mp.mpf, places: int = 30) -> mp.mpf:
    with mp.workdps(DPS):
        return abs(f(mpq(x)) - tie) / ulp(tie, places)


# ---------------------------------------------------------------- the functions, as mpmath has them


def sin_deg(x: mp.mpf) -> mp.mpf:
    return mp.sin(x * mp.pi / 180)


def normal_cdf(x: mp.mpf, mean: mp.mpf = 0, sd: mp.mpf = 1) -> mp.mpf:
    return mp.erfc(-(x - mean) / sd / mp.sqrt(2)) / 2


def normal_sf(x: mp.mpf, mean: mp.mpf = 0, sd: mp.mpf = 1) -> mp.mpf:
    return mp.erfc((x - mean) / sd / mp.sqrt(2)) / 2


def chi2_sf(x: mp.mpf, k: mp.mpf) -> mp.mpf:
    return mp.gammainc(mp.mpf(k) / 2, x / 2, mp.inf, regularized=True)


def t_cdf(t: mp.mpf, nu: mp.mpf) -> mp.mpf:
    """The Student-t cdf, each tail in the form that keeps its digits: near 0
    through I_{t^2/(nu+t^2)}(1/2, nu/2), far out through I_{nu/(nu+t^2)}(nu/2, 1/2)."""
    nu = mp.mpf(nu)
    if t * t < nu:
        half = mp.betainc(mp.mpf(1) / 2, nu / 2, 0, t * t / (nu + t * t), regularized=True) / 2
        return mp.mpf(1) / 2 + (half if t > 0 else -half)
    tail = mp.betainc(nu / 2, mp.mpf(1) / 2, 0, nu / (nu + t * t), regularized=True) / 2
    return 1 - tail if t > 0 else tail


def brackets_quantile(cdf: Callable[[mp.mpf], mp.mpf], value: Fraction, p: Fraction, places: int = 30) -> bool:
    """Whether `value` is the correctly rounded quantile at p of an increasing
    cdf: cdf just below its rounding cell < p < cdf just above it."""
    with mp.workdps(DPS):
        c = mpq(value)
        h = ulp(c, places) / 2
        below = c - h if value else -mp.mpf(10) ** (-DPS // 2)
        above = c + h if value else mp.mpf(10) ** (-DPS // 2)
        return cdf(below) < mpq(p) < cdf(above)
