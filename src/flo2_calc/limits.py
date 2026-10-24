"""Host-set limits: how long one call may run, and how large its numbers and its reply may grow.

req:a-calculation-past-the-hosts-limits-is-stopped-and-handed-on, options (b)
and (d) of dec:idea-estimate-compute-before-calculating. flo2-calc's arithmetic
is EXACT, and exact numbers can grow without bound: a high power, or a long
chain of divisions, gives numerators and denominators of thousands of digits.
In a confined container (flo2.io runs a helper with a memory cap and a call
deadline) a runaway calculation would be killed, which reads as a crash. So
the HOST sets limits at start-up, and flo2-calc stops itself cleanly, with its
reason, before anything else has to.

THE LIMITS (cli.py reads them, like --root, from a flag or the environment):

  deadline         --deadline SECONDS        FLO2_CALC_DEADLINE         per call
  max_digits       --max-digits N            FLO2_CALC_MAX_DIGITS       any exact numerator or denominator
  max_reply_bytes  --max-reply-bytes N       FLO2_CALC_MAX_REPLY_BYTES  a reply, its record included
  max_array_bytes  --max-array-bytes N       FLO2_CALC_MAX_ARRAY_BYTES  the arrays one call holds (arrays.py)
  max_exact_elements --max-exact-elements N  FLO2_CALC_MAX_EXACT_ELEMENTS  the most elements an exact array has
  max_arrangements --max-arrangements N      FLO2_CALC_MAX_ARRANGEMENTS   the arrangements one randomization test counts
  max_shapley_factors --max-shapley-factors N  FLO2_CALC_MAX_SHAPLEY_FACTORS  the factors of one Shapley table
  max_prime_digits --max-prime-digits N      FLO2_CALC_MAX_PRIME_DIGITS   the digits of a number proven prime
  max_factor_digits --max-factor-digits N    FLO2_CALC_MAX_FACTOR_DIGITS  the digits of the part factoring splits
  max_answer_chars --max-answer-chars N      FLO2_CALC_MAX_ANSWER_CHARS   the characters of a reply's text answer

max_answer_chars (flo2-calc 0.11.0, dec:a-reply-carries-its-outcome-whole-and-fits-a-host-set-answer-budget) is
the READER's budget, not a runaway guard: what one reply's text answer may hold, as the text is sent. It never
stops a calculation. A reply keeps its outcome whole and fills the rest of it (answer.py), naming what it left out
and where it is. Like the others it is the host's, but unlike them it is never written into a record: a
not-yet-computed record's limits_in_force is describe(), schema 10's, unchanged. 30,000 characters on a laptop
(reflow2's reply budget, the one chat clients are known to take), 24,000 in flo2.io's image, which leaves room
for what flo2's door wraps around a reply within its own 30,000.

max_arrangements and max_shapley_factors (flo2-calc 0.8.0,
dec:v0-8-0-bayes-randomization-shapley-choices, choice 5) are checked BEFORE
the work, from its exact size: a randomization test counts every arrangement
its scheme allows (C(N, k), or 2^(N/2) within pairs), and a Shapley table of k
factors holds 2^k outcomes. Past either, the call is stopped like any other
limit (exceeds_limits), never sampled and never cut short.

max_prime_digits and max_factor_digits (flo2-calc 0.9.0,
dec:v0-9-0-integer-operator-choices, choices 4, 5 and 7; integers.py) bound the two integer
operations whose cost grows fastest with the size of a number, each one FLINT call that nothing
interrupts: proving a number prime (is_prime, and each factor factorize finds), and splitting the
composite part a factorization has left after its factors below 65,536. Each is checked BEFORE the
call, from the number's digits. Past max_prime_digits a number that fails a probable-prime test is
still answered (composite, proven), and one that passes is stopped, never answered as probably
prime; past max_factor_digits the factorization is stopped, never answered in part.

max_exact_elements is not a stop (except for integer_range, whose elements are the integers the
integer operators take exactly: past it the range is stopped, naming it, rather than made float64): past it an array is carried in float64 and
labelled so (dec:idea-how-arrays-are-computed's "large grids";
dec:v0-6-0-array-choices made it the host's). A computed record that holds an
array keeps the value it was made with, and re-running uses that value, so the
record re-runs to the same values on any host.

max_array_bytes caps how many array elements a call may hold, in all: a
float64 element and its bound are 16 bytes, a complex one 24, a true/false 1,
and an exact one its object and its digits (about 128 bytes for a short
number). It is checked BEFORE an array is made (from its shape), so an array
too large for the host's memory is never allocated, and again after.

Their defaults suit a laptop (LAPTOP). FLO2_IO is the lower profile for
flo2.io's sandbox, which the image sets (Dockerfile). README.md, "Limits",
says why each value is what it is.

THE GUARD (option b) checks them WHILE the evaluator runs, one Guard per call:
the deadline before every node and after every step of an operation with many
arguments; the digits budget on every input, every partial result and every
value. A power is checked BEFORE it is computed, from the sizes of its operands
alone, because a huge power stalls inside a single Python operation (a
20,000-digit number to the power 1000 takes about 44 s on one CPU, and nothing
can interrupt it). Every other operation's operands are already inside the
budget, so no single step can run long. The reply is measured as it is
written, so a reply too large to send is never built whole.

Passing a limit raises LimitExceeded, a NORMAL refusal of kind
"exceeds_limits" naming the limit, its value, the node reached and how large
the numbers had grown. Never a crash, never isError, never a sandbox kill.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from functools import cache
from typing import Any, Callable

from flo2_calc.errors import LimitExceeded

MIB = 1024 * 1024

# What each limit is called, where it is set, and the range a host may set it in.
SETTINGS: dict[str, tuple[str, str]] = {
    "deadline": ("--deadline", "FLO2_CALC_DEADLINE"),
    "max_digits": ("--max-digits", "FLO2_CALC_MAX_DIGITS"),
    "max_reply_bytes": ("--max-reply-bytes", "FLO2_CALC_MAX_REPLY_BYTES"),
    "max_array_bytes": ("--max-array-bytes", "FLO2_CALC_MAX_ARRAY_BYTES"),
    "max_exact_elements": ("--max-exact-elements", "FLO2_CALC_MAX_EXACT_ELEMENTS"),
    "max_arrangements": ("--max-arrangements", "FLO2_CALC_MAX_ARRANGEMENTS"),
    "max_shapley_factors": ("--max-shapley-factors", "FLO2_CALC_MAX_SHAPLEY_FACTORS"),
    "max_prime_digits": ("--max-prime-digits", "FLO2_CALC_MAX_PRIME_DIGITS"),
    "max_factor_digits": ("--max-factor-digits", "FLO2_CALC_MAX_FACTOR_DIGITS"),
    "max_answer_chars": ("--max-answer-chars", "FLO2_CALC_MAX_ANSWER_CHARS"),
}
# What each count-like limit counts, as a not-yet-computed record says what it needs.
COUNTS = {"max_digits": "digits", "max_arrangements": "arrangements", "max_shapley_factors": "factors",
          "max_exact_elements": "elements", "max_prime_digits": "digits", "max_factor_digits": "digits"}
DEADLINE_MS_RANGE = (1, 86_400_000)  # 0.001 s to a day
MAX_DIGITS_RANGE = (10, 100_000)  # past 100,000 digits, one step on two such numbers takes most of a second
MAX_REPLY_BYTES_RANGE = (1024, 256 * MIB)
MAX_ARRAY_BYTES_RANGE = (64 * 1024, 64 * 1024 * MIB)
MAX_EXACT_ELEMENTS_RANGE = (1, 1 << 21)  # up to the most elements any one array has (arrays.MAX_ELEMENTS)
MAX_ARRANGEMENTS_RANGE = (1, 10**12)  # 10^12 arrangements at about 0.6 us each is a week of one CPU
MAX_SHAPLEY_FACTORS_RANGE = (1, 21)  # 2^21 outcomes is the most elements any one array has (arrays.MAX_ELEMENTS)
MAX_PRIME_DIGITS_RANGE = (1, 2_000)  # proving a 700-digit prime took 4 minutes of one CPU (README, "Limits")
MAX_FACTOR_DIGITS_RANGE = (1, 100)  # a 60-digit part took 18 s; FLINT's quadratic sieve is practical to about 100
MAX_ANSWER_CHARS_RANGE = (1_000, 256 * MIB)  # below about 1,000 characters even a small outcome does not fit


@dataclass(frozen=True)
class Limits:
    """The limits one flo2-calc runs under, for every call."""

    deadline_ms: int = 45_000
    max_digits: int = 20_000
    max_reply_bytes: int = 8 * MIB
    max_array_bytes: int = 512 * MIB
    max_exact_elements: int = 65_536  # a 256 x 256 grid stays exact on a laptop
    max_arrangements: int = 10_000_000  # about 6 s of one randomization test at 0.6 us an arrangement
    max_shapley_factors: int = 16  # 2^16 outcomes: max_exact_elements, so the table stays exact
    max_prime_digits: int = 300  # a 300-digit prime is proven in about 10 s here, against the 45 s deadline
    max_factor_digits: int = 50  # the hardest 50-digit part (two 25-digit primes) splits in 2 to 3 s here
    max_answer_chars: int = 30_000  # a reply's text answer (0.11.0): reflow2's reply budget, which chat clients take

    def describe(self) -> dict[str, Any]:
        """As replies and not-yet-computed records write them: the deadline in
        seconds, spelled "s" as reflow2 spells it; the budgets as counts."""
        return {
            "deadline": seconds_text(self.deadline_ms),
            "max_digits": self.max_digits,
            "max_reply_bytes": self.max_reply_bytes,
            "max_array_bytes": self.max_array_bytes,
            "max_exact_elements": self.max_exact_elements,
            "max_arrangements": self.max_arrangements,
            "max_shapley_factors": self.max_shapley_factors,
            "max_prime_digits": self.max_prime_digits,
            "max_factor_digits": self.max_factor_digits,
        }

    def settings(self) -> dict[str, Any]:
        """Every limit the host sets, as describe() writes them, and the answer budget, which a record never
        holds (0.11.0)."""
        return {**self.describe(), "max_answer_chars": self.max_answer_chars}

    def value_of(self, name: str) -> Any:
        return self.settings()[name]

    def in_words(self) -> str:
        return (
            f"a deadline of {seconds_text(self.deadline_ms)} per call, at most {self.max_digits:,} digits in any exact "
            f"numerator or denominator, a reply of at most {self.max_reply_bytes:,} bytes, at most "
            f"{self.max_array_bytes:,} bytes of arrays in one call, exact arrays of up to "
            f"{self.max_exact_elements:,} elements (larger ones are float64, labelled), at most "
            f"{self.max_arrangements:,} arrangements in one randomization test, Shapley values of at most "
            f"{self.max_shapley_factors} factors, primality proven for numbers of up to {self.max_prime_digits:,} digits, "
            f"factoring that splits a part of up to {self.max_factor_digits:,} digits, "
            f"and an answer of at most {self.max_answer_chars:,} characters (its outcome whole, the rest named)"
        )


# A laptop: the defaults. A workstation raises them; flo2.io lowers them.
LAPTOP = Limits()
# flo2.io's sandbox: a 128m memory cap, one CPU, and a gateway that stops a helper call at 60 s.
FLO2_IO = Limits(deadline_ms=20_000, max_digits=2_000, max_reply_bytes=2 * MIB, max_array_bytes=16 * MIB, max_exact_elements=4_096,
                 max_arrangements=1_000_000, max_shapley_factors=12, max_prime_digits=200, max_factor_digits=40,
                 max_answer_chars=24_000)


def seconds_text(ms: int) -> str:
    whole, rest = divmod(ms, 1000)
    return f"{whole} s" if rest == 0 else f"{whole}.{rest:03d}".rstrip("0") + " s"


# ---------------------------------------------------------------- reading the settings


def parse_deadline(text: str) -> int:
    """A deadline in whole milliseconds, from seconds as text ("20", "0.5", "20 s").
    Raises ValueError with the reason."""
    t = text.strip()
    if t.endswith("s"):
        t = t[:-1].strip()
    try:
        seconds = Fraction(Decimal(t))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{text!r} is not a number of seconds; write, say, 20 or 0.5") from None
    ms = seconds * 1000
    lo, hi = DEADLINE_MS_RANGE
    if ms.denominator != 1 or not lo <= ms <= hi:
        raise ValueError(f"{text!r} is not a deadline flo2-calc takes: seconds from 0.001 to 86400, in whole milliseconds")
    return int(ms)


def parse_count(text: str, name: str, bounds: tuple[int, int]) -> int:
    t = text.strip().replace("_", "")
    lo, hi = bounds
    if not t.isdigit() or not lo <= int(t) <= hi:
        raise ValueError(f"{text!r} is not a {name} flo2-calc takes: a whole number from {lo:,} to {hi:,}")
    return int(t)


def from_settings(
    deadline: str | None,
    max_digits: str | None,
    max_reply_bytes: str | None,
    max_array_bytes: str | None = None,
    max_exact_elements: str | None = None,
    max_arrangements: str | None = None,
    max_shapley_factors: str | None = None,
    max_prime_digits: str | None = None,
    max_factor_digits: str | None = None,
    max_answer_chars: str | None = None,
) -> Limits:
    """The limits from start-up settings (None or "" keeps the laptop default).
    Raises ValueError naming the setting and why."""
    out = {}
    settings = (
        ("deadline", deadline), ("max_digits", max_digits), ("max_reply_bytes", max_reply_bytes),
        ("max_array_bytes", max_array_bytes), ("max_exact_elements", max_exact_elements),
        ("max_arrangements", max_arrangements), ("max_shapley_factors", max_shapley_factors),
        ("max_prime_digits", max_prime_digits), ("max_factor_digits", max_factor_digits),
        ("max_answer_chars", max_answer_chars),
    )
    for name, raw in settings:
        if raw is None or raw.strip() == "":
            continue
        flag, env = SETTINGS[name]
        try:
            if name == "deadline":
                out["deadline_ms"] = parse_deadline(raw)
            elif name == "max_digits":
                out["max_digits"] = parse_count(raw, "digits budget", MAX_DIGITS_RANGE)
            elif name == "max_reply_bytes":
                out["max_reply_bytes"] = parse_count(raw, "reply budget in bytes", MAX_REPLY_BYTES_RANGE)
            elif name == "max_array_bytes":
                out["max_array_bytes"] = parse_count(raw, "budget for arrays in bytes", MAX_ARRAY_BYTES_RANGE)
            elif name == "max_exact_elements":
                out["max_exact_elements"] = parse_count(raw, "limit on an exact array's elements", MAX_EXACT_ELEMENTS_RANGE)
            elif name == "max_arrangements":
                out["max_arrangements"] = parse_count(raw, "limit on a randomization test's arrangements", MAX_ARRANGEMENTS_RANGE)
            elif name == "max_shapley_factors":
                out["max_shapley_factors"] = parse_count(raw, "limit on a Shapley table's factors", MAX_SHAPLEY_FACTORS_RANGE)
            elif name == "max_prime_digits":
                out["max_prime_digits"] = parse_count(raw, "limit on the digits of a primality proof", MAX_PRIME_DIGITS_RANGE)
            elif name == "max_factor_digits":
                out["max_factor_digits"] = parse_count(raw, "limit on the digits of the part factoring splits", MAX_FACTOR_DIGITS_RANGE)
            else:
                out["max_answer_chars"] = parse_count(raw, "answer budget in characters", MAX_ANSWER_CHARS_RANGE)
        except ValueError as e:
            raise ValueError(f"{flag} (or {env}): {e}.") from None
    return Limits(**out)


# ---------------------------------------------------------------- sizes, without writing the number out


@cache
def ten_to(n: int) -> int:
    return 10**n


def digits(n: int) -> int:
    """The exact number of decimal digits of |n| (1 for 0), without turning n
    into text: a lower bound from its bit length, then a few comparisons."""
    n = abs(n)
    if n < 10:
        return 1
    # 2^(b-1) <= n, and 30102/100000 is just under log10(2), so this never overshoots.
    d = ((n.bit_length() - 1) * 30102) // 100000 + 1
    p = 10**d
    while n >= p:
        d += 1
        p *= 10
    return d


def power_digits_at_least(base: int, n: int) -> int:
    """A lower bound on the digits of base ** n (n >= 0), from base's size alone."""
    b = abs(base).bit_length()
    if b <= 1 or n == 0:  # 0, 1 or -1: the power stays 0 or 1
        return 1
    # base >= 2^(b-1), so base^n >= 2^(n(b-1)).
    return (n * (b - 1) * 30102) // 100000 + 1


def _power_size(b: int, n: int, exact_digits: Callable[[int, int], int | None] | None) -> tuple[int, bool]:
    """(the digits of |b| ** n, whether that count is exact rather than a lower bound)."""
    b = abs(b)
    if b <= 1 or n == 0:
        return 1, True
    if exact_digits is not None:
        d = exact_digits(b, n)
        if d is not None:
            return d, True
    return power_digits_at_least(b, n), False


def power_digits_at_most(base: int, n: int) -> int:
    """An upper bound on the digits of base ** n (n >= 0), from base's size alone."""
    b = abs(base).bit_length()
    if b <= 1 or n == 0:
        return 1
    # base < 2^b, so base^n < 2^(n b); 30103/100000 is just over log10(2).
    return (n * b * 30103) // 100000 + 1


def allow_int_text(max_digits: int) -> None:
    """Python refuses to write an int of more than 4,300 digits as text, by
    default. flo2-calc writes every value exactly, and its own digits budget is
    what bounds how large a value can be, so the interpreter's limit is raised to
    the budget (never lowered). Nothing else in this process writes numbers."""
    current = sys.get_int_max_str_digits()
    if current != 0 and current < max_digits + 1:
        sys.set_int_max_str_digits(max_digits + 1)


# ---------------------------------------------------------------- the guard


class Guard:
    """One call's budget. Starts its clock when it is made, at the call's start."""

    def __init__(self, limits: Limits = LAPTOP, clock: Callable[[], int] = time.monotonic_ns) -> None:
        self.limits = limits
        self._clock = clock
        self._started = clock()
        self._ends = self._started + limits.deadline_ms * 1_000_000
        self._ceiling = ten_to(limits.max_digits)
        self.largest = 0  # the largest numerator or denominator met so far
        self.node: str | None = None
        self.op: str | None = None
        self.done = 0
        self.total = 0
        self.reply_bytes = 0
        self.array_bytes = 0  # what the arrays made so far in this call hold
        allow_int_text(limits.max_digits)

    # -- where the evaluation is

    def at(self, node: str, op: str | None, done: int, total: int) -> None:
        self.node, self.op, self.done, self.total = node, op, done, total
        self.check_time()

    def past_nodes(self) -> None:
        """Every node is done; what follows is writing the reply."""
        self.node = self.op = None
        self.done = self.total

    # -- the three checks

    def check_time(self) -> None:
        if self._clock() > self._ends:
            where = (
                f'at node "{self.node}"' + (f" ({self.op})" if self.op else "") + f", after {self.done} of {self.total} nodes"
                if self.node is not None
                else (f"while writing the reply, after all {self.total} nodes were computed" if self.total else "while reading the call")
            )
            self._stop("deadline", f"this call passed this host's deadline of {seconds_text(self.limits.deadline_ms)} {where}.")

    def check_number(self, q: Fraction, what: str = "result") -> None:
        """After a value is made: its numerator and denominator within the
        digits budget. Checks the deadline too."""
        self.check_time()
        num, den = abs(q.numerator), q.denominator
        for part, n in (("numerator", num), ("denominator", den)):
            if n >= self._ceiling:
                d = digits(n)
                self._remember(n)
                self._stop(
                    "max_digits",
                    f"{self._here()}the {what} has a {part} of {d:,} digits, past this host's budget of "
                    f"{self.limits.max_digits:,} digits for any exact number.",
                    needed=d,
                )
        self._remember(num if num.bit_length() >= den.bit_length() else den)

    def _power_parts(self, base: Fraction, n: int) -> tuple[tuple[str, int], tuple[str, int]]:
        num, den = (base.numerator, base.denominator) if n >= 0 else (base.denominator, base.numerator)
        return ("numerator", num), ("denominator", den)

    def power_fits(self, base: Fraction, n: int, exact_digits: Callable[[int, int], int | None] | None = None) -> bool:
        """Whether base ** n is within the digits budget, judged as check_power
        judges it, without stopping."""
        for _part, b in self._power_parts(base, n):
            if power_digits_at_most(b, abs(n)) <= self.limits.max_digits:
                continue
            if _power_size(b, abs(n), exact_digits)[0] > self.limits.max_digits:
                return False
        return True

    def check_power(
        self,
        base: Fraction,
        n: int,
        exact_digits: Callable[[int, int], int | None] | None = None,
        hint: str = "",
    ) -> None:
        """BEFORE base ** n: refuse it when the result passes the digits budget.
        A power of a fraction in lowest terms stays in lowest terms, so its
        numerator and denominator are each base's to the power |n|: their digit
        counts come from `exact_digits` (realmath.power_digits, from Arb) where
        given and decided, else from a close lower bound (within a factor of two
        for base 2 or 3, tighter for anything larger). `hint` is said after the
        reason (pow: how to get a correctly rounded value instead). This is the
        ONLY size check on a power: flo2-calc 0.1.0 to 0.6.1 also refused any
        whole exponent above 1000, a cap the served limits never named
        (round 3: q072, q086)."""
        self.check_time()
        for part, b in self._power_parts(base, n):
            if power_digits_at_most(b, abs(n)) <= self.limits.max_digits:
                continue
            size, exact = _power_size(b, abs(n), exact_digits)
            if size > self.limits.max_digits:
                beyond = (
                    f" No host can carry it exactly: a digits budget is at most {MAX_DIGITS_RANGE[1]:,}."
                    if size > MAX_DIGITS_RANGE[1]
                    else ""
                )
                self._stop(
                    "max_digits",
                    f"{self._here()}the power's {part} would have {'' if exact else 'at least '}{size:,} digits, past "
                    f"this host's budget of {self.limits.max_digits:,} digits for any exact number, so it was not "
                    f"computed: flo2-calc sizes a power from its operands before computing it.{beyond}{hint}",
                    needed=size,
                )

    def check_digits(self, digits_: int, what: str, exact: bool = False) -> None:
        """BEFORE a value of `digits_` digits (a lower bound, unless `exact`) is
        computed: refuse it when that passes the digits budget (a factorial, a
        binomial coefficient, a binomial probability's denominator)."""
        self.check_time()
        if digits_ > self.limits.max_digits:
            beyond = (
                f" No host can carry it exactly: a digits budget is at most {MAX_DIGITS_RANGE[1]:,}."
                if digits_ > MAX_DIGITS_RANGE[1]
                else ""
            )
            self._stop(
                "max_digits",
                f"{self._here()}the {what} would have {'' if exact else 'at least '}{digits_:,} digits, past this host's "
                f"budget of {self.limits.max_digits:,} digits for any exact number, so it was not computed: flo2-calc "
                f"sizes it from its operands before computing it.{beyond}",
                needed=digits_,
            )

    def check_rounded_size(self, exponent: int, places: int, what: str = "result") -> None:
        """BEFORE a rounded value of `places` significant digits and decimal
        exponent `exponent` is written as an exact fraction: a value like
        1.2e-3000 is short as text but its denominator has 3,000 digits, so it
        is sized from its exponent first, never built and then measured."""
        self.check_time()
        needed = abs(exponent) + places + 1
        if needed > self.limits.max_digits:
            self._stop(
                "max_digits",
                f"{self._here()}the {what} is about 1e{exponent:+d}; carried exactly to {places} significant digits, "
                f"its {'numerator' if exponent >= 0 else 'denominator'} would have about {needed:,} digits, past this "
                f"host's budget of {self.limits.max_digits:,} digits for any exact number, so it was not made.",
                needed=needed,
            )

    def check_precision(self, working: int, what: str) -> None:
        """Deciding a correctly rounded value works at a precision that grows
        until the rounding is decided (realmath.py). The host's digits budget
        bounds that working precision too."""
        self.check_time()
        if working > self.limits.max_digits:
            self._stop(
                "max_digits",
                f"{self._here()}deciding {what} needed more than this host's budget of {self.limits.max_digits:,} "
                f"digits of working precision (it was about to work at {working:,}), so nothing was guessed.",
                needed=working,
            )

    def check_array_room(self, nbytes: int, elements: int, what: str = "result") -> None:
        """BEFORE an array is made, from its shape: refuse one that would pass
        the call's budget for arrays, so it is never allocated."""
        self.check_time()
        if self.array_bytes + nbytes > self.limits.max_array_bytes:
            self._stop(
                "max_array_bytes",
                f"{self._here()}the {what} would be an array of {elements:,} elements (about {nbytes:,} bytes), and "
                f"with the {self.array_bytes:,} bytes of arrays this call already holds that passes this host's budget "
                f"of {self.limits.max_array_bytes:,} bytes for arrays in one call, so it was not made.",
                needed=self.array_bytes + nbytes,
            )

    def spend_array(self, nbytes: int, elements: int, what: str = "result") -> None:
        """After an array is made: count what it holds against the call's budget."""
        self.array_bytes += nbytes
        if self.array_bytes > self.limits.max_array_bytes:
            self._stop(
                "max_array_bytes",
                f"{self._here()}the {what}, an array of {elements:,} elements (about {nbytes:,} bytes), brings the "
                f"arrays this call holds to about {self.array_bytes:,} bytes, past this host's budget of "
                f"{self.limits.max_array_bytes:,} bytes for arrays in one call.",
                needed=self.array_bytes,
            )
        self.check_time()

    def check_arrangements(self, count: int, what: str) -> None:
        """BEFORE a randomization test enumerates: refuse one whose scheme allows
        more arrangements than this host counts in one test."""
        self.check_time()
        if count > self.limits.max_arrangements:
            self._stop(
                "max_arrangements",
                f"{self._here()}{what} allows {count_text(count)} arrangements, past this host's limit of "
                f"{self.limits.max_arrangements:,} arrangements in one randomization test, so none was counted: the "
                "p-value is exact only over every arrangement, and flo2-calc never samples instead.",
                needed=count,
            )

    def check_factors(self, k: int) -> None:
        """BEFORE Shapley values are computed: refuse a table of more factors than
        this host takes (its outcomes grow as 2^k)."""
        self.check_time()
        if k > self.limits.max_shapley_factors:
            self._stop(
                "max_shapley_factors",
                f"{self._here()}the table has {k:,} factors, so 2^{k} = {count_text(2**k) if k <= 64 else 'more than 10^19'} "
                f"combinations, past this host's limit of Shapley values of at most {self.limits.max_shapley_factors} "
                "factors, so none was computed.",
                needed=k,
            )

    def check_prime_digits(self, digits_: int, what: str) -> None:
        """BEFORE a primality proof (integers.py): stop at a number of more digits
        than this host proves prime. Only a number that passed the probable-prime
        tests reaches here: one that fails them is composite, and answered."""
        self.check_time()
        if digits_ > self.limits.max_prime_digits:
            self._stop(
                "max_prime_digits",
                f"{self._here()}{what} has {digits_:,} digits and passes the BPSW probable-prime tests, which no known "
                "composite passes, but that is not a proof; proving it prime is past this host's limit of "
                f"{self.limits.max_prime_digits:,} digits for a primality proof, so it was not answered: a probable "
                "prime is never answered as prime.",
                needed=digits_,
            )

    def check_factor_digits(self, digits_: int, what: str) -> None:
        """BEFORE a factorization splits a composite with no small factors
        (integers.py): stop at one of more digits than this host factors."""
        self.check_time()
        if digits_ > self.limits.max_factor_digits:
            self._stop(
                "max_factor_digits",
                f"{self._here()}{what} is a composite of {digits_:,} digits, past this host's limit of "
                f"{self.limits.max_factor_digits:,} digits for the part a factorization has to split, so it was not "
                "factored: a factorization is never answered in part.",
                needed=digits_,
            )

    def check_exact_elements(self, count: int, what: str) -> None:
        """BEFORE an integer range is made: it is exact or not made, so stop at
        one of more elements than this host's exact arrays hold."""
        self.check_time()
        if count > self.limits.max_exact_elements:
            self._stop(
                "max_exact_elements",
                f"{self._here()}the {what} would hold {count:,} whole numbers, past this host's limit of "
                f"{self.limits.max_exact_elements:,} elements for an exact array, so it was not made: an integer range "
                "stays exact, because the integer operators take exact values only.",
                needed=count,
            )

    def spend_reply(self, nbytes: int) -> None:
        """Count bytes written into the reply as they are written, so a reply
        too large to send stops early instead of being built whole."""
        self.reply_bytes += nbytes
        if self.reply_bytes > self.limits.max_reply_bytes:
            self._stop(
                "max_reply_bytes",
                f"the reply passed this host's budget of {self.limits.max_reply_bytes:,} bytes for a reply and its "
                f"record while it was being written ({self.reply_bytes:,} bytes so far).",
                needed=self.reply_bytes,
            )
        self.check_time()

    def check_reply(self, nbytes: int, what: str = "the reply") -> None:
        """The finished reply's exact size."""
        if nbytes > self.limits.max_reply_bytes:
            self._stop(
                "max_reply_bytes",
                f"{what} would be {nbytes:,} bytes, past this host's budget of {self.limits.max_reply_bytes:,} bytes "
                "for a reply and its record.",
                needed=nbytes,
            )

    # -- the refusal

    def _here(self) -> str:
        if self.node is None:
            return ""
        return f'{self.op} at node "{self.node}": ' if self.op else f'input "{self.node}": '

    def _remember(self, n: int) -> None:
        if n.bit_length() > self.largest.bit_length():
            self.largest = n

    def elapsed_ms(self) -> int:
        return (self._clock() - self._started) // 1_000_000

    def _stop(self, name: str, reason: str, needed: int | None = None) -> None:
        flag, env = SETTINGS[name]
        limit: dict[str, Any] = {"name": name, "value": self.limits.value_of(name)}
        if needed is not None:
            limit["needed_at_least"] = needed
        limit["setting"] = f"{flag} or {env}"
        raise LimitExceeded(
            {
                "node": self.node,
                "op": self.op,
                "kind": "exceeds_limits",
                "reason": reason + " The calculation was stopped cleanly; nothing was cut short or guessed.",
                "limit": limit,
                "reached": {
                    "nodes_done": self.done,
                    "nodes": self.total,
                    "largest_digits": digits(self.largest),
                    "elapsed": seconds_text(self.elapsed_ms()),
                },
                "limits": self.limits.describe(),
            }
        )


def count_text(n: int) -> str:
    """A count in full with separators, or, past 10^18, as a power of ten."""
    if n < 10**18:
        return f"{n:,}"
    return f"about 10^{digits(n) - 1}"


def stopped_for_record(refusal: dict[str, Any]) -> dict[str, Any]:
    """What a not-yet-computed record keeps of the refusal: the limit, where it
    stopped, why, and how far it got. Not the elapsed time, which is the
    machine's and not the calculation's."""
    limit = {k: v for k, v in refusal["limit"].items() if k != "setting"}
    reached = {k: v for k, v in refusal["reached"].items() if k != "elapsed"}
    return {"limit": limit, "node": refusal["node"], "op": refusal["op"], "reason": refusal["reason"], "reached": reached}
