"""Exact integer operators: remainder, divisibility, gcd, primality, factorization into primes, an integer range.

req:integer-arithmetic-has-remainder-divisibility-and-primality (accepted 2026-10-17, after a primes
trial on flo2.io had to test n^2 + n + 41 as v/d == floor(v/d) over a typed 40 x 39 grid) and
dec:v0-9-0-integer-operator-choices in design 0bee0c00b35845f6.

Every argument is an EXACT WHOLE PLAIN NUMBER of any size within the host's digits budget. A
fraction, a rounded value, a value with a unit or a true/false one is refused, naming the argument
and why (evaluator._whole_number). A float64 array is refused too: these operators take exact
values only.

  mod [a, b]           a - b floor(a / b): the remainder with the sign of b (Knuth's floored
                       remainder), so 0 <= a mod b < b for b > 0. b = 0 is refused.
  divides [d, n]       true when n = d k for a whole k. 0 divides only 0.
  gcd [a, b, ...]      the greatest common divisor of their absolute values; gcd(0, 0) = 0.
  is_prime [n]         true when n is a prime (n >= 2 with no divisor but 1 and n); false for n < 2.
  factorize [n]        n >= 2 as its primes with their multiplicities: an exact grid of k rows
                       [p, e], the primes in increasing order (1681 is [[41, 2]]).
  integer_range [a, b] the whole numbers a, a + 1, ..., b, both ends included: an exact 1-D
                       array of b - a + 1 elements, so a count is never typed by hand.

mod, divides, gcd and is_prime work element by element on exact arrays (evaluator.PER_ELEMENT),
so is_prime over integer_range(0, 39) tests forty numbers in one node. factorize and
integer_range take single values.

PRIMALITY IS PROVEN, never probable (choice 4). A number of at most the host's
max_prime_digits digits is decided by FLINT's fmpz_is_prime (python-flint's is_prime): a proof
either way (a certificate of Pocklington, Morrison-Brillhart, Lehmer or Selfridge's kind, else
APR-CL; below 2^64, Miller-Rabin with bases shown to be deterministic there). A longer number is
first given the BPSW probable-prime tests: failing one PROVES it composite, so the answer is false,
exactly. One that passes them is refused (kind exceeds_limits, naming max_prime_digits): no
composite is known to pass BPSW, but that is not a proof, and flo2-calc never answers a probable
prime as prime. A proof is one FLINT call that nothing interrupts, so the limit is what bounds it.

FACTORING IS EXACT OR REFUSED (choice 5). Every prime below 65,536 (TRIAL_BOUND) is divided out
first, exactly. What is left is 1, a prime (proven as above), a perfect power r^k (r is factored
in its place, and its exponents multiplied by k), or a composite whose factors are all at least
65,536: that composite part is factored by FLINT's fmpz_factor only when it has at most the
host's max_factor_digits digits, and refused past it (kind exceeds_limits, naming
max_factor_digits), never answered with a partial factorization. Every factor FLINT gives is
proven prime, and the product of the result is checked to be n, before it is answered.

AN INTEGER RANGE IS EXACT OR NOT MADE (choice 6). Its elements are the integers themselves, and the
integer operators take exact values only, so a range of more elements than the host's
max_exact_elements is refused (kind exceeds_limits, naming that limit) rather than carried in
float64 as a larger array otherwise is. An empty range (b < a) is refused.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

from flo2_calc import arrays as A
from flo2_calc import evaluator as E
from flo2_calc import limits as L
from flo2_calc import realmath as RM
from flo2_calc.errors import Refusal

ELEMENT_WISE = ("mod", "divides", "gcd", "is_prime")  # each takes exact arrays element by element
SINGLE = ("factorize", "integer_range")  # each takes single values only
TRIAL_BOUND = 1 << 16  # every prime below this is divided out of n before anything else (factorize)
CHECK_EVERY = 512


def _primes_below(n: int) -> tuple[int, ...]:
    sieve = bytearray([1]) * n
    sieve[0:2] = b"\x00\x00"
    for p in range(2, math.isqrt(n - 1) + 1):
        if sieve[p]:
            sieve[p * p::p] = bytearray(len(range(p * p, n, p)))
    return tuple(i for i, flag in enumerate(sieve) if flag)


SMALL_PRIMES = _primes_below(TRIAL_BOUND)  # 6,542 primes, 2 to 65,521

ARG_NAMES = {
    "mod": ("a", "b"),
    "divides": ("d", "n"),
    "is_prime": ("n",),
    "factorize": ("n",),
    "integer_range": ("a", "b"),
}


def apply(node: Any, args: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    if op in SINGLE:
        for v, name in zip(args, names, strict=True):
            if isinstance(v, A.Array):
                raise Refusal(
                    f'{op} takes single whole numbers, and "{name}" is an array: apply it to one value (element picks '
                    "one out).",
                    kind="type_mismatch",
                )
    what = ARG_NAMES.get(op, ())
    ints = [
        E._whole_number(op, v, name, what[i] if i < len(what) else "every argument", least=None)
        for i, (v, name) in enumerate(zip(args, names, strict=True))
    ]
    if op == "mod":
        a, b = ints
        if b == 0:
            raise Refusal(f'mod: "{names[1]}" is zero, and a remainder on division by zero has no value.', kind="division_by_zero")
        return E.Quantity(Fraction(a % b))  # Python's % is the floored remainder: the sign of b
    if op == "divides":
        d, n = ints
        return n == 0 if d == 0 else n % d == 0
    if op == "gcd":
        return E.Quantity(Fraction(math.gcd(*ints)))
    if op == "is_prime":
        return is_prime(ints[0], guard, f'"{names[0]}"')
    if op == "factorize":
        return _factorize(ints[0], names[0], guard)
    return _integer_range(ints[0], ints[1], names, guard)


def is_prime(n: int, guard: L.Guard, what: str) -> bool:
    """Whether n is prime, proven either way; a probable prime past the host's
    max_prime_digits is stopped there, never answered."""
    if n < 2:
        return False
    if n < TRIAL_BOUND:
        return _small_prime(n)
    guard.check_time()
    x = RM.flint().fmpz(n)
    d = L.digits(n)
    if d <= guard.limits.max_prime_digits:
        return bool(x.is_prime())
    if not x.is_probable_prime():
        return False  # a failed probable-prime test is a proof that n is composite
    guard.check_prime_digits(d, what)
    raise AssertionError("check_prime_digits stops past the limit")  # pragma: no cover


def _small_prime(n: int) -> bool:
    for p in SMALL_PRIMES:
        if p * p > n:
            return True
        if n % p == 0:
            return n == p
    return True  # pragma: no cover (n < 65,536 always meets a p with p * p > n)


def _factorize(n: int, name: str, guard: L.Guard) -> A.Array:
    if n == 1:
        raise Refusal(
            f'factorize: "{name}" is 1, which has no prime factors (its factorization is the empty product), and '
            "flo2-calc has no empty array to hold one.",
            kind="out_of_domain",
        )
    if n < 1:
        raise Refusal(
            f'factorize takes n, a whole number of at least 2, and "{name}" is {n}. For a negative number, factorize '
            "its abs: the sign is the factor -1.",
            kind="out_of_domain",
        )
    factors: list[tuple[int, int]] = []
    m = n
    for i, p in enumerate(SMALL_PRIMES):
        if i % CHECK_EVERY == 0:
            guard.check_time()
        if p * p > m:
            break
        if m % p == 0:
            e = 0
            while m % p == 0:
                m //= p
                e += 1
            factors.append((p, e))
    else:
        if m > 1 and m >= TRIAL_BOUND * TRIAL_BOUND:
            factors += _large_part(m, f'the part of "{name}" left after its factors below {TRIAL_BOUND:,}', guard)
            m = 1
    if m > 1:
        factors.append((m, 1))  # no prime p with p * p <= m divides it: m is prime
    product = 1
    for p, e in factors:
        product *= p**e
    if product != n:  # pragma: no cover - a fault, said as one rather than answered
        raise AssertionError(f"factorize: the factors' product is not {n}")
    A.make_room(guard, (len(factors), 2), A.EXACT)
    return A.exact_array([Fraction(x) for pe in factors for x in pe], (len(factors), 2))


def _large_part(m: int, what: str, guard: L.Guard) -> list[tuple[int, int]]:
    """m, with no prime factor below TRIAL_BOUND, as proven primes with their multiplicities."""
    if is_prime(m, guard, what):
        return [(m, 1)]
    x = RM.flint().fmpz(m)
    if x.is_perfect_power():  # m = r^k: factor r, at a fraction of m's digits
        for k in SMALL_PRIMES:  # the least prime k that works; r >= 65,536, so r^k >= 2^(16 k)
            if 1 << (16 * k) > m:
                break
            r = int(x.root(k))
            if r**k == m:
                return [(p, e * k) for p, e in _large_part(r, what, guard)]
    guard.check_factor_digits(L.digits(m), what)
    guard.check_time()
    found: dict[int, int] = {}
    for p, e in x.factor():
        p = int(p)
        if not is_prime(p, guard, f"a factor of {what}"):  # pragma: no cover - FLINT's factors are prime
            raise AssertionError(f"factorize: FLINT gave a factor {p} that is not prime")
        found[p] = found.get(p, 0) + int(e)
    guard.check_time()
    return sorted(found.items())


def _integer_range(a: int, b: int, names: tuple[str, ...], guard: L.Guard) -> A.Array:
    if b < a:
        raise Refusal(
            f'integer_range takes [a, b] with a <= b, both ends included, and "{names[0]}" is {a} and "{names[1]}" is '
            f"{b}: the range would be empty.",
            kind="out_of_domain",
        )
    count = b - a + 1
    if count > A.MAX_ELEMENTS:
        raise Refusal(f"integer_range: at most {A.MAX_ELEMENTS:,} whole numbers; {count:,} were asked for.", kind="too_large")
    guard.check_exact_elements(count, "integer range")
    A.make_room(guard, (count,), A.EXACT)
    return A.exact_array([Fraction(k) for k in range(a, b + 1)], (count,))
