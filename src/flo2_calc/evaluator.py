"""The computation graph: how it is written, how it is read, how it is evaluated.

A GRAPH is a list of named nodes and, optionally, which one is the result
(the last node when it is not named):

    {"nodes": [
       {"id": "cavity", "value": "2 mm", "source": {"design_node": "con:cavity-depth"}},
       {"id": "bend", "value": "1.4 mm", "source": "fiber datasheet, minimum bend radius"},
       {"id": "margin", "op": "sub", "args": ["cavity", "bend"]},
       {"id": "needed", "value": "0.5 mm", "source": "assumed"},
       {"id": "fits", "op": "ge", "args": ["margin", "needed"]}],
     "result": "fits"}

An INPUT node has a `value`: a number with its unit as text ("1.4 mm"), a
plain number ("0.1", or a JSON integer), or true/false. Its `source` says
where the value came from: free text, or {"design_node": "<id>"} naming a node
in a reflow2 design (with "design": "<design id>" when it is another design).
flo2-calc records a source and never resolves it. An exchange rate (a value
whose unit holds two currencies, "0.92 EUR/USD") must have one: flo2-calc
holds no rates, so the rate is the caller's, and must say where it came from.
A value is one number: text that holds arithmetic ("3 + 4") is refused as an
expression, to be built as nodes.

An OPERATION node has an `op` and `args`, the ids of the nodes it takes, in
order. `convert` also takes the `unit` to convert to (a change of temperature
converted to K is written delta_K, so it stays a change), and so do asin, acos,
atan and atan2 (the angle unit of their result, "deg" or "rad"), `magnitude`
(the unit to read a quantity's number in) and `with_unit` (the unit it states,
with the `source` that states it). db_to_ratio and ratio_to_db take `kind`,
"power" or "amplitude", which is never defaulted. An operator
of the rounded class may take `digits`, the significant digits of its result
(30 when not given); ceil, floor and round may take `places`, the decimal
places to round to (0 when not given), and round a `mode` (half_even when not
given). Any node may carry a free-text `note`.

TWO CLASSES OF VALUE (dec:round-1-fixes-one-to-six). An EXACT value is an
exact fraction, as every value was before. A ROUNDED value comes from an
operator whose result is irrational in general (pi, e, sqrt, exp, ln, log10, a
non-whole power, trigonometry, a deg-rad conversion, the distributions), or
from arithmetic on a rounded value. It is a decimal of `digits` significant
digits with a rigorous bound on its distance from the true value
(realmath.py), and it is labelled so in every reply and record. Where a
result is rational it stays exact: sqrt(9/4) is 3/2, sin(30 deg) is 1/2.
Arithmetic on a rounded value gives the correctly rounded result on its
written decimal, and its bound grows by what the arguments' bounds allow. A
comparison, ceil, floor or round of a rounded value is answered only when the
bound decides it, and refused (kind "undecidable") otherwise: a true/false or
a whole number is never a guess.

RESULTS. `result` names the result node, or a list of them: then each is
reported by name, in that order, as "results" (dec:round-2-fixes). With no
`result`, the last node listed is the result.

SHOWN BACK (formula.py). Every answer carries the computation as a formula and
as numbered steps, each in plain text with LaTeX beside it, rendered from what
was evaluated.

ARRAYS (arrays.py; req:flo2-calc-computes-over-arrays). An input's value may
be an array, {"array": [...], "unit": "<unit>"} (one or two dimensions, one
unit), or, run locally, {"file": "<path>"}. Every operator works element by
element on arrays, with numpy's broadcasting; reductions (sum, product, mean,
min, max, count_true, any, all, argmin, argmax, with "axis" for a grid),
statistics over data (variance_sample, variance_population, sd_sample,
sd_population, and the fit_* least-squares results), the FFT (fft, ifft,
fft2, ifft2), complex parts (abs for the modulus, phase, real, imag, conj) and making
and shaping arrays (linspace, column, transpose, element) are operators of
their own. An exact array stays exact through rational operations; an FFT, a
function over an array or a large array is FLOAT64, labelled with a rigorous
bound on every element. `_apply` hands any operation with an array among its
arguments, or an operator only arrays have, to arrays.apply.

READING. A graph that cannot be read is a CallError naming the field: no
nodes, a repeated id, an unknown operator or field, the wrong number of
arguments, a reference to a node that is not there, a cycle, a value that is
not a number, an unknown unit, an expression typed as a value, an exchange
rate with no source.

EVALUATING. Nodes are evaluated in one fixed order: each as soon as every node
it takes is done, ties broken by the order they are listed in. The first node
that cannot be computed stops the evaluation with a Refusal naming that node,
its operation and why. Every value computed before it is still reported.
The whole-graph path and the node-by-node path (add_node) both end here, in
`evaluate`, which is why they give the same result.

LIMITS. `evaluate` runs under a limits.Guard, the host's limits for one call:
the deadline is checked before every node and after every step of an
operation with many arguments; every input, partial result and value is held
to the digits budget; a power is sized before it is computed; a rounded value
is sized from its exponent before it is made, and the working precision that
decides its rounding is held to the digits budget too. Passing one stops the
evaluation like a refusal, of kind "exceeds_limits" (limits.py). These are the
only limits on a calculation: a power has no exponent cap of its own (0.1.0
to 0.6.1 refused any whole exponent above 1000; round 3, q072 and q086).

ROUND 3 (flo2-calc 0.7.0): choose and factorial, exact; the binomial
distribution (binomial_pmf, binomial_cdf, binomial_sf), exact for an exact p;
to_number (true is 1, false is 0); length (an array's elements); a whole
power of a rounded base for any exponent, and of an exact base past the
digits budget as a correctly rounded value when the node asks for "digits".
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Any

from flo2_calc import arrays as A
from flo2_calc import decibels as D
from flo2_calc import formula as FM
from flo2_calc import limits as L
from flo2_calc import numbers as N
from flo2_calc import realmath as RM
from flo2_calc import temperature as T
from flo2_calc import units as U
from flo2_calc.errors import CallError, LimitExceeded, Refusal, at
from flo2_calc.numbers import (
    EXACT_BUT_ROUNDED,
    EXACT_FOR_THESE_INPUTS,
    MAX_NUMBER_TEXT,
    NUMBER_THEN_REST,
    expression_problem,
    format_number,
    looks_like_expression,
    parse_number,
)

MAX_NODES = 500
MAX_ARGS = 100
MAX_NOTE = 2000
MAX_PLACES = 1000
ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class Rounding:
    """How a rounded value stands for the true one."""

    digits: int  # significant digits it is written to
    error: Fraction  # |true value - magnitude| <= error, in the value's unit; > 0
    correctly_rounded: bool  # the true value, rounded half-even to `digits` (its arguments were exact)
    origins: tuple[str, ...]  # the rounded-class nodes it rests on


@dataclass(frozen=True)
class Quantity:
    magnitude: Fraction
    unit: U.Unit = U.PLAIN
    rounding: Rounding | None = None  # None: exact

    @property
    def error(self) -> Fraction:
        return self.rounding.error if self.rounding is not None else Fraction(0)


Value = Quantity | bool  # | arrays.Array: an array, or a single float64 value (shape ())

ARITHMETIC, FUNCTIONS, CONSTANTS, TRIG, ROUNDING, STATISTICS = (
    "arithmetic", "functions", "constants", "trigonometry", "rounding", "statistics",
)
UNITS_OPS, DECIBELS, COUNTING = "units", "decibels", "counting"  # dec:round-2-fixes
COMBINATORICS = "combinatorics"  # round 3
REDUCTION, DATA, TRANSFORM, COMPLEX, ARRAY = (
    "reductions", "statistics over data", "transforms", "complex values", "making and shaping arrays",
)

# (family, fewest args, most args or None for "any number up to MAX_ARGS"), and what it does
OPS: dict[str, tuple[str, int, int | None, str]] = {
    "add": (ARITHMETIC, 2, None, "the sum; every unit must measure the same thing, and the result is in the first one's unit"),
    "sub": (ARITHMETIC, 2, 2, "the first minus the second, in the first one's unit"),
    "mul": (ARITHMETIC, 2, None, "the product; units multiply (mm * mm is mm^2)"),
    "div": (ARITHMETIC, 2, 2, "the first divided by the second; units divide; division by zero is refused"),
    "neg": (ARITHMETIC, 1, 1, "minus the value"),
    "abs": (ARITHMETIC, 1, 1, "the absolute value; of a complex value (an FFT's), its modulus |z|"),
    "pow": (ARITHMETIC, 2, 2, "the first raised to the second, a plain number: exact for a whole exponent of any size, sized "
            "before it is computed and stopped past the host's digits budget (with \"digits\", such a power of an exact base "
            "is given correctly rounded instead); a whole power of a rounded base is rounded; a non-whole exponent "
            "(\"1/3\", \"2.5\") gives a rounded value unless the result is rational, needs a base >= 0, and keeps a unit "
            "only when its root is exact (m^2 to the 1/2 is m)"),
    "min": (ARITHMETIC, 1, None, "the smallest, in the first one's unit; element by element for arrays; with ONE array, "
            "the smallest of its elements (\"axis\" 0 or 1 for each column or row of a grid)"),
    "max": (ARITHMETIC, 1, None, "the largest, in the first one's unit; element by element for arrays; with ONE array, "
            "the largest of its elements (\"axis\" as for min)"),
    "convert": (ARITHMETIC, 1, 1, 'the value in the node\'s "unit" ("" for a plain number); it must measure the same thing. '
                "deg to rad (or back) is a rounded value, since pi/180 is irrational; every other conversion is exact. A "
                "change of temperature converted to K is written delta_K: it stays a change, and never converts to degC or "
                "degF as a temperature"),
    "sqrt": (FUNCTIONS, 1, 1, "the square root of a value >= 0; exact when it is rational (sqrt(9/4) is 3/2), else rounded; "
             "m^2 gives m, and a unit with no exact square root (m) is refused"),
    "exp": (FUNCTIONS, 1, 1, "e to the power of a plain number; rounded (exp(0) is exactly 1)"),
    "ln": (FUNCTIONS, 1, 1, "the natural logarithm of a plain number > 0; rounded (ln(1) is exactly 0)"),
    "log10": (FUNCTIONS, 1, 1, "the base-10 logarithm of a plain number > 0; exact for a power of ten, else rounded"),
    "pi": (CONSTANTS, 0, 0, "the constant pi, rounded (no args)"),
    "e": (CONSTANTS, 0, 0, "the constant e, rounded (no args)"),
    "sin": (TRIG, 1, 1, "the sine of an angle in deg, arcmin, arcsec or rad (a plain number is refused); rounded, exact where rational "
            "(sin(30 deg) is 1/2)"),
    "cos": (TRIG, 1, 1, "the cosine of an angle (deg, arcmin, arcsec or rad); rounded, exact where rational (cos(60 deg) is 1/2)"),
    "tan": (TRIG, 1, 1, "the tangent of an angle (deg, arcmin, arcsec or rad); rounded, exact where rational; tan(90 deg) is refused"),
    "asin": (TRIG, 1, 1, 'the arcsine of a plain number in [-1, 1], as an angle in the node\'s "unit" ("deg" or "rad")'),
    "acos": (TRIG, 1, 1, 'the arccosine of a plain number in [-1, 1], as an angle in the node\'s "unit" ("deg" or "rad")'),
    "atan": (TRIG, 1, 1, 'the arctangent of a plain number, as an angle in the node\'s "unit" ("deg" or "rad")'),
    "atan2": (TRIG, 2, 2, 'the angle of the point (x, y) for args [y, x], in (-180, 180] deg, as an angle in the node\'s '
              '"unit"; y and x measure the same thing; atan2(0, 0) is refused'),
    "ceil": (ROUNDING, 1, 1, 'the least multiple of 10^-places at or above the value (places 0: a whole number), in its '
             "unit; exact"),
    "floor": (ROUNDING, 1, 1, "the greatest multiple of 10^-places at or below the value, in its unit; exact"),
    "round": (ROUNDING, 1, 1, 'the value rounded to `places` decimal places (0: a whole number), in its unit; exact; '
              '"mode" is half_even (the default), half_away_from_zero, half_toward_zero, half_up (ties toward '
              "+infinity) or half_down (ties toward -infinity)"),
    "normal_cdf": (STATISTICS, 1, 3, "P(X <= x) for args [x] (the standard normal) or [x, mean, sd], all in one unit, "
                   "sd > 0; rounded"),
    "normal_sf": (STATISTICS, 1, 3, "P(X > x), the upper tail, for args [x] or [x, mean, sd]; accurate far into the tail; rounded"),
    "normal_quantile": (STATISTICS, 1, 3, "the x with P(X <= x) = p, for args [p] or [p, mean, sd], p a plain number in "
                        "(0, 1); in the mean's unit; rounded"),
    "chi2_sf": (STATISTICS, 2, 2, "the chi-square upper tail P(X > x), for args [x, dof], x >= 0 and dof an exact plain "
                "number > 0: a test's p-value; rounded"),
    "t_quantile": (STATISTICS, 2, 2, "the Student-t x with P(T <= x) = p, for args [p, dof], p in (0, 1) and dof an exact "
                   "plain number > 0; rounded"),
    # round 3
    "binomial_pmf": (STATISTICS, 3, 3, "P(X = k) for X binomial with args [k, n, p]: n independent trials, each with "
                     "probability p; k and n exact whole plain numbers (n >= 0), p a plain number from 0 to 1. Exact for an "
                     "exact p; from a rounded p, rounded with its bound"),
    "binomial_cdf": (STATISTICS, 3, 3, "P(X <= k), at most k successes, for args [k, n, p] as binomial_pmf; exact for an exact p"),
    "binomial_sf": (STATISTICS, 3, 3, "P(X > k), MORE than k successes, for args [k, n, p] as binomial_pmf (\"at least 3 of 5\" "
                    "is binomial_sf of k = 2); exact for an exact p"),
    "and": ("logic", 2, None, "true when every argument is true"),
    "or": ("logic", 2, None, "true when any argument is true"),
    "not": ("logic", 1, 1, "true when the argument is false"),
    "nand": ("logic", 2, None, "not and"),
    "nor": ("logic", 2, None, "not or"),
    "xor": ("logic", 2, None, "true when an odd number of arguments are true"),
    "sum": (REDUCTION, 1, 1, 'the sum of an array\'s elements, in its unit; "axis" 0 sums each column of a grid, 1 each row '
            "(a discretised integral is a sum of an element-wise product); exact for exact data"),
    "product": (REDUCTION, 1, 1, 'the product of a plain array\'s elements ("axis" as for sum)'),
    "mean": (REDUCTION, 1, 1, 'the mean of an array\'s elements, in its unit ("axis" as for sum); exact for exact data'),
    "any": (REDUCTION, 1, 1, 'true when any element of a true/false array is ("axis" as for sum)'),
    "all": (REDUCTION, 1, 1, 'true when every element of a true/false array is ("axis" as for sum)'),
    "argmin": (REDUCTION, 1, 1, "the index (0 for the first) of the smallest element of a 1-D array; the first of exact ties"),
    "argmax": (REDUCTION, 1, 1, "the index (0 for the first) of the largest element of a 1-D array; the first of exact ties"),
    "variance_sample": (DATA, 1, 1, "the sample variance of a 1-D array (divides by n - 1), in its unit squared; exact for exact data"),
    "variance_population": (DATA, 1, 1, "the population variance of a 1-D array (divides by n), in its unit squared; exact for exact data"),
    "sd_sample": (DATA, 1, 1, "the sample standard deviation (n - 1), in the data's unit; correctly rounded for exact data"),
    "sd_population": (DATA, 1, 1, "the population standard deviation (n), in the data's unit; correctly rounded for exact data"),
    "fit_slope": (DATA, 2, 2, "the least-squares slope of y on x, for args [x, y] (1-D, the same length), in y's unit per x's; "
                  "exact for exact data"),
    "fit_intercept": (DATA, 2, 2, "the least-squares intercept, for args [x, y], in y's unit; exact for exact data"),
    "fit_slope_se": (DATA, 2, 2, "the slope's standard error, s / sqrt(Sxx), for args [x, y]; correctly rounded for exact data"),
    "fit_intercept_se": (DATA, 2, 2, "the intercept's standard error, s sqrt(1/n + mean(x)^2 / Sxx), for args [x, y]"),
    "fit_residual_se": (DATA, 2, 2, "the residual standard error s = sqrt(SSR / (n - 2)), for args [x, y], in y's unit"),
    "fft": (TRANSFORM, 1, 1, "the discrete Fourier transform of a 1-D array, numpy's convention (no scaling); complex, float64, "
            "labelled with its error bound"),
    "ifft": (TRANSFORM, 1, 1, "the inverse transform of a 1-D array (scaled by 1/n); complex, float64, labelled"),
    "fft2": (TRANSFORM, 1, 1, "the 2-D discrete Fourier transform of a grid; complex, float64, labelled"),
    "ifft2": (TRANSFORM, 1, 1, "the inverse 2-D transform of a grid (scaled by 1/(m n)); complex, float64, labelled"),
    "phase": (COMPLEX, 1, 1, 'the angle of each element, in (-180, 180] deg, in the node\'s "unit" ("deg" or "rad"); float64; '
              "an element at (or, within its bound, possibly at) zero is refused"),
    "real": (COMPLEX, 1, 1, "the real part of each element"),
    "imag": (COMPLEX, 1, 1, "the imaginary part of each element"),
    "conj": (COMPLEX, 1, 1, "the complex conjugate of each element"),
    "linspace": (ARRAY, 3, 3, "args [start, stop, count]: count evenly spaced values from start to stop, both ends included, in "
                 "start's unit; exact for exact ends"),
    "column": (ARRAY, 1, 1, "a 1-D array of n as a column (n x 1), to meet a row element by element as a grid"),
    "transpose": (ARRAY, 1, 1, "a grid's rows as columns"),
    "element": (ARRAY, 2, 3, "args [array, i] or [array, row, col]: one element (indices from 0)"),
    "eq": ("comparison", 2, 2, "equal (numbers after converting to the first one's unit, or two true/false values)"),
    "ne": ("comparison", 2, 2, "not equal"),
    "lt": ("comparison", 2, 2, "the first is less than the second"),
    "le": ("comparison", 2, 2, "the first is less than or equal to the second"),
    "gt": ("comparison", 2, 2, "the first is greater than the second"),
    "ge": ("comparison", 2, 2, "the first is greater than or equal to the second"),
    # dec:round-2-fixes
    "magnitude": (UNITS_OPS, 1, 1, 'the number of the node\'s "unit" a quantity is, a plain number (2 A in "mA" is 2000); '
                  "refused unless the quantity measures what that unit measures. For an empirical formula, whose "
                  "numbers are taken in stated units"),
    "with_unit": (UNITS_OPS, 1, 1, 'a plain number given the node\'s "unit", which the node\'s "source" states: the document '
                  "the formula and its constants were given from (an empirical formula's result in the unit that document "
                  "states); flo2-calc cannot check it, so it is recorded. An empirical formula's constants are inputs whose "
                  "sources say where the person or a cited document gave them, never recalled from memory"),
    "db_to_ratio": (DECIBELS, 1, 1, 'a gain in dB as a plain ratio: "kind" "power" gives 10^(x/10), "amplitude" '
                    "10^(x/20); kind is never defaulted; rounded unless exact"),
    "ratio_to_db": (DECIBELS, 1, 1, 'a plain ratio > 0 as a gain in dB: "kind" "power" gives 10 log10(r), '
                    '"amplitude" 20 log10(r); kind is never defaulted; rounded unless exact'),
    "count_true": (COUNTING, 1, None, "how many of the true/false arguments are true, or how many elements of one "
                   'true/false array are ("axis" 0 or 1 for each column or row of a grid): an exact whole number'),
    "k_of_n": (COUNTING, 2, None, "args [k, b1, b2, ...]: true when at least k of the true/false values b are true; "
               "k is an exact whole number from 0 to their count; [k, array] counts a true/false array's elements"),
    # round 3
    "to_number": (COUNTING, 1, 1, "a true/false value as a number: true is 1 and false is 0, exactly (element by element "
                  "for a true/false array); never a guess, and the only way a true/false value becomes a number"),
    "choose": (COMBINATORICS, 2, 2, "the binomial coefficient C(n, k), for args [n, k]: the ways to choose k of n, exact; n and "
               "k exact whole plain numbers, n >= 0 and k >= 0 (0 when k > n)"),
    "factorial": (COMBINATORICS, 1, 1, "n! for an exact whole plain number n >= 0, exact (0! is 1); sized before it is computed"),
    "length": (REDUCTION, 1, 1, 'the number of elements of an array, an exact whole number; with "axis" 0 the length of each '
               "column (the grid's rows), with 1 the length of each row"),
}

# Operators that may give a rounded value, and so take "digits".
ROUNDED_OPS = frozenset(
    k for k, v in OPS.items() if v[0] in (FUNCTIONS, CONSTANTS, TRIG, STATISTICS, DECIBELS)
) | {"pow", "convert", "magnitude", "sd_sample", "sd_population", "fit_slope_se", "fit_intercept_se", "fit_residual_se"}
UNIT_OPS = frozenset({"convert", "asin", "acos", "atan", "atan2", "magnitude", "with_unit", "phase"})
ANGLE_UNIT_OPS = frozenset({"asin", "acos", "atan", "atan2", "phase"})
KIND_OPS = frozenset({"db_to_ratio", "ratio_to_db"})  # each must be told "kind"
SOURCED_OPS = frozenset({"with_unit"})  # each must say, in "source", where what it asserts comes from
AXIS_OPS = frozenset({"sum", "product", "mean", "min", "max", "count_true", "any", "all", "length"})
# Exact operators that take single values, and take exact arrays element by element (arrays.py).
PER_ELEMENT = frozenset({"choose", "factorial", "binomial_pmf", "binomial_cdf", "binomial_sf"})
ROUND_MODES = ("half_even", "half_away_from_zero", "half_toward_zero", "half_up", "half_down")

INPUT_KEYS = ("id", "value", "source", "note")
OP_KEYS = ("id", "op", "args", "unit", "digits", "places", "mode", "kind", "source", "axis", "note")
GRAPH_KEYS = ("nodes", "result")
SOURCE_KEYS = ("design_node", "design")


@dataclass(frozen=True)
class InputNode:
    id: str
    raw: str | dict[str, Any]  # the value's text as given (a JSON integer or true/false made text); an array's object
    value: Value
    source: str | dict[str, str] | None
    note: str | None


@dataclass(frozen=True)
class OpNode:
    id: str
    op: str
    args: tuple[str, ...]
    unit: U.Unit | None  # convert's target, or an inverse trigonometric function's angle unit
    unit_text: str | None
    note: str | None
    digits: int | None = None
    places: int | None = None
    mode: str | None = None
    kind: str | None = None  # db_to_ratio, ratio_to_db: "power" or "amplitude"
    source: str | dict[str, str] | None = None  # with_unit: where the unit it states comes from
    axis: int | None = None  # a reduction over a grid: 0 down each column, 1 along each row


Node = InputNode | OpNode


@dataclass(frozen=True)
class Graph:
    nodes: tuple[Node, ...]
    result: str  # the result; with a list of results, the first of them
    result_named: bool  # whether the graph named its result (else: the last node)
    results: tuple[str, ...] | None = None  # "result" given as a list: every result, in its order

    @property
    def result_ids(self) -> tuple[str, ...]:
        return self.results if self.results is not None else (self.result,)

    def by_id(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}

    def to_json(self) -> dict[str, Any]:
        """The graph as flo2-calc read it, every value as text: the form a
        record keeps and add_node hands back."""
        out: list[dict[str, Any]] = []
        for n in self.nodes:
            if isinstance(n, InputNode):
                d: dict[str, Any] = {"id": n.id, "value": n.raw}
                if n.source is not None:
                    d["source"] = n.source
            else:
                d = {"id": n.id, "op": n.op, "args": list(n.args)}
                if n.unit_text is not None:
                    d["unit"] = n.unit_text
                for key in ("digits", "places", "mode", "kind", "source", "axis"):
                    if getattr(n, key) is not None:
                        d[key] = getattr(n, key)
            if n.note is not None:
                d["note"] = n.note
            out.append(d)
        g: dict[str, Any] = {"nodes": out}
        if self.results is not None:
            g["result"] = list(self.results)
        elif self.result_named:
            g["result"] = self.result
        return g


@dataclass
class Evaluation:
    graph: Graph
    guard: L.Guard
    order: list[str] = field(default_factory=list)
    values: dict[str, Value] = field(default_factory=dict)
    refusal: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None

    @property
    def stopped(self) -> bool:
        """Stopped at one of the host's limits, rather than refused for a reason in the graph."""
        return self.refusal is not None and self.refusal.get("kind") == "exceeds_limits"

    def result_value(self) -> Value | None:
        return self.values.get(self.graph.result) if self.ok else None


# ---------------------------------------------------------------- values as text


@dataclass(frozen=True)
class Style:
    """How values are written, by the record format they are written for. A
    record re-runs under its own version's style, so a record made by an
    earlier flo2-calc still reproduces byte for byte."""

    whole_in_full: bool  # a whole number in full, never "/1" or e-notation
    every_digit: bool  # a rounded value with every one of its digits, trailing zeros kept
    simplify_units: bool  # a computed value's compound unit shown simpler where one is the same size (units.simplify)
    every_line_valued: bool = True  # every formula line ends with its value, not only a result's (round 3)


LEGACY = Style(False, False, False, False)  # record schema versions 1 to 3 (flo2-calc 0.1.0 to 0.4.0)
FORMULA_RESULTS_ONLY = Style(True, True, True, False)  # versions 4 to 6 (0.5.0 to 0.6.1): only a result's line has its value
CURRENT = Style(True, True, True, True)  # schema version 7 (0.7.0), and every reply


def _power_of_ten(f: Fraction) -> bool:
    n, d = f.numerator, f.denominator
    if n != 1 and d != 1:
        return False
    k = n if d == 1 else d
    return L.ten_to(L.digits(k) - 1) == k


def value_json(v: Value, style: Style = CURRENT, computed: bool = False) -> dict[str, Any]:
    """A value as replies and records write it: {"value": "0.3 mm"}, plus
    "exact" when the text of an exact value is rounded (the exact value FOR
    THESE INPUTS: the inputs as written, no more accurate than they are), or
    "rounded" (its digits, its error bound and where its rounding came from)
    when the value itself is a rounded one. A rounded value is never given an
    "exact", and is never exact.

    A `computed` value (an operation's whose unit came from a rule of
    arithmetic, not an input's or a unit the graph chose) whose compound unit
    has a simpler one of the same size (units.simplify) is shown in it, with
    "simplified_from" naming the unit it was computed in. Only what is shown
    changes, and a rounded value's only by a power of ten."""
    if isinstance(v, bool):
        return {"value": "true" if v else "false"}
    if isinstance(v, A.Array):
        return A.value_json(v, computed=computed and style.simplify_units)
    simplified_from = None
    if computed and style.simplify_units:
        simpler = U.simplify(v.unit)
        if simpler is not None and (v.rounding is None or _power_of_ten(simpler[1])):
            to, k = simpler
            simplified_from = U.format_unit(v.unit)
            rounding = v.rounding
            if rounding is not None:
                rounding = Rounding(rounding.digits, rounding.error * k, rounding.correctly_rounded, rounding.origins)
            v = Quantity(v.magnitude * k, to, rounding)
    unit = U.format_unit(v.unit)

    def with_unit(text: str) -> str:
        return f"{text} {unit}" if unit else text

    if v.rounding is not None:
        r = v.rounding
        text = N.significant_text(v.magnitude, r.digits) if style.every_digit else N.decimal_text(v.magnitude)
        out: dict[str, Any] = {
            "value": with_unit(text),
            "rounded": {
                "digits": r.digits,
                "correctly_rounded": r.correctly_rounded,
                "error_at_most": with_unit(N.decimal_text(r.error)),
                "from": list(r.origins),
            },
        }
    else:
        text, exact = format_number(v.magnitude, style.whole_in_full)
        out = {"value": with_unit(text)}
        if exact is not None:
            out["exact"] = with_unit(exact)
    if simplified_from is not None:
        out["simplified_from"] = simplified_from
    return out


def value_text(v: Value) -> str:
    return value_json(v)["value"]


def parse_value(raw: Any, path: str, data_root: Any = None, exact_limit: int | None = None) -> tuple[Any, Value]:
    """(the value's text, the value) from what a call gave; an array's object
    (arrays.py) comes back as the object a record keeps, and the array."""
    if isinstance(raw, dict):
        return A.parse_input(raw, path, data_root, exact_limit)
    if isinstance(raw, list):
        raise CallError(path, 'an array is written {"array": [...], "unit": "<unit>"}, so its one unit is given once.')
    if isinstance(raw, bool):
        return ("true" if raw else "false"), raw
    if isinstance(raw, int):
        if abs(raw) >= L.ten_to(MAX_NUMBER_TEXT):
            raise CallError(path, f"a number is at most {MAX_NUMBER_TEXT} digits; this JSON integer is longer.")
        return str(raw), Quantity(Fraction(raw))
    if isinstance(raw, float):
        if raw.is_integer() and abs(raw) < 2**53:
            return str(int(raw)), Quantity(Fraction(int(raw)))
        raise CallError(
            path,
            f"{raw!r} arrived as a JSON number with a fraction part, which reaches flo2-calc as a binary "
            f'floating-point number whose exact value is already lost. Write it as text: "{raw!r}".',
        )
    if not isinstance(raw, str):
        raise CallError(path, 'a value is text: a number with its unit ("1.4 mm"), a plain number ("0.1"), or true/false.')
    text = raw.strip()
    if text in ("true", "false"):
        return raw, text == "true"
    if text in ("pi", "e"):
        raise CallError(
            path,
            f'"{text}" is a constant, not a typed value: write an operation node {{"id": "{text}", "op": "{text}"}}, '
            "which gives it correctly rounded and labelled rounded.",
        )
    m = NUMBER_THEN_REST.match(text)
    if not m:
        if looks_like_expression(text, whole=True):  # "(3+4)", "pi*2"
            raise CallError(path, expression_problem(raw))
        raise CallError(
            path,
            f'"{raw}" is not a value: write a number with its unit ("1.4 mm"), a plain number ("0.1" or "1/3"), or true/false.',
        )
    if looks_like_expression(m.group(2)):  # "3 + * 4", "3*4", "2^10", "1/2/3", "2 1/2"
        raise CallError(path, expression_problem(raw))
    try:
        number = parse_number(m.group(1))
        unit = U.parse_unit(m.group(2))
    except ValueError as e:  # UnitTextError is a ValueError
        raise CallError(path, str(e)) from None
    return raw, Quantity(number, unit)


# ---------------------------------------------------------------- reading a graph


def _note(obj: dict[str, Any], path: str) -> str | None:
    if "note" not in obj:
        return None
    note = obj["note"]
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise CallError(at(path, "note"), f"a note is text of at most {MAX_NOTE} characters.")
    return note


def _source(obj: dict[str, Any], path: str) -> str | dict[str, str] | None:
    if "source" not in obj:
        return None
    src = obj["source"]
    p = at(path, "source")
    if isinstance(src, str):
        if not src.strip() or len(src) > MAX_NOTE:
            raise CallError(p, f"a source is free text (1 to {MAX_NOTE} characters) or {{\"design_node\": \"<id>\"}}.")
        return src
    if isinstance(src, dict):
        unknown = [k for k in src if k not in SOURCE_KEYS]
        if unknown:
            raise CallError(at(p, unknown[0]), 'a design source has only "design_node" and, for another design, "design".')
        dn = src.get("design_node")
        if not isinstance(dn, str) or not re.fullmatch(r"\S{1,200}", dn):
            raise CallError(at(p, "design_node"), 'name the design node by its id, e.g. "con:cavity-depth" (no spaces).')
        out = {"design_node": dn}
        if "design" in src:
            d = src["design"]
            if not isinstance(d, str) or not re.fullmatch(r"\S{1,200}", d):
                raise CallError(at(p, "design"), "name the design by its id, with no spaces.")
            out["design"] = d
        return out
    raise CallError(p, 'a source is free text, or {"design_node": "<id>"} naming a node in a reflow2 design.')


def _whole(obj: dict[str, Any], key: str, path: str, lo: int, hi: int, what: str) -> int | None:
    if key not in obj:
        return None
    v = obj[key]
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise CallError(at(path, key), f"{what}: a whole number from {lo} to {hi}.")
    return v


def _known_ops() -> str:
    families: dict[str, list[str]] = {}
    for k, v in OPS.items():
        families.setdefault(v[0], []).append(k)
    return "; ".join(f"{family} ({', '.join(names)})" for family, names in families.items())


def _node(obj: Any, path: str, data_root: Any = None, exact_limit: int | None = None) -> Node:
    if not isinstance(obj, dict):
        raise CallError(path, 'a node is an object: {"id", "value"} for an input, or {"id", "op", "args"} for an operation.')
    nid = obj.get("id")
    if not isinstance(nid, str) or not ID.match(nid):
        raise CallError(
            at(path, "id"),
            "every node has an id: a letter or _, then up to 63 letters, digits, _ . or -, e.g. \"bend_radius\".",
        )
    if "value" in obj and "op" in obj:
        raise CallError(path, f'node "{nid}" has both "value" and "op": an input has a value, an operation has an op.')
    if "value" in obj:
        unknown = [k for k in obj if k not in INPUT_KEYS]
        if unknown:
            raise CallError(at(path, unknown[0]), f"an input node has only {', '.join(INPUT_KEYS)}.")
        raw, value = parse_value(obj["value"], at(path, "value"), data_root, exact_limit)
        source = _source(obj, path)
        if source is None and not isinstance(value, bool) and len(U.currencies_in(value.unit)) > 1:
            raise CallError(
                at(path, "source"),
                f'"{raw}" is an exchange rate, and an exchange rate must say where it came from and when: give it a '
                '"source", for example "ECB reference rate, 2026-10-02". flo2-calc holds no rates of its own.',
            )
        return InputNode(nid, raw, value, source, _note(obj, path))
    if "op" not in obj:
        raise CallError(path, f'node "{nid}" has neither "value" (an input) nor "op" (an operation).')
    unknown = [k for k in obj if k not in OP_KEYS]
    if unknown:
        raise CallError(at(path, unknown[0]), f"an operation node has only {', '.join(OP_KEYS)}.")
    op = obj["op"]
    if not isinstance(op, str) or op not in OPS:
        raise CallError(
            at(path, "op"),
            f"{op!r} is not an operator flo2-calc has. It has: {_known_ops()}. Set operations come later.",
        )
    family, least, most, _what = OPS[op]
    args = obj.get("args", [] if family == CONSTANTS else None)
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise CallError(at(path, "args"), f'"{op}" takes "args": a list of the ids of the nodes it works on, in order.')
    most_n = MAX_ARGS if most is None else most
    if not least <= len(args) <= most_n or (family == STATISTICS and least == 1 and len(args) == 2):
        if family == STATISTICS and least == 1:
            want = "1 ([x], the standard normal) or 3 ([x, mean, sd])" if op != "normal_quantile" else "1 ([p]) or 3 ([p, mean, sd])"
        elif least == most == 0:
            want = "no"
        else:
            want = f"exactly {least}" if least == most else f"{least} to {most_n}"
        raise CallError(at(path, "args"), f'"{op}" takes {want} argument(s); this node gives {len(args)}.')
    unit = unit_text = None
    if op in UNIT_OPS:
        if "unit" not in obj or not isinstance(obj["unit"], str):
            if op == "convert":
                raise CallError(at(path, "unit"), 'convert needs "unit": the unit to convert to, e.g. "mm" ("" for a plain number).')
            if op == "magnitude":
                raise CallError(at(path, "unit"), 'magnitude needs "unit": the unit to take the quantity\'s number in, e.g. "mil".')
            if op == "with_unit":
                raise CallError(at(path, "unit"), 'with_unit needs "unit": the unit the formula states for its result, e.g. "mil^2".')
            raise CallError(at(path, "unit"), f'{op} needs "unit": the angle unit of its result, "deg" or "rad" (or "arcmin", "arcsec").')
        unit_text = obj["unit"]
        if op in ("magnitude", "with_unit") and not unit_text.strip():
            raise CallError(at(path, "unit"), f'{op} takes a unit to name; "" (a plain number) is no unit. Use convert to make a ratio plain.')
        try:
            unit = U.parse_unit(unit_text)
        except ValueError as e:
            raise CallError(at(path, "unit"), str(e)) from None
        if op in ANGLE_UNIT_OPS and U.angle_kind(unit) is None:
            raise CallError(at(path, "unit"), f'{op} gives an angle: its "unit" is "deg" or "rad" (or "arcmin", "arcsec"), not "{unit_text}".')
    elif "unit" in obj:
        raise CallError(
            at(path, "unit"),
            f'only convert, magnitude, with_unit, asin, acos, atan, atan2 and phase take a "unit"; "{op}" keeps the '
            "units of what it takes.",
        )
    kind = None
    if op in KIND_OPS:
        kind = obj.get("kind")
        if kind not in D.KINDS:
            given = "" if "kind" not in obj else f" {kind!r} is neither."
            raise CallError(
                at(path, "kind"),
                f'{op} needs "kind": "power" (10 log10, a ratio of two powers) or "amplitude" (20 log10, a ratio of two '
                f"field quantities such as voltages or pressures).{given} The same dB is a different ratio in each "
                "(10 dB is a power ratio of 10 and an amplitude ratio of about 3.16), so flo2-calc never picks one.",
            )
    elif "kind" in obj:
        raise CallError(at(path, "kind"), f'only db_to_ratio and ratio_to_db take "kind"; "{op}" takes none.')
    source = None
    if op in SOURCED_OPS:
        source = _source(obj, path)
        if source is None:
            raise CallError(
                at(path, "source"),
                f'{op} states a unit flo2-calc cannot check, so it must say where that unit comes from: give it a '
                '"source", the document (and edition) that gives the formula and states its unit, or {"design_node": "<id>"}.',
            )
    elif "source" in obj:
        raise CallError(at(path, "source"), f'only an input and with_unit take a "source"; "{op}" computes its value.')
    if "digits" in obj and op not in ROUNDED_OPS:
        raise CallError(at(path, "digits"), f'"{op}" gives an exact result, so it takes no "digits".')
    digits_ = _whole(obj, "digits", path, 1, RM.MAX_DIGITS, "digits is how many significant digits a rounded result has")
    if ("places" in obj or "mode" in obj) and op not in ("ceil", "floor", "round"):
        key = "places" if "places" in obj else "mode"
        raise CallError(at(path, key), f'only ceil, floor and round take "{key}".')
    places = _whole(obj, "places", path, -MAX_PLACES, MAX_PLACES, "places is how many decimal places to keep (negative: tens, hundreds ...)")
    mode = None
    if "mode" in obj:
        if op != "round":
            raise CallError(at(path, "mode"), f'only round takes "mode"; {op} rounds one way only.')
        mode = obj["mode"]
        if mode not in ROUND_MODES:
            raise CallError(at(path, "mode"), f"round's mode is one of {', '.join(ROUND_MODES)}; half_even is the default.")
    axis = None
    if "axis" in obj:
        if op not in AXIS_OPS:
            raise CallError(at(path, "axis"), f'only {", ".join(sorted(AXIS_OPS))} take "axis"; "{op}" does not.')
        axis = obj["axis"]
        if axis not in (0, 1) or isinstance(axis, bool):
            raise CallError(at(path, "axis"), 'a grid\'s "axis" is 0 (down each column) or 1 (along each row).')
    return OpNode(nid, op, tuple(args), unit, unit_text, _note(obj, path), digits_, places, mode, kind, source, axis)


def read_nodes(
    items: list[tuple[Any, str]],
    result: Any = None,
    result_path: str = "graph.result",
    data_root: Any = None,
    exact_limit: int | None = None,
) -> Graph:
    """A graph from (node, field path) pairs. Raises CallError. `exact_limit`
    is the most elements an input array may have and stay exact (the host's
    max_exact_elements; a laptop's when not given). `data_root` is
    the folder an array's data file may be read from (None: none)."""
    if not items:
        raise CallError("graph.nodes", "a graph needs at least one node.")
    if len(items) > MAX_NODES:
        raise CallError("graph.nodes", f"a graph has at most {MAX_NODES} nodes; this one has {len(items)}.")
    nodes: list[Node] = []
    seen: dict[str, str] = {}
    for obj, path in items:
        node = _node(obj, path, data_root, exact_limit)
        if node.id in seen:
            raise CallError(at(path, "id"), f'"{node.id}" is already the id of {seen[node.id]}; every id names one node.')
        seen[node.id] = path
        nodes.append(node)
    ids = set(seen)
    for (_obj, path), node in zip(items, nodes, strict=True):
        if isinstance(node, OpNode):
            for i, a in enumerate(node.args):
                if a not in ids:
                    raise CallError(at(at(path, "args"), i), f'"{a}" is not the id of any node in this graph.')
    results: tuple[str, ...] | None = None
    if result is None:
        named = False
        result_id = nodes[-1].id
    elif isinstance(result, list):
        named = True
        if not result:
            raise CallError(result_path, 'a list of results names at least one node; leave "result" out for the last node.')
        for i, r in enumerate(result):
            if not isinstance(r, str) or r not in ids:
                raise CallError(at(result_path, i), f"{r!r} is not the id of any node in this graph.")
            if result.index(r) != i:
                raise CallError(at(result_path, i), f'"{r}" is named twice; name each result once.')
        results = tuple(result)
        result_id = results[0]
    else:
        named = True
        if not isinstance(result, str) or result not in ids:
            raise CallError(result_path, f"{result!r} is not the id of any node in this graph (or a list of ids).")
        result_id = result
    graph = Graph(tuple(nodes), result_id, named, results)
    evaluation_order(graph)  # refuses a cycle now, as a malformed call
    return graph


def read_graph(obj: Any, path: str = "graph", data_root: Any = None, exact_limit: int | None = None) -> Graph:
    if not isinstance(obj, dict):
        raise CallError(path, 'a graph is an object: {"nodes": [...], "result": "<id>"}.')
    unknown = [k for k in obj if k not in GRAPH_KEYS]
    if unknown:
        raise CallError(at(path, unknown[0]), 'a graph has only "nodes" and, optionally, "result" (an id, or a list of ids).')
    nodes = obj.get("nodes")
    if not isinstance(nodes, list):
        raise CallError(at(path, "nodes"), "a graph's nodes are a list.")
    return read_nodes([(n, at(at(path, "nodes"), i)) for i, n in enumerate(nodes)], obj.get("result"), at(path, "result"), data_root, exact_limit)


def evaluation_order(graph: Graph) -> list[str]:
    """Each node as soon as every node it takes is done, ties broken by list
    order. Raises CallError naming a cycle."""
    deps = {n.id: set(n.args) if isinstance(n, OpNode) else set() for n in graph.nodes}
    done: list[str] = []
    done_set: set[str] = set()
    remaining = [n.id for n in graph.nodes]
    while remaining:
        nxt = next((nid for nid in remaining if deps[nid] <= done_set), None)
        if nxt is None:
            raise CallError("graph.nodes", f"these nodes depend on each other in a cycle: {_a_cycle(deps, remaining)}.")
        remaining.remove(nxt)
        done.append(nxt)
        done_set.add(nxt)
    return done


def _a_cycle(deps: dict[str, set[str]], remaining: list[str]) -> str:
    left = set(remaining)
    start = remaining[0]
    path = [start]
    while True:
        here = path[-1]
        nxt = sorted(d for d in deps[here] if d in left)[0]
        if nxt in path:
            loop = path[path.index(nxt):] + [nxt]
            return " -> ".join(loop)
        path.append(nxt)


# ---------------------------------------------------------------- evaluating: shared parts


def _numbers(op: str, args: list[Value], names: tuple[str, ...]) -> list[Quantity]:
    for a, name in zip(args, names, strict=True):
        if isinstance(a, bool):
            raise Refusal(
                f'{op} takes numbers, and "{name}" is {"true" if a else "false"}.',
                kind="type_mismatch",
            )
    return args  # type: ignore[return-value]


def _booleans(op: str, args: list[Value], names: tuple[str, ...]) -> list[bool]:
    for a, name in zip(args, names, strict=True):
        if not isinstance(a, bool):
            raise Refusal(
                f'{op} takes true/false values, and "{name}" is the number {value_text(a)}.',
                kind="type_mismatch",
            )
    return args  # type: ignore[return-value]


def _in_unit_of(first: Quantity, other: Quantity, op: str) -> Fraction:
    """`other`'s magnitude in `first`'s unit, exactly. Refuses a mismatch."""
    return other.magnitude * U.conversion(other.unit, first.unit, op)


def _rounded(args: list[Value]) -> list[Quantity]:
    return [a for a in args if isinstance(a, Quantity) and a.rounding is not None]


def _origins(args: list[Value], own: str | None = None) -> tuple[str, ...]:
    out = [o for a in _rounded(args) for o in a.rounding.origins]  # type: ignore[union-attr]
    if own is not None:
        out.append(own)
    return tuple(dict.fromkeys(out))


def _settle(center: Fraction, unit: U.Unit, error: Fraction, args: list[Value]) -> Quantity:
    """Arithmetic on rounded values: the exact result on their written
    decimals, rounded half-even to the most digits any of them has, with its
    error bound grown by that rounding and rounded up to two significant
    digits. With no rounded argument, or a bound of 0 (0 times anything), it
    is exact."""
    rounded = _rounded(args)
    if not rounded or error == 0:
        return Quantity(center, unit)
    places = max(a.rounding.digits for a in rounded)  # type: ignore[union-attr]
    c = N.round_significant(center, places)
    bound = N.round_up_significant(error + abs(center - c), 2)
    return Quantity(c, unit, Rounding(places, bound, False, _origins(args)))


def _places(node: OpNode, args: list[Value]) -> int:
    if node.digits is not None:
        return node.digits
    rounded = _rounded(args)
    return max((a.rounding.digits for a in rounded), default=RM.DEFAULT_DIGITS)  # type: ignore[union-attr]


def _ball(q: Quantity, scale: Fraction = Fraction(1)) -> RM.Ball:
    return RM.Ball(q.magnitude * scale, q.error * scale)


def _outcome(out: RM.Outcome, unit: U.Unit, node: OpNode, args: list[Value], places: int) -> Quantity:
    if out.error == 0:
        return Quantity(out.value, unit)
    return Quantity(out.value, unit, Rounding(places, out.error, out.correctly_rounded, _origins(args, node.id)))


def _number_text(q: Fraction) -> str:
    text, exact = format_number(q)
    return text if exact is None else exact


def _bound(q: Quantity) -> str:
    return value_text(Quantity(q.error, q.unit)) if q.rounding is not None else "0"


def _undecidable(reason: str, *qs: Quantity) -> Refusal:
    rounded = [q for q in qs if q.rounding is not None]
    named = "; ".join(f"{value_text(q)} is within {_bound(q)} of its true value" for q in rounded)
    return Refusal(f"{reason} ({named}), so flo2-calc does not guess. Ask for more digits, or decide it another way.", kind="undecidable")


def _sign(b: RM.Ball) -> int | None:
    """+1, -1 or 0 when the ball decides the sign; None when it holds 0 and more."""
    if b.lo > 0:
        return 1
    if b.hi < 0:
        return -1
    if b.mid == 0 and b.rad == 0:
        return 0
    return None


def _fold(q: Quantity) -> Quantity:
    """A "%" folded into the magnitude (and its error), so 4 % is 0.04."""
    if not any(s == U.PERCENT for s, _ in q.unit):
        return q
    k = dict(q.unit)[U.PERCENT]
    scale = Fraction(1, 100) ** k
    unit = tuple((s, e) for s, e in q.unit if s != U.PERCENT)
    rounding = q.rounding
    if rounding is not None:
        rounding = Rounding(rounding.digits, rounding.error * scale, rounding.correctly_rounded, rounding.origins)
    return Quantity(q.magnitude * scale, unit, rounding)


def _plain(op: str, q: Quantity, name: str, what: str = "a plain number") -> Quantity:
    """q as a plain number (a "%" folded in); refuses any other unit."""
    q = _fold(q)
    if q.unit != U.PLAIN:
        raise Refusal(
            f'{op} takes {what}, and "{name}" is {value_text(q)} ({U.describe_dimension(q.unit)}). A unit is never '
            "dropped: divide it by a value in the same unit first if a ratio is what you mean.",
            kind="unit_mismatch",
            units=(U.format_unit(q.unit), ""),
        )
    return q


# ---------------------------------------------------------------- arithmetic, exact or on rounded values


def _arithmetic(node: OpNode, qs: list[Quantity], guard: L.Guard) -> Quantity:
    op, names = node.op, node.args
    first = qs[0]
    if op == "add":
        total, error = first.magnitude, first.error
        for i, q in enumerate(qs[1:], 2):  # step by step, each partial sum held to the budget
            f = U.conversion(q.unit, first.unit, op)
            total = total + q.magnitude * f
            error += q.error * f
            guard.check_number(total, "sum" if i == len(qs) else f"partial sum (of the first {i} arguments)")
        return _settle(total, first.unit, error, qs)  # type: ignore[arg-type]
    if op == "sub":
        f = U.conversion(qs[1].unit, first.unit, op)
        return _settle(first.magnitude - qs[1].magnitude * f, first.unit, first.error + qs[1].error * f, qs)  # type: ignore[arg-type]
    if op in ("min", "max"):
        scaled = [(first.magnitude, first.error)]
        for q in qs[1:]:
            f = U.conversion(q.unit, first.unit, op)
            scaled.append((q.magnitude * f, q.error * f))
        pick = min if op == "min" else max
        # min and max move a value by at most the largest error among them.
        return _settle(pick(m for m, _ in scaled), first.unit, max(e for _, e in scaled), qs)  # type: ignore[arg-type]
    if op == "neg":
        return Quantity(-first.magnitude, first.unit, first.rounding)
    if op == "abs":
        # | |t| - |m| | <= |t - m|, and half-even rounding is symmetric: the label carries over.
        return Quantity(abs(first.magnitude), first.unit, first.rounding)
    if op == "mul":
        mag, unit, error = first.magnitude, first.unit, first.error
        for i, q in enumerate(qs[1:], 2):  # step by step, each partial product held to the budget
            unit, scale = U.multiply(unit, q.unit)
            error = (abs(mag) * q.error + abs(q.magnitude) * error + error * q.error) * scale
            mag = mag * q.magnitude * scale
            guard.check_number(mag, "product" if i == len(qs) else f"partial product (of the first {i} arguments)")
        return _settle(mag, unit, error, qs)  # type: ignore[arg-type]
    if op == "div":
        divisor = qs[1]
        if divisor.magnitude == 0 and divisor.rounding is None:
            raise Refusal(f'div: "{names[1]}" is zero ({value_text(divisor)}), and division by zero has no value.', kind="division_by_zero")
        if _sign(_ball(divisor)) is None:
            raise _undecidable(f'div: "{names[1]}" may be zero within its error bound', divisor)
        unit, scale = U.multiply(first.unit, U.invert(divisor.unit))
        a, ra, b, rb = first.magnitude, first.error, divisor.magnitude, divisor.error
        error = (abs(a) * rb + abs(b) * ra) / (abs(b) * (abs(b) - rb)) * scale if (ra or rb) else Fraction(0)
        return _settle(a / b * scale, unit, error, qs)  # type: ignore[arg-type]
    if op == "pow":
        return _pow(node, qs, guard)
    if op == "convert":
        assert node.unit is not None
        try:
            f = U.conversion(first.unit, node.unit, op)
        except Refusal:
            turned = U.pi_conversion(first.unit, node.unit)
            if turned is None:
                raise
            f, k = turned
            places = _places(node, qs)  # type: ignore[arg-type]
            out = RM.evaluate(RM.angle_factor(k), [_ball(first, f)], places, guard)
            return _outcome(out, node.unit, node, qs, places)  # type: ignore[arg-type]
        return _settle(first.magnitude * f, U.converted_unit(first.unit, node.unit), first.error * f, qs)  # type: ignore[arg-type]
    raise AssertionError(f"operator {op} has no evaluation")  # pragma: no cover


def _power_hint(base: Fraction, n: int, places: int, guard: L.Guard) -> str:
    """What a refused exact power can be instead: its correctly rounded value,
    when one that size fits the budget, else how large it is."""
    if base == 0:
        return ""
    decade = RM.power_decade(base, n)
    if abs(decade) + places + 1 <= guard.limits.max_digits:
        return (
            f' Its value is about 1e{decade:+d}: give the node "digits" (for example {places}) for its correctly rounded '
            "value, labelled rounded."
        )
    return f" Its value is about 1e{decade:+d}, too far from 1 for even a rounded value to be carried within this budget."


def _pow(node: OpNode, qs: list[Quantity], guard: L.Guard) -> Quantity:
    names = node.args
    first, exponent = qs
    if exponent.unit != U.PLAIN:
        raise Refusal(
            f'pow: the exponent "{names[1]}" is {value_text(exponent)}; it must be a plain number.',
            kind="bad_exponent",
        )
    whole = exponent.rounding is None and exponent.magnitude.denominator == 1
    if whole:
        n = exponent.magnitude.numerator
        if first.magnitude == 0 and n < 0 and first.rounding is None:
            raise Refusal(f'pow: "{names[0]}" is zero, and a negative power of zero divides by zero.', kind="division_by_zero")
        if first.magnitude == 0 and n == 0 and first.rounding is None:
            raise Refusal("pow: zero to the power zero has no single agreed value, so flo2-calc does not pick one.", kind="undefined")
        unit, scale = U.power(first.unit, n)
        base = first.magnitude
        folded = Fraction(1)
        if scale != 1:
            # A folded "%" (U.fold_percent): m^n * (1/100)^(k*n) is (m / 100^k)^n. Folding
            # it into the base first keeps the base in lowest terms, so the size check
            # below is of the power actually computed.
            k = dict(first.unit)[U.PERCENT]
            assert scale == Fraction(1, 100) ** (k * n)
            folded = Fraction(1, 100) ** k
            base = base * folded
        places = _places(node, qs)  # type: ignore[arg-type]
        if first.rounding is None:
            # Sized BEFORE computing: a huge power stalls inside one operation. Within the budget it is exact;
            # past it, a node that asks for "digits" gets the correctly rounded value, and any other is stopped.
            if guard.power_fits(base, n, RM.power_digits):
                return Quantity(base**n, unit)
            if node.digits is not None and base != 0:
                guard.check_rounded_size(RM.power_decade(base, n), places, "power")
                out = RM.evaluate(RM.integer_power(n, guard), [RM.Ball(base)], places, guard)
                return _outcome(out, unit, node, qs, places)  # type: ignore[arg-type]
            guard.check_power(base, n, RM.power_digits, _power_hint(base, n, places, guard))
            raise AssertionError("check_power passes what power_fits refused")  # pragma: no cover
        # A rounded base, any exponent: the correctly rounded power of its written decimal (exactly, where that
        # fits the budget), with Arb's bound over its ball, sized from its exponent first.
        ball = _ball(first, folded)
        if n <= 0 and _sign(ball) is None:
            raise _undecidable(f'pow: "{names[0]}" may be zero within its error bound, and {"a negative power" if n else "the power zero"} of zero has no value', first)
        if n == 0:
            return Quantity(Fraction(1), unit)
        if ball.mid != 0:
            guard.check_rounded_size(RM.power_decade(ball.mid, n), places, "power")
        out = RM.evaluate(RM.integer_power(n, guard), [ball], places, guard)
        if out.error == 0:
            return Quantity(out.value, unit)
        return Quantity(out.value, unit, Rounding(places, out.error, False, _origins(qs)))  # type: ignore[arg-type]
    # A non-whole (or rounded) exponent: a plain base >= 0, and a unit only when its root is exact.
    base = _fold(first)
    unit: U.Unit = U.PLAIN
    if base.unit != U.PLAIN:
        if exponent.rounding is not None:
            raise Refusal(
                f'pow: "{names[0]}" is {value_text(first)} and the exponent "{names[1]}" is a rounded value, so the '
                "power of its unit would not be exact. Make the base a plain number first.",
                kind="unit_mismatch",
                units=(U.format_unit(first.unit), ""),
            )
        y = exponent.magnitude
        powers = [(s, e * y) for s, e in base.unit]
        if any(p.denominator != 1 for _, p in powers):
            shown = U.format_unit(base.unit)
            raise Refusal(
                f'pow: "{names[0]}" is in {shown}, and {shown} to the power {_number_text(y)} '
                "is not a unit (its exponents would not be whole numbers). Raise a plain number, or a unit with an "
                "exact root (m^2 to the 1/2 is m).",
                kind="unit_mismatch",
                units=(shown, ""),
            )
        unit = tuple((s, int(p)) for s, p in powers)
    x, y = _ball(base), _ball(exponent)
    sx, sy = _sign(x), _sign(y)
    if sx == -1:
        raise Refusal(
            f'pow: "{names[0]}" is negative ({value_text(first)}), and a negative number to a non-whole power has no '
            "real value in general. For an odd root, take the root of its absolute value and negate it.",
            kind="out_of_domain",
        )
    if sx is None:
        raise _undecidable(f'pow: "{names[0]}" may be negative within its error bound, and a negative number has no non-whole power', first)
    if sx == 0:
        if sy is None:
            raise _undecidable(f'pow: "{names[0]}" is zero and the sign of the exponent "{names[1]}" is not decided', exponent)
        if sy < 0:
            raise Refusal(f'pow: "{names[0]}" is zero, and a negative power of zero divides by zero.', kind="division_by_zero")
        return Quantity(Fraction(0), unit)
    places = _places(node, qs)  # type: ignore[arg-type]
    if x.exact and y.exact:
        # Sized before Arb is asked: |y| * log10(x) digits, from x's decade.
        guard.check_rounded_size(int(abs(y.mid) * abs(N.decade(x.mid))), places, "power")
    out = RM.evaluate(RM.pow_fn(guard), [x, y], places, guard)
    return _outcome(out, unit, node, qs, places)  # type: ignore[arg-type]


# ---------------------------------------------------------------- the rounded class: functions, trigonometry, statistics


def _function(node: OpNode, qs: list[Quantity], guard: L.Guard) -> Quantity:
    op, names = node.op, node.args
    places = _places(node, qs)  # type: ignore[arg-type]
    if op in ("pi", "e"):
        return _outcome(RM.evaluate(RM.PI if op == "pi" else RM.E, [], places, guard), U.PLAIN, node, [], places)
    q = qs[0]
    if op == "sqrt":
        folded = _fold(q)
        if any(e % 2 for _, e in folded.unit):
            shown = U.format_unit(folded.unit)
            raise Refusal(
                f'sqrt: "{names[0]}" is in {shown}, which has no exact square root as a unit (its exponents are not all '
                "even). Take the square root of a plain number, or of a unit squared (mm^2 gives mm).",
                kind="unit_mismatch",
                units=(shown, ""),
            )
        unit = tuple((s, e // 2) for s, e in folded.unit)
        x = _ball(folded)
        s = _sign(x)
        if s == -1:
            raise Refusal(f'sqrt: "{names[0]}" is negative ({value_text(q)}), and a negative number has no real square root.', kind="out_of_domain")
        if s is None:
            raise _undecidable(f'sqrt: "{names[0]}" may be negative within its error bound', q)
        return _outcome(RM.evaluate(RM.SQRT, [x], places, guard), unit, node, qs, places)  # type: ignore[arg-type]
    x = _ball(_plain(op, q, names[0]))
    if op == "exp":
        # Sized before Arb is asked: exp(x) is about 10^(0.434 x).
        if x.mid:
            guard.check_rounded_size(int(x.mid * Fraction(4342944819, 10**10)), places, "exponential")
        return _outcome(RM.evaluate(RM.EXP, [x], places, guard), U.PLAIN, node, qs, places)  # type: ignore[arg-type]
    if op in ("ln", "log10"):
        s = _sign(x)
        if s is not None and s <= 0:
            raise Refusal(f'{op}: "{names[0]}" is {value_text(q)}; a logarithm needs a number greater than 0.', kind="out_of_domain")
        if s is None:
            raise _undecidable(f'{op}: "{names[0]}" may be 0 or less within its error bound', q)
        return _outcome(RM.evaluate(RM.LN if op == "ln" else RM.LOG10, [x], places, guard), U.PLAIN, node, qs, places)  # type: ignore[arg-type]
    raise AssertionError(op)  # pragma: no cover


def _angle(op: str, q: Quantity, name: str) -> tuple[str, Fraction]:
    kind = U.angle_kind(q.unit)
    if kind is None:
        what = "a plain number" if q.unit == U.PLAIN else f"in {U.format_unit(q.unit)} ({U.describe_dimension(q.unit)})"
        raise Refusal(
            f'{op} takes an angle in deg or rad (or arcmin, arcsec), and "{name}" is {what}. Give the angle its unit, '
            "so it is never taken in the wrong one.",
            kind="unit_mismatch",
            units=(U.format_unit(q.unit), "deg"),
        )
    return kind


def _trigonometry(node: OpNode, qs: list[Quantity], guard: L.Guard) -> Quantity:
    op, names = node.op, node.args
    places = _places(node, qs)  # type: ignore[arg-type]
    if op in ("sin", "cos", "tan"):
        kind, f = _angle(op, qs[0], names[0])
        x = _ball(qs[0], f)
        if op == "tan" and kind == "deg":
            # tan has no value at 90 deg + any multiple of 180 deg.
            pole = 90 + 180 * -((90 - x.lo) // 180)  # the first pole at or above x.lo
            if x.exact and (x.mid - 90) % 180 == 0:
                raise Refusal(f'tan: "{names[0]}" is {value_text(qs[0])}, where the tangent has no value.', kind="undefined")
            if not x.exact and x.lo <= pole <= x.hi:
                raise _undecidable(f'tan: "{names[0]}" may be {pole} deg within its error bound, where the tangent has no value', qs[0])
        fn = {"sin": RM.SIN, "cos": RM.COS, "tan": RM.TAN}[op][kind]
        return _outcome(RM.evaluate(fn, [x], places, guard), U.PLAIN, node, qs, places)  # type: ignore[arg-type]
    assert node.unit is not None
    kind, f = U.angle_kind(node.unit)  # type: ignore[misc]
    if op == "atan2":
        y, xq = qs
        # x in y's unit: the angle of (x, y) does not depend on the unit they share.
        by, bx = _ball(y), _ball(xq, U.conversion(xq.unit, y.unit, op))
        sy, sx = _sign(by), _sign(bx)
        if sy == 0 and sx == 0:
            raise Refusal(f'atan2: "{names[0]}" and "{names[1]}" are both zero, and the angle of the origin has no value.', kind="undefined")
        if sy is None and sx is None:
            raise _undecidable(f'atan2: "{names[0]}" and "{names[1]}" may both be zero within their error bounds', y, xq)
        if sy is None and sx == -1:
            raise _undecidable(f'atan2: "{names[0]}" may be either side of zero with "{names[1]}" negative, so the angle may be near +180 or -180 deg', y)
        fn = RM.scaled(RM.ATAN2[kind], 1 / f)
        return _outcome(RM.evaluate(fn, [by, bx], places, guard), node.unit, node, qs, places)  # type: ignore[arg-type]
    x = _ball(_plain(op, qs[0], names[0]))
    if op in ("asin", "acos"):
        if x.exact and abs(x.mid) > 1 or x.lo > 1 or x.hi < -1:
            raise Refusal(f'{op}: "{names[0]}" is {value_text(qs[0])}; {op} takes a number from -1 to 1.', kind="out_of_domain")
        if x.lo < -1 or x.hi > 1:
            raise _undecidable(f'{op}: "{names[0]}" may be outside -1 to 1 within its error bound', qs[0])
    fn = RM.scaled({"asin": RM.ASIN, "acos": RM.ACOS, "atan": RM.ATAN}[op][kind], 1 / f)
    return _outcome(RM.evaluate(fn, [x], places, guard), node.unit, node, qs, places)  # type: ignore[arg-type]


def _probability(op: str, q: Quantity, name: str) -> RM.Ball:
    p = _ball(_plain(op, q, name, "a probability, a plain number"))
    if (p.exact and not 0 < p.mid < 1) or p.hi <= 0 or p.lo >= 1:
        raise Refusal(
            f'{op}: "{name}" is {value_text(q)}; a probability for {op} is strictly between 0 and 1 (at 0 and 1 the '
            "quantile is infinite).",
            kind="out_of_domain",
        )
    if p.lo <= 0 or p.hi >= 1:
        raise _undecidable(f'{op}: "{name}" may be 0 or 1 within its error bound', q)
    return p


def _positive(op: str, q: Quantity, name: str, what: str, ball: RM.Ball | None = None) -> None:
    """Refuses unless the value (or its ball in another unit) is surely > 0."""
    s = _sign(ball if ball is not None else _ball(q))
    if s is not None and s <= 0:
        raise Refusal(f'{op}: "{name}" is {value_text(q)}; {what} must be greater than 0.', kind="out_of_domain")
    if s is None:
        raise _undecidable(f'{op}: "{name}" may be 0 or less within its error bound', q)


def _dof(op: str, q: Quantity, name: str) -> Fraction:
    q = _plain(op, q, name, "degrees of freedom, a plain number")
    if q.rounding is not None:
        raise Refusal(
            f'{op}: the degrees of freedom "{name}" are a rounded value ({value_text(q)}); they must be exact.',
            kind="out_of_domain",
        )
    _positive(op, q, name, "the degrees of freedom")
    return q.magnitude


def _statistics(node: OpNode, qs: list[Quantity], guard: L.Guard) -> Quantity:
    op, names = node.op, node.args
    places = _places(node, qs)  # type: ignore[arg-type]
    if op in ("normal_cdf", "normal_sf"):
        if len(qs) == 1:
            x = _ball(_plain(op, qs[0], names[0], "a plain number (the standard normal), or [x, mean, sd] in one unit"))
            mean, sd = RM.Ball(Fraction(0)), RM.Ball(Fraction(1))
        else:
            first = qs[0]
            x = _ball(first)
            mean = _ball(qs[1], U.conversion(qs[1].unit, first.unit, op))
            sd = _ball(qs[2], U.conversion(qs[2].unit, first.unit, op))
            _positive(op, qs[2], names[2], "the standard deviation", sd)
        fn = RM.NORMAL_CDF if op == "normal_cdf" else RM.NORMAL_SF
        return _outcome(RM.evaluate(fn, [x, mean, sd], places, guard), U.PLAIN, node, qs, places)  # type: ignore[arg-type]
    if op == "normal_quantile":
        p = _probability(op, qs[0], names[0])
        if len(qs) == 1:
            mean, sd, unit = RM.Ball(Fraction(0)), RM.Ball(Fraction(1)), U.PLAIN
        else:
            unit = qs[1].unit
            mean = _ball(qs[1])
            sd = _ball(qs[2], U.conversion(qs[2].unit, unit, op))
            _positive(op, qs[2], names[2], "the standard deviation", sd)
        return _outcome(RM.evaluate(RM.NORMAL_QUANTILE, [p, mean, sd], places, guard), unit, node, qs, places)  # type: ignore[arg-type]
    if op == "chi2_sf":
        x = _ball(_plain(op, qs[0], names[0], "a chi-square statistic, a plain number"))
        dof = _dof(op, qs[1], names[1])
        if (x.exact and x.mid < 0) or x.hi < 0:
            raise Refusal(f'chi2_sf: "{names[0]}" is {value_text(qs[0])}; a chi-square statistic is never negative.', kind="out_of_domain")
        if x.lo < 0:
            raise _undecidable(f'chi2_sf: "{names[0]}" may be negative within its error bound', qs[0])
        return _outcome(RM.evaluate(RM.CHI2_SF, [x, RM.Ball(dof)], places, guard), U.PLAIN, node, qs, places)  # type: ignore[arg-type]
    if op == "t_quantile":
        p = _probability(op, qs[0], names[0])
        dof = _dof(op, qs[1], names[1])
        return _outcome(RM.t_quantile(p, dof, places, guard), U.PLAIN, node, qs, places)  # type: ignore[arg-type]
    if op in BINOMIAL:
        return _binomial(node, qs, guard)
    raise AssertionError(op)  # pragma: no cover


# ---------------------------------------------------------------- combinatorics and the binomial (round 3)

BINOMIAL = ("binomial_pmf", "binomial_cdf", "binomial_sf")


def _whole_number(op: str, q: Value, name: str, what: str, least: int | None = 0) -> int:
    """An exact whole plain number (at least `least`, when given), or a refusal naming why not."""
    if isinstance(q, bool):
        raise Refusal(f'{op} takes {what}, and "{name}" is {"true" if q else "false"}.', kind="type_mismatch")
    if q.unit != U.PLAIN:
        raise Refusal(
            f'{op} takes {what}, a plain number, and "{name}" is {value_text(q)} ({U.describe_dimension(q.unit)}).',
            kind="unit_mismatch",
            units=(U.format_unit(q.unit), ""),
        )
    if q.rounding is not None:
        raise Refusal(f'{op} takes {what}, an exact whole number, and "{name}" is a rounded value ({value_text(q)}).', kind="out_of_domain")
    if q.magnitude.denominator != 1 or (least is not None and q.magnitude < least):
        bound = "" if least is None else f" of at least {least}"
        raise Refusal(f'{op} takes {what}, a whole number{bound}, and "{name}" is {value_text(q)}.', kind="out_of_domain")
    return q.magnitude.numerator


def _combinatorics(node: OpNode, args: list[Value], guard: L.Guard) -> Quantity:
    """choose and factorial: exact whole numbers, sized before they are computed
    (a lower bound on their digits against the host's budget), then held to it."""
    op, names = node.op, node.args
    if op == "factorial":
        n = _whole_number(op, args[0], names[0], "n")
        # n! >= (n/3)^n, so its digits are at least those of floor(n/3)^n.
        guard.check_digits(L.power_digits_at_least(max(n // 3, 1), n), "factorial")
        return Quantity(Fraction(math.factorial(n)))
    n = _whole_number(op, args[0], names[0], "n")
    k = _whole_number(op, args[1], names[1], "k")
    if k > n:
        return Quantity(Fraction(0))
    j = min(k, n - k)
    if j:
        # C(n, j) >= (n/j)^j, so its digits are at least those of floor(n/j)^j.
        guard.check_digits(L.power_digits_at_least(n // j, j), "binomial coefficient")
    return Quantity(Fraction(math.comb(n, j)))


def _binomial_exact(op: str, k: int, n: int, p: Fraction, guard: L.Guard) -> Fraction:
    """P(X = k), P(X <= k) or P(X > k) for X binomial(n, p), p = a/b exactly:
    sum(C(n, i) a^i (b - a)^(n - i)) / b^n over the i the tail holds, in whole
    numbers (each term from the last by one exact multiplication and one exact
    division), summing the shorter of the two tails. Sized first by b^n."""
    a, b = p.numerator, p.denominator
    c = b - a
    if b == 1:  # p is 0 or 1: X is 0 or n for certain
        x = n if a == 1 else 0
        hit = {"binomial_pmf": k == x, "binomial_cdf": x <= k, "binomial_sf": x > k}[op]
        return Fraction(1 if hit else 0)
    exact_digits = RM.power_digits(b, n) if n else 1
    guard.check_digits(exact_digits or L.power_digits_at_least(b, n), f"probability's denominator ({b}^{n}, for p = {a}/{b})", exact_digits is not None)
    if op == "binomial_pmf":
        if not 0 <= k <= n:
            return Fraction(0)
        return Fraction(math.comb(n, k) * a**k * c ** (n - k), b**n)
    # P(X <= k): i from 0 to k.  P(X > k): i from k + 1 to n.
    lo, hi = max(0, k + 1), n  # the upper tail's terms
    if k < 0:
        upper_terms, lower_terms = n + 1, 0
    elif k >= n:
        upper_terms, lower_terms = 0, n + 1
    else:
        upper_terms, lower_terms = hi - lo + 1, k + 1
    total = b**n
    if lower_terms <= upper_terms:
        part = _binomial_sum(n, a, c, 0, lower_terms - 1, guard) if lower_terms else 0
        below = part
    else:
        part = _binomial_sum(n, a, c, lo, hi, guard) if upper_terms else 0
        below = total - part
    return Fraction(below if op == "binomial_cdf" else total - below, total)


def _binomial_sum(n: int, a: int, c: int, first: int, last: int, guard: L.Guard) -> int:
    """sum over i = first..last of C(n, i) a^i c^(n - i), in whole numbers."""
    if a == 0:
        return c**n if first == 0 else 0
    if c == 0:
        return a**n if last == n else 0
    term = math.comb(n, first) * a**first * c ** (n - first)
    total = term
    for i in range(first, last):
        if (i - first) % 64 == 63:
            guard.check_time()
        term = term * (n - i) * a // ((i + 1) * c)
        total += term
    return total


def _binomial(node: OpNode, qs: list[Quantity], guard: L.Guard) -> Quantity:
    op, names = node.op, node.args
    k = _whole_number(op, qs[0], names[0], "k, a count of successes", least=None)
    n = _whole_number(op, qs[1], names[1], "n, a number of trials")
    p = _fold(_plain(op, qs[2], names[2], "a probability, a plain number"))
    if p.rounding is None:
        if not 0 <= p.magnitude <= 1:
            raise Refusal(f'{op}: "{names[2]}" is {value_text(qs[2])}; a probability is from 0 to 1.', kind="out_of_domain")
        return Quantity(_binomial_exact(op, k, n, p.magnitude, guard))
    b = _ball(p)
    if b.hi < 0 or b.lo > 1:
        raise Refusal(f'{op}: "{names[2]}" is {value_text(qs[2])}; a probability is from 0 to 1.', kind="out_of_domain")
    if b.lo < 0 or b.hi > 1:
        raise _undecidable(f'{op}: "{names[2]}" may be outside 0 to 1 within its error bound', qs[2])
    # From a rounded p: the exact value at its written decimal, and a bound from the values the
    # polynomial takes over p's ball: P(X <= k) falls and P(X > k) rises with p, so their extremes are
    # at the ends; P(X = k) rises then falls, so its extremes are at the ends or at its peak, p = k/n.
    value = _binomial_exact(op, k, n, b.mid, guard)
    points = [b.lo, b.hi]
    if op == "binomial_pmf" and n and b.lo < Fraction(k, n) < b.hi:
        points.append(Fraction(k, n))
    error = max(abs(_binomial_exact(op, k, n, x, guard) - value) for x in points)
    if error == 0:
        return Quantity(value)
    places = _places(node, qs)  # type: ignore[arg-type]
    c = N.round_significant(value, places)
    return Quantity(c, U.PLAIN, Rounding(places, N.round_up_significant(error + abs(value - c), 2), False, _origins(qs)))


# ---------------------------------------------------------------- rounding to places, exactly


def _round_to(x: Fraction, places: int, op: str, mode: str) -> Fraction:
    step = Fraction(1, L.ten_to(places)) if places >= 0 else Fraction(L.ten_to(-places))
    s = x / step
    down = s.numerator // s.denominator  # the floor
    if op == "floor" or s.denominator == 1:
        k = down
    elif op == "ceil":
        k = down + 1
    else:
        rest = s - down
        if rest != Fraction(1, 2):
            k = down + (1 if rest > Fraction(1, 2) else 0)
        elif mode == "half_even":
            k = down if down % 2 == 0 else down + 1
        elif mode == "half_up":
            k = down + 1
        elif mode == "half_down":
            k = down
        elif mode == "half_away_from_zero":
            k = down + 1 if x > 0 else down
        else:  # half_toward_zero
            k = down if x > 0 else down + 1
    return k * step


def _rounding(node: OpNode, q: Quantity) -> Quantity:
    places = node.places if node.places is not None else 0
    mode = node.mode or "half_even"
    if q.rounding is None:
        return Quantity(_round_to(q.magnitude, places, node.op, mode), q.unit)
    b = _ball(q)
    lo, hi = _round_to(b.lo, places, node.op, mode), _round_to(b.hi, places, node.op, mode)
    if lo != hi:
        raise _undecidable(f'{node.op}: "{node.args[0]}" lies within its error bound of a rounding boundary (it could give {N.decimal_text(lo)} or {N.decimal_text(hi)})', q)
    return Quantity(lo, q.unit)  # decided: exact, and true of the true value


# ---------------------------------------------------------------- comparison


def _compare(op: str, a: Quantity, b: Quantity, names: tuple[str, ...]) -> bool:
    """Exact values compare exactly. With a rounded value, the difference is a
    ball, and the answer is given only when the whole ball decides it."""
    f = U.conversion(b.unit, a.unit, op)
    d = RM.Ball(a.magnitude - b.magnitude * f, a.error + b.error * f)
    if d.rad == 0:
        x = d.mid
        return {"eq": x == 0, "ne": x != 0, "lt": x < 0, "le": x <= 0, "gt": x > 0, "ge": x >= 0}[op]
    decided = {
        "eq": False if (d.lo > 0 or d.hi < 0) else None,
        "ne": True if (d.lo > 0 or d.hi < 0) else None,
        "lt": True if d.hi < 0 else False if d.lo >= 0 else None,
        "le": True if d.hi <= 0 else False if d.lo > 0 else None,
        "gt": True if d.lo > 0 else False if d.hi <= 0 else None,
        "ge": True if d.lo >= 0 else False if d.hi < 0 else None,
    }[op]
    if decided is not None:
        return decided
    raise _undecidable(
        f'{op} cannot decide "{names[0]}" against "{names[1]}": their written values differ by '
        f"{value_text(Quantity(d.mid, a.unit))}, and their error bounds add up to {value_text(Quantity(d.rad, a.unit))}",
        a,
        b,
    )


# ---------------------------------------------------------------- temperature readings (temperature.py)


def _corners(qs: list[Quantity], op: str) -> list[list[Fraction]]:
    """The arguments' values at the corners of their error balls that hold the
    extremes of a temperature operation. Each such operation (an exact shift,
    a difference, a comparison, min, max) moves monotonically with each of
    its arguments, so its extremes are at corners; add, min and max increase
    with all of them, so their two extremes are all-low and all-high."""
    lows, highs = [q.magnitude - q.error for q in qs], [q.magnitude + q.error for q in qs]
    if op in ("add", "min", "max"):
        return [lows, highs]
    out: list[list[Fraction]] = [[]]
    for lo, hi in zip(lows, highs, strict=True):
        out = [c + [v] for c in out for v in ((lo, hi) if lo != hi else (lo,))]
    return out


def _temperature(node: OpNode, qs: list[Quantity]) -> Value:
    """An operation on a temperature reading, by temperature.py. With a rounded
    argument, the answer at the written values carries the bound the corners
    of the arguments' error balls give, and a comparison is answered only
    when every corner gives the same answer."""
    op, names = node.op, node.args

    def at(ms: list[Fraction]) -> Any:
        return T.apply(op, [(m, q.unit) for m, q in zip(ms, qs, strict=True)], names, node.unit)

    out = at([q.magnitude for q in qs])
    if not _rounded(qs):  # type: ignore[arg-type]
        return out if isinstance(out, bool) else Quantity(*out)
    answers = [at(c) for c in _corners(qs, op)]
    if isinstance(out, bool):
        if all(a == out for a in answers):
            return out
        raise _undecidable(f'{op} cannot decide "{names[0]}" against "{names[1]}" within their error bounds', *qs)
    value, unit = out
    return _settle(value, unit, max(abs(a[0] - value) for a in answers), qs)  # type: ignore[arg-type]


# ---------------------------------------------------------------- decibels (decibels.py; dec:round-2-fixes)

DB: U.Unit = (("dB", 1),)


def _ten_to_the(node: OpNode, exponent: RM.Ball, scale: Fraction, unit: U.Unit, qs: list[Quantity], guard: L.Guard) -> Quantity:
    """scale * 10^exponent, in `unit`: exact when the exponent is a whole
    number (sized before it is computed), else correctly rounded (or, from a
    rounded exponent, rounded with its bound)."""
    places = _places(node, qs)  # type: ignore[arg-type]
    # Sized before Arb is asked, from the exponent: 10^x has about x digits.
    guard.check_rounded_size(int(abs(exponent.mid)) + int(abs(N.decade(scale))), places, "power of ten")
    out = RM.evaluate(RM.scaled(RM.pow_fn(guard), scale), [RM.Ball(Fraction(10)), exponent], places, guard)
    return _outcome(out, unit, node, qs, places)  # type: ignore[arg-type]


def _ten_log10(node: OpNode, ratio: RM.Ball, k: int, unit: U.Unit, q: Quantity, name: str, guard: L.Guard) -> Quantity:
    """k * log10(ratio), in `unit` (dB, dBm or dBW): ratio > 0."""
    s = _sign(ratio)
    if s is not None and s <= 0:
        raise Refusal(f'{node.op}: "{name}" is {value_text(q)}; a logarithm needs a ratio greater than 0.', kind="out_of_domain")
    if s is None:
        raise _undecidable(f'{node.op}: "{name}" may be 0 or less within its error bound', q)
    places = _places(node, [q])
    return _outcome(RM.evaluate(RM.scaled(RM.LOG10, Fraction(k)), [ratio], places, guard), unit, node, [q], places)


def _decibels(node: OpNode, q: Quantity, guard: L.Guard) -> Quantity:
    """db_to_ratio and ratio_to_db, told "power" (10) or "amplitude" (20)."""
    op, name = node.op, node.args[0]
    k = D.DB_FACTOR[node.kind]  # type: ignore[index]
    if op == "db_to_ratio":
        if D.level_of(q.unit):
            raise Refusal(
                f'db_to_ratio takes a gain in dB, and "{name}" is {value_text(q)}, a power level: a level is a power, not '
                "a ratio. Convert it to a power instead (convert to mW or W).",
                kind="unit_mismatch",
                units=(U.format_unit(q.unit), "dB"),
            )
        if not U.gain_in(q.unit):
            what = "a plain number" if q.unit == U.PLAIN else f"in {U.format_unit(q.unit)} ({U.describe_dimension(q.unit)})"
            raise Refusal(
                f'db_to_ratio takes a gain in dB, and "{name}" is {what}. Write its unit ("6 dB"), so that a ratio is '
                "never taken for a gain, or a gain for a ratio.",
                kind="unit_mismatch",
                units=(U.format_unit(q.unit), "dB"),
            )
        f = U.conversion(q.unit, DB, op)
        exponent = RM.Ball(q.magnitude * f / k, q.error * f / k)
        return _ten_to_the(node, exponent, Fraction(1), U.PLAIN, [q], guard)
    if U.gain_in(q.unit) or D.level_of(q.unit):
        raise Refusal(
            f'ratio_to_db takes a plain ratio, and "{name}" is already in decibels ({value_text(q)}).',
            kind="unit_mismatch",
            units=(U.format_unit(q.unit), ""),
        )
    r = _plain(op, q, name, "a ratio, a plain number (a power or an amplitude divided by one in the same unit)")
    return _ten_log10(node, _ball(r), k, DB, q, name, guard)


def _shifted(q: Quantity, to: U.Unit) -> Quantity:
    """A power level written on another level's scale (dBW to dBm: + 30), exactly."""
    off = D.offset_db(D.level_of(q.unit), D.level_of(to))  # type: ignore[arg-type]
    return Quantity(q.magnitude + off, to, q.rounding)


def _level(node: OpNode, qs: list[Quantity], guard: L.Guard) -> Value:
    """An operation on a power level in dBm or dBW (decibels.py's rules)."""
    op, names = node.op, node.args
    plan = D.plan(op, [q.unit for q in qs], names, node.unit)
    first = qs[0]
    if plan == "shift":
        assert node.unit is not None
        moved = _shifted(first, node.unit)
        return _settle(moved.magnitude, node.unit, first.error, qs)  # type: ignore[arg-type]
    if plan == "to_power":
        assert node.unit is not None
        ref = D.REFERENCE_W[D.level_of(first.unit)]  # type: ignore[index]
        exponent = RM.Ball(first.magnitude / 10, first.error / 10)
        return _ten_to_the(node, exponent, ref / U.factor(node.unit), node.unit, qs, guard)
    if plan == "to_level":
        assert node.unit is not None
        ref = D.REFERENCE_W[D.level_of(node.unit)]  # type: ignore[index]
        return _ten_log10(node, _ball(first, U.factor(first.unit) / ref), 10, node.unit, first, names[0], guard)
    if plan == "add":
        level = next(q for q in qs if D.level_of(q.unit))
        total = sum((q.magnitude * (1 if q is level else U.conversion(q.unit, DB, op)) for q in qs), Fraction(0))
        error = sum((q.error * (1 if q is level else U.conversion(q.unit, DB, op)) for q in qs), Fraction(0))
        return _settle(total, level.unit, error, qs)  # type: ignore[arg-type]
    if plan == "difference":
        b = _shifted(qs[1], first.unit)
        return _settle(first.magnitude - b.magnitude, DB, first.error + b.error, qs)  # type: ignore[arg-type]
    if plan == "level_minus_gain":
        f = U.conversion(qs[1].unit, DB, op)
        return _settle(first.magnitude - qs[1].magnitude * f, first.unit, first.error + qs[1].error * f, qs)  # type: ignore[arg-type]
    on_one_scale = [_shifted(q, first.unit) for q in qs]  # "compare": levels with levels
    if op in ("min", "max"):
        return _arithmetic(node, on_one_scale, guard)
    return _compare(op, on_one_scale[0], on_one_scale[1], names)


# ---------------------------------------------------------------- units for an empirical formula (dec:round-2-fixes)


def _units_op(node: OpNode, q: Value, guard: L.Guard) -> Quantity:
    """magnitude: a quantity's number in a named unit; with_unit: a stated unit
    put on a plain number. An empirical formula (a datasheet's fit, a
    standard's relation) works on numbers taken in stated units; these two make
    those units part of the graph and the record. Its constants are inputs the
    person or a cited document gave, each with that source (round 3, q077):
    flo2-calc cannot check where a number came from, so the skill and the
    instructions say it."""
    name = node.args[0]
    if isinstance(q, bool):
        raise Refusal(f'{node.op} takes a number, and "{name}" is {"true" if q else "false"}.', kind="type_mismatch")
    if node.op == "magnitude":
        try:
            v = _apply(replace(node, op="convert"), [q], guard)
        except Refusal as r:
            raise Refusal(
                f'magnitude reads "{name}" ({value_text(q)}) as a number of {node.unit_text} only when it measures what '
                f"{node.unit_text} measures, so the number is never taken in the wrong unit. {r.reason}",
                kind=r.kind,
                units=r.units,
            ) from None
        assert isinstance(v, Quantity)
        return Quantity(v.magnitude, U.PLAIN, v.rounding)
    p = _fold(q)
    if p.unit != U.PLAIN:
        raise Refusal(
            f'with_unit puts a stated unit on a plain number, and "{name}" is {value_text(q)} '
            f"({U.describe_dimension(q.unit)}). A unit is never replaced: use convert to change one, or magnitude to take "
            "its number in a named unit first.",
            kind="unit_mismatch",
            units=(U.format_unit(q.unit), node.unit_text or ""),
        )
    assert node.unit is not None
    return Quantity(p.magnitude, node.unit, p.rounding)


# ---------------------------------------------------------------- counting true values (dec:round-2-fixes)


def _counting(node: OpNode, args: list[Value]) -> Value:
    """count_true: how many are true, an exact whole number (add refuses
    true/false, so booleans never add as numbers). k_of_n: at least k true."""
    op, names = node.op, node.args
    if op == "count_true":
        return Quantity(Fraction(sum(_booleans(op, args, names))))
    if op == "to_number":
        return Quantity(Fraction(1 if _booleans(op, args, names)[0] else 0))
    k, votes = args[0], args[1:]
    if isinstance(k, bool):
        raise Refusal(f'k_of_n\'s first argument is k, a whole number, and "{names[0]}" is {"true" if k else "false"}.', kind="type_mismatch")
    n = len(votes)
    if k.unit != U.PLAIN or k.rounding is not None or k.magnitude.denominator != 1 or not 0 <= k.magnitude <= n:
        raise Refusal(
            f'k_of_n\'s first argument is k, an exact whole plain number from 0 to {n} (the count of true/false values '
            f'after it), and "{names[0]}" is {value_text(k)}.',
            kind="out_of_domain" if k.unit == U.PLAIN else "unit_mismatch",
        )
    return sum(_booleans(op, votes, names[1:])) >= k.magnitude


# ---------------------------------------------------------------- one node


def _apply(node: OpNode, args: list[Value], guard: L.Guard) -> Value:
    op, names = node.op, node.args
    if A.uses_arrays(op, args):
        return A.apply(node, args, guard)  # an array among the arguments, or an operator only arrays have
    family = OPS[op][0]
    if family == COUNTING:
        return _counting(node, args)
    if family == COMBINATORICS:
        return _combinatorics(node, args, guard)
    if family == UNITS_OPS:
        return _units_op(node, args[0], guard)
    if family == "logic":
        bs = _booleans(op, args, names)
        if op == "and":
            return all(bs)
        if op == "or":
            return any(bs)
        if op == "not":
            return not bs[0]
        if op == "nand":
            return not all(bs)
        if op == "nor":
            return not any(bs)
        return sum(bs) % 2 == 1  # xor
    if op in ("eq", "ne") and isinstance(args[0], bool) and isinstance(args[1], bool):
        return (args[0] == args[1]) if op == "eq" else (args[0] != args[1])
    if op in ("eq", "ne") and (isinstance(args[0], bool) != isinstance(args[1], bool)):
        raise Refusal(f"{op} compares like with like, and one of {names[0]!r}, {names[1]!r} is true/false and the other a number.", kind="type_mismatch")
    qs = _numbers(op, args, names)
    if family == DECIBELS:
        return _decibels(node, qs[0], guard)
    if family != ROUNDING and T.involved(op, [q.unit for q in qs], node.unit):
        return _temperature(node, qs)  # a temperature on degC or degF: temperature.py
    if family != ROUNDING and D.involved(op, [q.unit for q in qs], node.unit):
        return _level(node, qs, guard)  # a power level in dBm or dBW: decibels.py
    if family == "comparison":
        return _compare(op, qs[0], qs[1], names)
    if family == ARITHMETIC:
        return _arithmetic(node, qs, guard)
    if family in (FUNCTIONS, CONSTANTS):
        return _function(node, qs, guard)
    if family == TRIG:
        return _trigonometry(node, qs, guard)
    if family == STATISTICS:
        return _statistics(node, qs, guard)
    if family == ROUNDING:
        return _rounding(node, qs[0])
    raise AssertionError(f"operator {op} has no evaluation")  # pragma: no cover


def evaluate(graph: Graph, guard: L.Guard | None = None) -> Evaluation:
    """Evaluate under `guard` (by default, a fresh one with the laptop limits)."""
    guard = guard if guard is not None else L.Guard()
    ev = Evaluation(graph, guard)
    nodes = graph.by_id()
    order = evaluation_order(graph)
    for i, nid in enumerate(order):
        node = nodes[nid]
        try:
            guard.at(nid, node.op if isinstance(node, OpNode) else None, i, len(order))
            ev.order.append(nid)
            if isinstance(node, InputNode):
                if isinstance(node.value, Quantity):
                    guard.check_number(node.value.magnitude, "value")
                elif isinstance(node.value, A.Array):
                    A.check(node.value, guard, "array")
                ev.values[nid] = node.value
                continue
            value = _apply(node, [ev.values[a] for a in node.args], guard)
            if isinstance(value, Quantity):
                guard.check_number(value.magnitude)
            elif isinstance(value, A.Array):
                A.check(value, guard)
        except LimitExceeded as e:
            ev.refusal = e.refusal
            return ev
        except Refusal as r:
            ev.refusal = {"node": nid, "op": node.op, "kind": r.kind, "reason": r.reason}
            if r.units:
                ev.refusal["units"] = list(r.units)
            return ev
        except OverflowError as e:
            ev.refusal = {"node": nid, "op": node.op, "kind": "too_large", "reason": f"{node.op}: {e}."}
            return ev
        ev.values[nid] = value
    guard.past_nodes()
    return ev


STOPPED_NEXT = (
    "This passed a limit of this host, not a rule of the math: nothing is wrong with the computation. "
    "record_computation returns it as a not-yet-computed record, which flo2-calc on a machine with more room "
    "(a higher limit) completes."
)


def _entry_bytes(entry: dict[str, Any]) -> int:
    return sum(len(v) if isinstance(v, str) else len(json.dumps(v)) for v in entry.values()) + 32


def values_json(ev: Evaluation, style: Style = CURRENT) -> list[dict[str, Any]]:
    """Every value computed, in evaluation order, as replies write them. Writing
    out a large value takes time and room, so each is counted against the
    deadline and the reply budget as it is written (LimitExceeded)."""
    nodes = ev.graph.by_id()
    out = []
    for nid in ev.order:
        if nid in ev.values:
            entry = {"node": nid, **value_json(ev.values[nid], style, _unit_chosen_by_rule(nodes[nid]))}
            ev.guard.spend_reply(_entry_bytes(entry))
            out.append(entry)
    return out


def _unit_chosen_by_rule(node: Node) -> bool:
    """Whether a value's unit came from a rule of arithmetic, and so may be shown
    simpler: not an input's (as written), and not a unit the graph chose
    itself (convert's, with_unit's, an inverse trigonometric function's)."""
    return isinstance(node, OpNode) and node.op not in UNIT_OPS


def results_json(ev: Evaluation, values: list[dict[str, Any]]) -> dict[str, Any]:
    """{"result": ...}, or, when the graph names a list of results,
    {"results": [...]}: each the result node's entry in `values`."""
    by_node = {v["node"]: v for v in values}
    if ev.graph.results is not None:
        return {"results": [by_node[r] for r in ev.graph.results]}
    return {"result": by_node[ev.graph.result]}


def shown_back(ev: Evaluation, values: list[dict[str, Any]] | None, style: Style = CURRENT) -> FM.Rendering:
    """The formula and the working, from the graph and the values as written,
    in `style`'s rendering (a record of version 4 to 6 ends only a result's
    formula line with its value; version 7 and every reply end every line so)."""
    shown = {
        v["node"]: FM.Shown(v["value"], v.get("exact"), v.get("rounded"), v.get("float64"), "array" in v)
        for v in values or []
    }
    graph = ev.graph
    return FM.render(list(graph.nodes), evaluation_order(graph), graph.result_ids, shown, ev.refusal, style.every_line_valued)


WORKING_REST_REPLY = "are not shown here; record_computation keeps every one in its record"
WORKING_REST_RECORD = 'are in the record ("formula" and "working" hold every one)'


def shown_json(rendering: FM.Rendering, where_rest: str = WORKING_REST_REPLY) -> dict[str, Any]:
    """What a reply shows back: readable views of the formula and the working
    (a record holds every line and every step)."""
    return {
        "formula": FM.view_formula(rendering.formula, where_rest),
        "working": FM.view(rendering.working, rendering.shapes, where_rest),
    }


def exactness(ev: Evaluation) -> str:
    """What "exact" means in an answer: exact for these inputs, and, when any
    value is a rounded one or a float64 one, that those values are not exact."""
    rounded = any(isinstance(v, Quantity) and v.rounding is not None for v in ev.values.values())
    floats = any(isinstance(v, A.Array) and v.inexact for v in ev.values.values())
    if floats:
        return N.EXACT_BUT_ROUNDED_AND_FLOAT64 if rounded else N.EXACT_BUT_FLOAT64
    if rounded:
        return EXACT_BUT_ROUNDED
    return EXACT_FOR_THESE_INPUTS


def evaluation_json(ev: Evaluation) -> dict[str, Any]:
    """What a reply says about an evaluation: its result (or results), every
    value, and the computation shown back as a formula and numbered steps. An
    answer too large for the host's reply budget, or one whose writing passes
    the deadline, is itself stopped there: a refusal of kind exceeds_limits,
    with no values."""
    many = ev.graph.results is not None
    if ev.ok:
        try:
            values = values_json(ev)
        except LimitExceeded as e:
            return {"status": "refused", "refused": e.refusal, "result": None, "values": None, "next": STOPPED_NEXT}
        return {
            "status": "ok",
            **results_json(ev, values),
            "values": values,
            **shown_json(shown_back(ev, values)),
            "exactness": exactness(ev),
        }
    try:
        values = values_json(ev)
    except LimitExceeded:
        values = None  # the values before the stop are too large to send: the refusal says why
    answer = {"status": "refused", "refused": ev.refusal, "result": None, "values": values}
    if many:
        answer["results"] = None
    answer.update(shown_json(shown_back(ev, values)))
    if ev.stopped:
        answer["next"] = STOPPED_NEXT
    return answer
