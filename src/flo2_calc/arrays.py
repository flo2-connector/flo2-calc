"""Arrays: vectors and grids of values with one unit, exact or float64, and labelled.

req:flo2-calc-computes-over-arrays and dec:idea-how-arrays-are-computed
(option (a): two labelled modes) in design 0bee0c00b35845f6.

AN ARRAY is an input node's value written as an object, one or two
dimensions, with ONE unit for the whole array:

    {"id": "t", "value": {"array": ["0", "2", "4.5"], "unit": "s"}, "source": "..."}
    {"id": "g", "value": {"array": [["1", "2"], ["3", "4"]], "unit": "mm"}, "source": "..."}
    {"id": "ok", "value": {"array": [true, false, true]}, "source": "..."}
    {"id": "big", "value": {"file": "data/grid.csv", "unit": "mm"}, "source": "..."}

Each element is a number as text ("2.5", "1/3"), a JSON integer, or, for a
whole array, true/false. An element with a unit of its own ("2 mm") is
refused: the unit is given once, in "unit". A JSON number with a fraction
part is refused, as for a single value.

A LARGE ARRAY enters in one of two ways, and a record keeps it so that it
re-runs and its content hash covers the data:

- INLINE, up to whatever the call can carry. The record keeps it in its
  graph, element for element, so it re-runs anywhere.
- FROM A FILE, locally: {"file": "<path>"} inside the folder flo2-calc was
  started with (--root), a .csv or .txt of numbers (a row per line, the
  numbers separated by commas or spaces; one row or one column is a 1-D
  array) or a .npy file. flo2-calc reads it, and the record's graph keeps
  the path AND the sha256 of the file's bytes, so the content hash covers the
  data. Re-running reads the file again and checks its sha256: a changed file
  is a difference, a missing one leaves the record neither confirmed nor
  contradicted. Hosted (no --root), files are refused: give the array inline.

TWO MODES (dec:idea-how-arrays-are-computed).

- EXACT. An array of exact numbers stays exact through every rational
  operation (add, sub, mul, div, neg, abs, whole powers, min, max, convert,
  ceil, floor, round, the comparisons), through the reductions and through
  the statistics over data that are rational (a mean, a variance, a
  regression's slope and intercept). Element-wise logic over true/false
  arrays is exact. A root of an exact value is the rounded class: a standard
  deviation or a standard error is correctly rounded, as a single value is.
- FLOAT64. An FFT, a function of the rounded class over an array (sqrt, exp,
  ln, sin ...), an array of more than EXACT_MAX_ELEMENTS elements, and
  anything that mixes such a value in (or a rounded value into an array) are
  computed in IEEE 754 double precision, and LABELLED "float64": every
  element carries a rigorous bound on its distance from the true value, and
  the label gives the largest (`error_at_most`), how each part of it was
  found (`how`) and where float64 entered (`from`). Mixing exact and float64
  gives float64.

How each float64 bound is found:

- an exact number taken into float64: its exact rounding error;
- + - * / and conversions: each operation's IEEE rounding (at most half a
  unit in the last place, u = 2^-53) and the arguments' bounds carried
  through, with every bound computed then inflated by (1 + 2^-40) so that the
  bound's own rounding cannot make it too small;
- a function of the rounded class: each element from Arb's rigorous
  enclosure over its argument's error ball (python-flint), rounded to the
  nearest float64. So it is the same on every machine, unlike a platform's
  libm, and its bound is rigorous;
- sums and means: math.fsum, which rounds the exact sum once;
- statistics over float64 data: Arb ball arithmetic over every element's
  error ball, rounded once;
- the FFT (numpy's pocketfft): for a length that is a power of two (each axis
  of a grid), Higham's bound for the radix-2 FFT (Accuracy and Stability of
  Numerical Algorithms, 2nd ed., SIAM 2002, Theorem 24.2), doubled; for any
  other length, computed for that transform from Arb's rigorous DFT
  enclosure (FLINT's acb_dft). Either way plus the input's own error, carried
  through.

Every comparison, ceil, floor, round, argmax or argmin of a float64 value is
answered only where the bounds decide it, and refused (kind "undecidable")
otherwise, as for a rounded value.

BROADCASTING is numpy's, and strict about units: shapes combine when they are
equal, when one side is a single value, a row of n against a grid of m x n,
or a column (m x 1) against a row (n). Every array has one unit, and the
unit rules are a single value's: units that measure different things are
refused, never stripped.

COMPLEX values come only from the FFT (and its inverse): abs (the modulus),
phase, real, imag and conj take them apart; add, sub, mul, neg and div by a
real value work on them.

WRITTEN BACK, an array is {"value": a description, "array": {"shape", "kind",
"unit", "sha256", "values"}}: every element as text (an exact element
exactly, "1/3"; a float64 element as the shortest text that reads back as the
same double) when it has at most FULL_ELEMENTS elements, else only its
sha256, its first elements, and its least and greatest. The sha256 is over
the canonical text of every element, so a record of a large result still
covers its data, and re-running compares it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from flo2_calc import evaluator as E
from flo2_calc import limits as L
from flo2_calc import numbers as N
from flo2_calc import realmath as RM
from flo2_calc import temperature as T
from flo2_calc import units as U
from flo2_calc.errors import CallError, Refusal, at

EXACT_MAX_ELEMENTS = 4_096  # past this (a 64 x 64 grid), an array is carried in float64: a "large grid"
FULL_ELEMENTS = 1_024  # an array of at most this many elements is written out in full
FIRST_SHOWN = 8
MAX_ELEMENTS = 1 << 21  # any one array (2,097,152 elements), whatever the host's budget
MAX_FILE_BYTES = 256 * 1024 * 1024
DATA_SUFFIXES = (".csv", ".txt", ".npy")

U53 = 2.0**-53  # the unit roundoff of float64
TINY = 2.0**-1074  # the least subnormal
NORMAL_MIN = 2.0**-1022
INFLATE = 1.0 + 2.0**-40  # a bound computed in float64 is inflated by this, so its own rounding never makes it too small
ARB_BITS = 80
CHECK_EVERY = 1024

EXACT, BOOL, FLOAT64, COMPLEX = "exact", "bool", "float64", "complex"
_KIND = {"O": EXACT, "b": BOOL, "f": FLOAT64, "c": COMPLEX}

# What each part of a float64 bound rests on, in words (the label's "how").
HOW_TAKEN = "an exact value taken into float64: its exact rounding error to the nearest double"
HOW_LARGE = (
    f"an array of more than {EXACT_MAX_ELEMENTS:,} elements is carried in float64 (dec:idea-how-arrays-are-computed)"
)
HOW_ROUNDED_IN = "a rounded value taken into float64 with its error bound and the rounding to the nearest double"
HOW_ARITH = (
    "float64 arithmetic: each operation's IEEE 754 rounding (at most half a unit in the last place, u = 2^-53) and "
    "the arguments' bounds, carried through and inflated by (1 + 2^-40)"
)
HOW_SUM = "math.fsum: the exact sum rounded once, plus the elements' bounds"


def how_function(op: str) -> str:
    return (
        f"{op}: each element from Arb's rigorous enclosure (python-flint) over its argument's error ball, rounded to "
        "the nearest float64"
    )


def how_stats(op: str) -> str:
    return f"{op} over float64 data: Arb ball arithmetic over every element's error ball, rounded once to the nearest float64"


# ---------------------------------------------------------------- the value


@dataclass(frozen=True)
class Label:
    """How a float64 value stands for the true one."""

    origins: tuple[str, ...]  # the nodes where float64 entered
    how: tuple[str, ...]  # what each part of its bound rests on

    def plus(self, other: Label | None = None, origins: tuple[str, ...] = (), how: tuple[str, ...] = ()) -> Label:
        o = self.origins + (other.origins if other else ()) + origins
        h = self.how + (other.how if other else ()) + how
        return Label(tuple(dict.fromkeys(o)), tuple(dict.fromkeys(h)))


def label_of(*parts: Label | None, origins: tuple[str, ...] = (), how: tuple[str, ...] = ()) -> Label:
    out = Label((), ())
    for p in parts:
        if p is not None:
            out = out.plus(p)
    return out.plus(origins=origins, how=how)


@dataclass(frozen=True, eq=False)
class Array:
    """A 1-D or 2-D array with one unit. `data` is an object array of exact
    Fractions, a bool array, or a float64 or complex128 array; a float64 or
    complex value of shape () is a single float64 value (a reduction's). For
    float64 and complex, `error` bounds |computed - true| for each element, in
    the array's unit, and `label` says how."""

    data: np.ndarray
    unit: U.Unit = U.PLAIN
    error: np.ndarray | None = None
    label: Label | None = None
    norm: float | None = None  # an FFT's: a bound on the 2-norm of the whole error vector, tighter than the elements'

    @property
    def kind(self) -> str:
        return _KIND[self.data.dtype.kind]

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(self.data.shape)

    @property
    def size(self) -> int:
        return int(self.data.size)

    @property
    def inexact(self) -> bool:
        return self.kind in (FLOAT64, COMPLEX)


def floats_in(a: Any) -> Iterator[Any]:
    """A numpy array's elements as Python numbers, a chunk at a time, so a
    large array is never turned into one long list of Python objects (whose
    memory Python keeps once it has had it)."""
    flat = np.asarray(a).ravel()
    for k in range(0, flat.size, CHECK_EVERY * 4):
        yield from flat[k:k + CHECK_EVERY * 4].tolist()


def _frozen(a: np.ndarray) -> np.ndarray:
    a.flags.writeable = False
    return a


def exact_array(values: list[Fraction], shape: tuple[int, ...], unit: U.Unit = U.PLAIN) -> Array:
    data = np.empty(len(values), dtype=object)
    data[:] = values
    return Array(_frozen(data.reshape(shape)), unit)


def bool_array(values: Any, shape: tuple[int, ...]) -> Array:
    return Array(_frozen(np.asarray(values, dtype=bool).reshape(shape)))


def float_array(v: Any, e: Any, unit: U.Unit, label: Label, norm: float | None = None) -> Array:
    v = np.array(v, order="C")  # a copy, and a 0-d value stays 0-d
    e = np.array(np.broadcast_to(np.asarray(e, dtype=np.float64), v.shape), order="C")
    if v.dtype.kind == "f":
        v = np.where(v == 0, 0.0, v.astype(np.float64))  # no negative zero in a result
    elif v.dtype.kind == "c":
        v = v.astype(np.complex128) + 0.0  # -0.0 + 0.0 is +0.0, in both parts
    return Array(_frozen(np.asarray(v)), unit, _frozen(e), label, norm)


def shape_text(shape: tuple[int, ...]) -> str:
    return "x".join(str(n) for n in shape) if shape else "a single value"


def index_text(i: int, shape: tuple[int, ...]) -> str:
    if len(shape) <= 1:
        return f"[{i}]"
    r, c = divmod(i, shape[1])
    return f"[{r}, {c}]"


def _element_refusal(r: Refusal, i: int, shape: tuple[int, ...]) -> Refusal:
    return Refusal(f"at element {index_text(i, shape)}: {r.reason}", kind=r.kind, units=r.units)


# ---------------------------------------------------------------- floats, exactly


def float_up(q: Fraction) -> float:
    """The least float64 >= q (q >= 0)."""
    if q <= 0:
        return 0.0
    try:
        f = q.numerator / q.denominator  # CPython's int division is correctly rounded
    except OverflowError:
        return math.inf
    if Fraction(f) < q:
        f = math.nextafter(f, math.inf)
    return f


def to_float(q: Fraction) -> tuple[float, float]:
    """(the nearest float64 to q, a bound on its distance from q). Raises
    OverflowError past float64's range."""
    f = q.numerator / q.denominator
    if math.isinf(f):
        raise OverflowError
    exact = Fraction(f)
    return f, (0.0 if exact == q else float_up(abs(exact - q)))


def _too_large(op: str, what: str = "a value") -> Refusal:
    return Refusal(
        f"{op}: {what} passes float64's range (about 1.8e308), so it cannot be carried in float64.",
        kind="too_large",
    )


def floats_of(xs: np.ndarray, op: str, guard: L.Guard) -> tuple[np.ndarray, np.ndarray]:
    """An object array of exact Fractions as float64, with each element's
    exact rounding error (0 where the double is the number itself)."""
    flat = xs.ravel()
    v = np.empty(flat.size, dtype=np.float64)
    e = np.zeros(flat.size, dtype=np.float64)
    for i, q in enumerate(flat):
        if i % CHECK_EVERY == 0:
            guard.check_time()
        try:
            v[i], e[i] = to_float(q)
        except OverflowError:
            raise _element_refusal(_too_large(op), i, xs.shape) from None
    return v.reshape(xs.shape), e.reshape(xs.shape)


def finite_or_refuse(op: str, *arrays: np.ndarray) -> None:
    for a in arrays:
        if not np.all(np.isfinite(a)):
            raise _too_large(op, "a result")


def _cabs(re_: np.ndarray, im_: np.ndarray) -> np.ndarray:
    """|re + i im| with the basic IEEE operations only (the same on every
    machine), scaled so that it neither overflows nor underflows early."""
    a, b = np.abs(re_), np.abs(im_)
    big, small = np.maximum(a, b), np.minimum(a, b)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(big > 0, small / np.where(big > 0, big, 1.0), 0.0)
    return big * np.sqrt(1.0 + r * r)


CABS_REL = 4 * U53  # _cabs's own relative rounding: a division, a square, an addition, a root, a product


# ---------------------------------------------------------------- reading an array


_ELEMENT = re.compile(rf"^\s*({N._FRACTION}|{N._DECIMAL})\s*$")


def _element(raw: Any, path: str) -> Fraction | bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        if abs(raw) >= L.ten_to(N.MAX_NUMBER_TEXT):
            raise CallError(path, f"a number is at most {N.MAX_NUMBER_TEXT} digits; this JSON integer is longer.")
        return Fraction(raw)
    if isinstance(raw, float):
        if raw.is_integer() and abs(raw) < 2**53:
            return Fraction(int(raw))
        raise CallError(
            path,
            f"{raw!r} arrived as a JSON number with a fraction part, which reaches flo2-calc as a binary "
            f'floating-point number whose exact value is already lost. Write it as text: "{raw!r}".',
        )
    if not isinstance(raw, str):
        raise CallError(path, 'an array element is a number as text ("2.5", "1/3"), a JSON integer, or true/false.')
    t = raw.strip()
    if t in ("true", "false"):
        return t == "true"
    m = _ELEMENT.match(t)
    if not m:
        rest = N.NUMBER_THEN_REST.match(t)
        if rest and rest.group(2).strip() and not N.looks_like_expression(rest.group(2)):
            raise CallError(
                path,
                f'"{raw}" carries a unit of its own. An array has ONE unit, given once beside it: '
                '{"array": ["1.4", "2"], "unit": "mm"}.',
            )
        raise CallError(path, f'"{raw}" is not a number: an array element is one number as text ("2.5", "1/3"), with no unit and no arithmetic.')
    try:
        return N.parse_number(m.group(1))
    except ValueError as e:
        raise CallError(path, str(e)) from None


def _rows(raw: Any, path: str) -> tuple[list[Any], tuple[int, ...]]:
    """The elements in row-major order, and the shape."""
    if not isinstance(raw, list) or not raw:
        raise CallError(path, "an array is a non-empty list of elements, or a list of rows (each a list) for a grid.")
    if all(isinstance(r, list) for r in raw):
        n = len(raw[0])
        if n == 0:
            raise CallError(at(path, 0), "a grid's row has at least one element.")
        for i, r in enumerate(raw):
            if len(r) != n:
                raise CallError(at(path, i), f"every row of a grid has the same length; row 0 has {n}, row {i} has {len(r)}.")
            if any(isinstance(x, list) for x in r):
                raise CallError(at(path, i), "an array has one or two dimensions, no more.")
        return [x for r in raw for x in r], (len(raw), n)
    if any(isinstance(r, list) for r in raw):
        raise CallError(path, "an array is all elements (a vector) or all rows (a grid), not a mix.")
    return list(raw), (len(raw),)


def _unit_of(obj: dict[str, Any], path: str) -> tuple[str | None, U.Unit]:
    if "unit" not in obj:
        return None, U.PLAIN
    text = obj["unit"]
    if not isinstance(text, str):
        raise CallError(at(path, "unit"), 'an array\'s "unit" is text, as reflow2 spells it ("mm"; "" for plain numbers).')
    try:
        return text, U.parse_unit(text)
    except ValueError as e:
        raise CallError(at(path, "unit"), str(e)) from None


def _build(items: list[Any], shape: tuple[int, ...], unit: U.Unit, path: str, where: Callable[[int], str]) -> Array:
    """An array from its elements as given (text, JSON numbers, true/false).
    Past EXACT_MAX_ELEMENTS each number goes straight into float64, so no
    large list of exact numbers is ever held."""
    n = len(items)
    if n > MAX_ELEMENTS:
        raise CallError(path, f"an array has at most {MAX_ELEMENTS:,} elements; this one has {n:,}.")
    first = _element(items[0], where(0))
    mixed = "an array is all numbers or all true/false, not a mix."
    if isinstance(first, bool):
        if unit != U.PLAIN:
            raise CallError(path, "a true/false array has no unit.")
        flags = [first]
        for i in range(1, n):
            x = _element(items[i], where(i))
            if not isinstance(x, bool):
                raise CallError(where(i), mixed)
            flags.append(x)
        return bool_array(flags, shape)
    if n <= EXACT_MAX_ELEMENTS:
        elements = [first]
        for i in range(1, n):
            x = _element(items[i], where(i))
            if isinstance(x, bool):
                raise CallError(where(i), mixed)
            elements.append(x)
        return exact_array(elements, shape, unit)
    values = np.empty(n, dtype=np.float64)
    errors = np.zeros(n, dtype=np.float64)
    for i in range(n):
        x = first if i == 0 else _element(items[i], where(i))
        if isinstance(x, bool):
            raise CallError(where(i), mixed)
        try:
            values[i], errors[i] = to_float(x)
        except OverflowError:
            raise CallError(where(i), "this number passes float64's range (about 1.8e308), and an array this large is carried in float64.") from None
    return float_array(values.reshape(shape), errors.reshape(shape), unit, Label((), (HOW_LARGE, HOW_TAKEN)))


def parse_input(raw: dict[str, Any], path: str, data_root: Path | None) -> tuple[dict[str, Any], Array]:
    """(the value as a record keeps it, the array) from an input's object value."""
    keys = set(raw)
    if keys - {"array", "file", "unit", "sha256"} or ("array" in raw) == ("file" in raw):
        raise CallError(
            path,
            'an array value is {"array": [...], "unit": "<unit>"} (inline), or {"file": "<path>", "unit": "<unit>"} '
            "(a .csv, .txt or .npy file inside the folder flo2-calc was started with).",
        )
    unit_text, unit = _unit_of(raw, path)
    if "array" in raw:
        if "sha256" in raw:
            raise CallError(at(path, "sha256"), 'only a file array takes "sha256".')
        items, shape = _rows(raw["array"], at(path, "array"))
        field = at(path, "array")

        def where(i: int) -> str:
            return at(field, i) if len(shape) == 1 else f"{field}[{i // shape[1]}][{i % shape[1]}]"

        array = _build(items, shape, unit, field, where)
        texts = [_kept_text(x) for x in items]
        kept: dict[str, Any] = {"array": _nested(texts, shape)}
        if unit_text is not None:
            kept["unit"] = unit_text
        return kept, array
    target, data = _read_file(data_root, raw["file"], at(path, "file"))
    digest = hashlib.sha256(data).hexdigest()
    if "sha256" in raw and raw["sha256"] != digest:
        raise CallError(
            at(path, "sha256"),
            f'the file "{raw["file"]}" now has sha256 {digest}, not the {raw["sha256"]!r} given: it is not the data '
            "this computation was made with.",
        )
    array = _parse_file(target, data, unit, at(path, "file"))
    kept = {"file": raw["file"], "sha256": digest}
    if unit_text is not None:
        kept["unit"] = unit_text
    return kept, array


def _kept_text(x: Any) -> str:
    """An element as the record's graph keeps it: as text, as given."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float):
        return str(int(x))  # only a whole-valued float gets this far
    return str(x)


class DataUnavailable(CallError):
    """A data file the graph names is not where this flo2-calc may read it."""


def _read_file(root: Path | None, requested: Any, field: str) -> tuple[Path, bytes]:
    if not isinstance(requested, str) or not requested.strip():
        raise CallError(field, "give the data file's path, relative to the folder flo2-calc was started with.")
    if root is None:
        raise DataUnavailable(
            field,
            "this flo2-calc was started with no folder it may read files from (no --root), as it is when hosted on "
            "flo2.io, so an array cannot come from a file here. Give it inline, as {\"array\": [...]}.",
        )
    if not requested.endswith(DATA_SUFFIXES):
        raise CallError(field, f'a data file is a {", ".join(DATA_SUFFIXES)} file; "{requested}" is not.')
    target = Path(os.path.normpath(root / requested))
    if not (target == root or target.is_relative_to(root)) or not target.resolve().is_relative_to(root):
        raise CallError(field, f'"{requested}" is outside the folder flo2-calc may read ({root}).')
    if not target.is_file():
        raise DataUnavailable(field, f'there is no data file "{requested}" in the folder flo2-calc may read.')
    if target.stat().st_size > MAX_FILE_BYTES:
        raise CallError(field, f'"{requested}" is larger than {MAX_FILE_BYTES:,} bytes, the most flo2-calc reads.')
    return target, target.read_bytes()


def _parse_file(target: Path, data: bytes, unit: U.Unit, field: str) -> Array:
    if target.suffix == ".npy":
        import io

        try:
            a = np.load(io.BytesIO(data), allow_pickle=False)
        except Exception as e:  # noqa: BLE001 - any unreadable file is said as one
            raise CallError(field, f"this is not a .npy file flo2-calc can read ({type(e).__name__}: {e}).") from None
        if a.ndim not in (1, 2) or a.size == 0:
            raise CallError(field, f"an array has one or two dimensions and at least one element; this .npy has shape {a.shape}.")
        if a.size > MAX_ELEMENTS:
            raise CallError(field, f"an array has at most {MAX_ELEMENTS:,} elements; this one has {a.size:,}.")
        k = a.dtype.kind
        if k == "b":
            if unit != U.PLAIN:
                raise CallError(field, "a true/false array has no unit.")
            return bool_array(a, a.shape)
        if k in "iu":
            items = [int(x) for x in a.ravel().tolist()]
            return _build(items, a.shape, unit, field, lambda i: f"{field} (element {i})")
        if k == "f":
            v = a.astype(np.float64)
            if not np.all(np.isfinite(v)):
                raise CallError(field, "this .npy holds an infinity or a NaN, which is not a number.")
            return float_array(v, np.zeros(v.shape), unit, Label((), (f"float64 values as given in {target.name} (exact binary numbers)",)))
        raise CallError(field, f"this .npy holds {a.dtype}, not numbers or true/false.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise CallError(field, "this data file is not UTF-8 text.") from None
    rows: list[list[str]] = []
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            rows.append([t for t in re.split(r"[,\s;]+", s) if t])
    if not rows:
        raise CallError(field, "this data file holds no numbers.")
    width = len(rows[0])
    for i, r in enumerate(rows):
        if len(r) != width:
            raise CallError(field, f"every row of a data file has the same number of values; row 1 has {width}, row {i + 1} has {len(r)}.")
    shape = (len(rows) * width,) if (len(rows) == 1 or width == 1) else (len(rows), width)
    items = [t for r in rows for t in r]
    del rows
    try:
        return _build(items, shape, unit, field, lambda i: f"row {i // width + 1}, value {i % width + 1}")
    except CallError as e:
        raise CallError(field, f"{e.path}: {e.problem}" if e.path != field else e.problem) from None


# ---------------------------------------------------------------- writing an array back


def element_texts(a: Array) -> list[str]:
    """Every element as text, row-major: exact exactly (a decimal that ends,
    else "p/q"), true/false, or a double as the shortest text that reads back
    as it (Python's repr)."""
    flat = a.data.ravel()
    k = a.kind
    if k == EXACT:
        out = []
        for q in flat:
            text, exact = N.format_number(q)
            out.append(exact if exact is not None else text)
        return out
    if k == BOOL:
        return ["true" if x else "false" for x in flat.tolist()]
    if k == FLOAT64:
        return [repr(x) for x in flat.tolist()]
    return [complex_text(z) for z in flat.tolist()]


def complex_text(z: complex) -> str:
    re_, im_ = z.real + 0.0, z.imag + 0.0
    sign = "-" if math.copysign(1.0, im_) < 0 and im_ != 0 else "+"
    return f"{re_!r}{sign}{abs(im_)!r}j"


def _nested(texts: list[str], shape: tuple[int, ...]) -> list[Any]:
    if len(shape) == 1:
        return texts
    return [texts[r * shape[1]:(r + 1) * shape[1]] for r in range(shape[0])]


def digest(a: Array, texts: list[str] | None = None) -> str:
    """sha256 over the canonical JSON {"shape", "kind", "unit", "values"}
    (every element's text, row-major, no spaces), written a chunk at a time
    so a large array's texts are never all held at once."""
    h = hashlib.sha256()
    head = json.dumps({"shape": list(a.shape), "kind": a.kind, "unit": U.format_unit(a.unit)}, separators=(",", ":"), ensure_ascii=False)
    h.update((head[:-1] + ',"values":[').encode("utf-8"))
    chunk = 4096
    flat = a.data.ravel()
    for start in range(0, max(1, flat.size), chunk):
        part = texts[start:start + chunk] if texts is not None else element_texts(Array(flat[start:start + chunk]))
        # An element's text is digits, a sign, ".", "e", "/", "j" or true/false: JSON writes it as itself in quotes.
        h.update(((',' if start else '') + '"' + '","'.join(part) + '"').encode("utf-8"))
    h.update(b"]}")
    return "sha256:" + h.hexdigest()


def error_at_most(a: Array) -> Fraction:
    assert a.error is not None
    m = float(np.max(a.error)) if a.error.size else 0.0
    return N.round_up_significant(Fraction(m), 2) if m > 0 else Fraction(0)


def label_json(a: Array) -> dict[str, Any]:
    unit = U.format_unit(a.unit)
    bound = N.decimal_text(error_at_most(a))
    assert a.label is not None
    return {
        "error_at_most": f"{bound} {unit}" if unit else bound,
        "how": list(a.label.how),
        "from": list(a.label.origins),
    }


def describe(a: Array) -> str:
    unit = U.format_unit(a.unit)
    kind = {EXACT: "exact", BOOL: "true/false", FLOAT64: "float64", COMPLEX: "complex, float64"}[a.kind]
    return f"array {shape_text(a.shape)} ({kind}{', ' + unit if unit else ''})"


def value_json(a: Array, elements: bool = True) -> dict[str, Any]:
    """An array as replies and records write it (see the module's note). A
    float64 value of shape () is written like a single value, with its label."""
    unit = U.format_unit(a.unit)
    if a.shape == ():
        z = a.data.item()
        text = complex_text(z) if a.kind == COMPLEX else repr(float(z) + 0.0)
        return {"value": f"{text} {unit}" if unit else text, "float64": label_json(a)}
    texts = element_texts(a) if a.size <= FULL_ELEMENTS else None
    body: dict[str, Any] = {"shape": list(a.shape), "kind": a.kind}
    if a.kind != BOOL:
        body["unit"] = unit
    body["sha256"] = digest(a, texts)
    if elements:
        if texts is not None:
            body["values"] = _nested(texts, a.shape)
        else:
            body["first"] = element_texts(Array(a.data.ravel()[:FIRST_SHOWN]))
            if a.kind in (EXACT, FLOAT64):
                lo, hi = a.data.min(), a.data.max()
                body["least"] = element_texts(Array(np.asarray([lo], dtype=a.data.dtype)))[0]
                body["greatest"] = element_texts(Array(np.asarray([hi], dtype=a.data.dtype)))[0]
    out: dict[str, Any] = {"value": describe(a), "array": body}
    if a.inexact:
        out["float64"] = label_json(a)
    return out


# ---------------------------------------------------------------- the host's budget for arrays


def nbytes(a: Array) -> int:
    """About what an array holds in memory: a float64 element and its bound
    16 bytes, a complex one 24, a true/false 1, and an exact one its object
    and its digits."""
    if a.kind == EXACT:
        return sum(112 + (q.numerator.bit_length() + q.denominator.bit_length()) // 8 for q in a.data.ravel())
    if a.kind == BOOL:
        return a.size
    return a.data.nbytes + (a.error.nbytes if a.error is not None else 0)


BYTES_PER = {EXACT: 128, BOOL: 1, FLOAT64: 16, COMPLEX: 24}
ARB_CHECK_BYTES = 128  # an Arb complex ball (python-flint's acb) and its place in a list


def make_room(guard: L.Guard, shape: tuple[int, ...], kind: str, what: str = "result") -> None:
    """BEFORE an array is made: refuse one the host's budget cannot hold."""
    n = math.prod(shape)
    guard.check_array_room(n * BYTES_PER[kind], n, what)


def check(a: Array, guard: L.Guard, what: str = "result") -> None:
    """After an array is made: every exact element within the digits budget,
    and its bytes counted against the call's budget for arrays."""
    if a.kind == EXACT:
        for i, q in enumerate(a.data.ravel()):
            guard.check_number(q, f"{what}'s element {index_text(i, a.shape)}")
    guard.spend_array(nbytes(a), a.size, what)


# ---------------------------------------------------------------- operands


@dataclass
class _Arg:
    """One argument of an array operation, in the forms the operation needs."""

    name: str
    kind: str  # exact | bool | float64 | complex
    unit: U.Unit
    shape: tuple[int, ...]
    exact: np.ndarray | None = None  # exact: object array of Fractions
    v: np.ndarray | None = None  # float64 / complex values (made from exact on demand)
    e: np.ndarray | None = None
    label: Label | None = None
    taken: str | None = None  # how it was taken into float64, if it was

    def floats(self, op: str, guard: L.Guard) -> tuple[np.ndarray, np.ndarray]:
        if self.v is None:
            assert self.exact is not None
            self.v, self.e = floats_of(self.exact, op, guard)
            self.taken = HOW_TAKEN
        return self.v, self.e  # type: ignore[return-value]


def operand(value: Any, name: str) -> _Arg:
    if isinstance(value, bool):
        return _Arg(name, BOOL, U.PLAIN, (), exact=np.asarray(value))
    if isinstance(value, E.Quantity):
        if value.rounding is None:
            q = np.empty((), dtype=object)
            q[()] = value.magnitude
            return _Arg(name, EXACT, value.unit, (), exact=q)
        f = value.magnitude.numerator / value.magnitude.denominator
        if math.isinf(f):
            raise _too_large("an array operation", f'"{name}"')
        err = float_up(value.error + abs(value.magnitude - Fraction(f)))
        lab = Label(value.rounding.origins, (HOW_ROUNDED_IN,))
        return _Arg(name, FLOAT64, value.unit, (), v=np.asarray(f), e=np.asarray(err), label=lab, taken=HOW_ROUNDED_IN)
    assert isinstance(value, Array)
    if value.kind == EXACT:
        return _Arg(name, EXACT, value.unit, value.shape, exact=value.data)
    if value.kind == BOOL:
        return _Arg(name, BOOL, U.PLAIN, value.shape, exact=value.data)
    return _Arg(name, value.kind, value.unit, value.shape, v=value.data, e=value.error, label=value.label)


def broadcast_shape(op: str, args: list[_Arg]) -> tuple[int, ...]:
    try:
        return tuple(np.broadcast_shapes(*[a.shape for a in args]))
    except ValueError:
        shown = ", ".join(f'"{a.name}" is {shape_text(a.shape)}' for a in args if a.shape)
        raise Refusal(
            f"{op}: the shapes do not fit together ({shown}). Arrays combine element by element when their shapes are "
            "equal, or one side is a single value, or a row of n meets a grid of m x n, or a column (m x 1) meets a "
            "row (n); use column or transpose to say which way.",
            kind="shape_mismatch",
        ) from None


def _result(values: list[Any], shape: tuple[int, ...], unit: U.Unit, node: Any, guard: L.Guard) -> Any:
    """An exact result: an array, or (shape ()) a single value. An array of
    more than EXACT_MAX_ELEMENTS elements is carried in float64, labelled."""
    if shape == ():
        v = values[0]
        return v if isinstance(v, bool) else E.Quantity(v, unit)
    if values and isinstance(values[0], (bool, np.bool_)):
        return bool_array(values, shape)
    if len(values) > EXACT_MAX_ELEMENTS:
        xs = np.empty(len(values), dtype=object)
        xs[:] = values
        v, e = floats_of(xs.reshape(shape), node.op, guard)
        return float_array(v, e, unit, Label((node.id,), (HOW_LARGE, HOW_TAKEN)))
    return exact_array(values, shape, unit)


def _flat(a: _Arg, shape: tuple[int, ...]) -> Any:
    assert a.exact is not None
    return np.broadcast_to(a.exact, shape).flat


# ---------------------------------------------------------------- the operators that only arrays have

REDUCTIONS = ("sum", "product", "mean", "min", "max", "count_true", "any", "all", "argmin", "argmax")
DATA_STATS = ("variance_sample", "variance_population", "sd_sample", "sd_population")
FITS = ("fit_slope", "fit_intercept", "fit_slope_se", "fit_intercept_se", "fit_residual_se")
TRANSFORMS = ("fft", "ifft", "fft2", "ifft2")
COMPLEX_PARTS = ("phase", "real", "imag", "conj")
SHAPING = ("linspace", "column", "transpose", "element")
ARRAY_ONLY = frozenset(REDUCTIONS + DATA_STATS + FITS + TRANSFORMS + COMPLEX_PARTS + SHAPING) - {"min", "max"}

# Element-wise operators whose result is rational in rational arguments: exact on exact arrays.
RATIONAL = frozenset({"add", "sub", "mul", "div", "neg", "abs", "pow", "min", "max", "convert", "ceil", "floor", "round",
                      "eq", "ne", "lt", "le", "gt", "ge"})


def uses_arrays(op: str, args: list[Any]) -> bool:
    """Whether an operation goes to this module: an array among its
    arguments, or an operator only arrays have."""
    return op in ARRAY_ONLY or any(isinstance(a, Array) for a in args) or (op in ("min", "max") and len(args) == 1)


def apply(node: Any, values: list[Any], guard: L.Guard) -> Any:
    op = node.op
    if op in REDUCTIONS and (op not in ("min", "max") or len(values) == 1):
        return _reduce(node, values, guard)
    if op in DATA_STATS:
        return _data_stats(node, values, guard)
    if op in FITS:
        return _fit(node, values, guard)
    if op in TRANSFORMS:
        return _transform(node, values, guard)
    if op in COMPLEX_PARTS:
        return _complex_part(node, values, guard)
    if op in SHAPING:
        return _shaping(node, values, guard)
    return _elementwise(node, values, guard)


# ---------------------------------------------------------------- element-wise


def _elementwise(node: Any, values: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    family = E.OPS[op][0]
    args = [operand(v, n) for v, n in zip(values, names, strict=True)]
    shape = broadcast_shape(op, args)
    if family == "logic" or (op in ("eq", "ne") and all(a.kind == BOOL for a in args)):
        return _logic(node, args, shape, guard)
    for a in args:
        if a.kind == BOOL:
            if op in ("eq", "ne"):
                raise Refusal(f"{op} compares like with like, and one of {names[0]!r}, {names[1]!r} is true/false and the other a number.", kind="type_mismatch")
            raise Refusal(f'{op} takes numbers, and "{a.name}" is true/false.', kind="type_mismatch")
    if any(a.kind == COMPLEX for a in args):
        return _complex_elementwise(node, args, shape, guard)
    exact_args = all(a.kind == EXACT for a in args)
    if exact_args and op in RATIONAL and _rational_here(node, args) and math.prod(shape) <= EXACT_MAX_ELEMENTS:
        make_room(guard, shape, EXACT)
        return _exact_elementwise(node, args, shape, guard)
    make_room(guard, shape, FLOAT64)
    large = exact_args and op in RATIONAL and _rational_here(node, args)  # exact, but too many elements to stay so
    out = _float_elementwise(node, args, shape, guard)
    if large and isinstance(out, Array) and out.label is not None:
        out = Array(out.data, out.unit, out.error, out.label.plus(how=(HOW_LARGE,)), out.norm)
    return out


def _rational_here(node: Any, args: list[_Arg]) -> bool:
    """A rational operator stays exact unless it is a non-whole power or a
    deg-rad conversion (both irrational in general)."""
    if node.op == "pow":
        ex = args[1]
        return ex.kind == EXACT and all(q.denominator == 1 for q in ex.exact.ravel())  # type: ignore[union-attr]
    if node.op == "convert" and not T.involved("convert", [args[0].unit], node.unit):
        return _plain_conversion(args[0].unit, node.unit)
    return True


def _logic(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> Any:
    op = node.op
    for a in args:
        if a.kind != BOOL:
            raise Refusal(f'{op} takes true/false values, and "{a.name}" is {"an array of numbers" if a.shape else "a number"}.', kind="type_mismatch")
    make_room(guard, shape, BOOL)
    xs = [np.broadcast_to(np.asarray(a.exact, dtype=bool), shape) for a in args]
    if op == "and":
        out = np.logical_and.reduce(xs)
    elif op == "or":
        out = np.logical_or.reduce(xs)
    elif op == "not":
        out = np.logical_not(xs[0])
    elif op == "nand":
        out = ~np.logical_and.reduce(xs)
    elif op == "nor":
        out = ~np.logical_or.reduce(xs)
    elif op == "xor":
        out = np.logical_xor.reduce(xs)
    elif op == "eq":
        out = xs[0] == xs[1]
    else:
        out = xs[0] != xs[1]
    out = np.asarray(out)
    if shape == ():
        return bool(out)
    return bool_array(out, shape)


def _temperature_elementwise(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> Any:
    """An operation on temperature readings (degC, degF), element by element
    through temperature.py, exactly as for single values."""
    out: list[Any] = []
    unit: U.Unit | None = None
    for i, elems in enumerate(zip(*(_flat(a, shape) for a in args))):
        qs = [E.Quantity(m, a.unit) for m, a in zip(elems, args, strict=True)]
        try:
            r = E._apply(node, qs, guard)
        except Refusal as x:
            raise _element_refusal(x, i, shape) from None
        if isinstance(r, E.Quantity):
            if unit is not None and r.unit != unit:
                raise Refusal(f"{node.op}: the elements' results came out in different units ({U.format_unit(unit)}, {U.format_unit(r.unit)}); an array has one unit.", kind="unit_mismatch")
            unit = r.unit
            out.append(r.magnitude)
        else:
            out.append(r)
    return _result(out, shape, unit or U.PLAIN, node, guard)


def _exact_elementwise(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    units = [a.unit for a in args]
    if E.OPS[op][0] != E.ROUNDING and T.involved(op, units, node.unit):
        return _temperature_elementwise(node, args, shape, guard)
    flats = [_flat(a, shape) for a in args]
    out: list[Any] = []
    unit = units[0]

    def each(fn: Callable[..., Any], what: str = "result") -> None:
        for i, elems in enumerate(zip(*flats)):
            try:
                r = fn(*elems)
                if not isinstance(r, bool):
                    guard.check_number(r, f"{what} at element {index_text(i, shape)}")
            except Refusal as x:
                raise _element_refusal(x, i, shape) from None
            out.append(r)

    if op in ("add", "sub", "min", "max") or E.OPS[op][0] == "comparison":
        fs = [Fraction(1)] + [U.conversion(u, units[0], op) for u in units[1:]]
        if op == "add":
            each(lambda *ms: sum((m * f for m, f in zip(ms, fs, strict=True)), Fraction(0)))
        elif op == "sub":
            each(lambda a, b: a - b * fs[1])
        elif op in ("min", "max"):
            pick = min if op == "min" else max
            each(lambda *ms: pick(m * f for m, f in zip(ms, fs, strict=True)))
        else:
            f = fs[1]
            cmp = {"eq": lambda a, b: a == b * f, "ne": lambda a, b: a != b * f, "lt": lambda a, b: a < b * f,
                   "le": lambda a, b: a <= b * f, "gt": lambda a, b: a > b * f, "ge": lambda a, b: a >= b * f}[op]
            each(lambda a, b: bool(cmp(a, b)))
            unit = U.PLAIN
    elif op == "mul":
        scale = Fraction(1)
        for u in units[1:]:
            unit, s = U.multiply(unit, u)
            scale *= s

        def product(*ms: Fraction) -> Fraction:
            p = ms[0]
            for m in ms[1:]:
                p = p * m
            return p * scale

        each(product)
    elif op == "div":
        unit, scale = U.multiply(units[0], U.invert(units[1]))

        def divide(a: Fraction, b: Fraction) -> Fraction:
            if b == 0:
                raise Refusal(f'div: "{names[1]}" is zero there, and division by zero has no value.', kind="division_by_zero")
            return a / b * scale

        each(divide)
    elif op in ("neg", "abs"):
        each((lambda a: -a) if op == "neg" else abs)
    elif op == "convert":
        f = U.conversion(units[0], node.unit, "convert")
        unit = node.unit
        each(lambda a: a * f)
    elif op in ("ceil", "floor", "round"):
        places = node.places if node.places is not None else 0
        mode = node.mode or "half_even"
        each(lambda a: E._round_to(a, places, op, mode))
    elif op == "pow":
        unit = _exact_pow(node, args, shape, guard, out)
    else:  # pragma: no cover
        raise AssertionError(op)
    return _result(out, shape, unit, node, guard)


def _exponent_plain(node: Any, ex: _Arg) -> None:
    if ex.unit != U.PLAIN:
        raise Refusal(f'pow: the exponent "{node.args[1]}" is in {U.format_unit(ex.unit)}; it must be a plain number.', kind="bad_exponent")


def _one_exponent(node: Any, base_unit: U.Unit, ex: _Arg) -> None:
    """One unit per array: a base with a unit takes one exponent for all its elements."""
    if base_unit != U.PLAIN and ex.shape:
        values = set(ex.exact.ravel().tolist()) if ex.exact is not None else set(np.asarray(ex.v).ravel().tolist())
        if len(values) > 1:
            raise Refusal(
                f'pow: "{node.args[0]}" is in {U.format_unit(base_unit)} and the exponents "{node.args[1]}" differ, so the '
                "elements' units would differ, and an array has one unit. Raise a plain array, or use one exponent.",
                kind="unit_mismatch",
                units=(U.format_unit(base_unit), ""),
            )


def _exact_pow(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard, out: list[Any]) -> U.Unit:
    base, ex = args
    _exponent_plain(node, ex)
    _one_exponent(node, base.unit, ex)
    first_n = int(next(iter(ex.exact.ravel())))  # type: ignore[union-attr]
    unit, scale = U.power(base.unit, first_n)
    # As for a single value: a folded "%" is folded into the base first (m^n (1/100)^(k n) is (m / 100^k)^n).
    folded = Fraction(1, 100) ** dict(base.unit)[U.PERCENT] if scale != 1 else Fraction(1)
    for i, (b, e) in enumerate(zip(_flat(base, shape), _flat(ex, shape))):
        n = int(e)
        try:
            if abs(n) > E.MAX_POWER_ARG:
                raise Refusal(f"pow: an exponent is at most {E.MAX_POWER_ARG} either way; this one is {n}.", kind="too_large")
            if b == 0 and n < 0:
                raise Refusal(f'pow: "{node.args[0]}" is zero there, and a negative power of zero divides by zero.', kind="division_by_zero")
            if b == 0 and n == 0:
                raise Refusal("pow: zero to the power zero has no single agreed value, so flo2-calc does not pick one.", kind="undefined")
            x = b * folded
            guard.check_power(x, n)
            r = x**n
            guard.check_number(r, f"power at element {index_text(i, shape)}")
        except Refusal as r_:
            raise _element_refusal(r_, i, shape) from None
        out.append(r)
    return unit


# ---------------------------------------------------------------- element-wise in float64


def _mul_err(a: np.ndarray, ea: np.ndarray, b: np.ndarray, eb: np.ndarray, v: np.ndarray) -> np.ndarray:
    e = np.abs(a) * eb + np.abs(b) * ea + ea * eb + U53 * np.abs(v)
    e = e + np.where((np.abs(v) < NORMAL_MIN) & (a != 0) & (b != 0), TINY, 0.0)
    return e * INFLATE


def _scaled(op: str, a: _Arg, f: Fraction, guard: L.Guard) -> tuple[np.ndarray, np.ndarray]:
    """a's values times the exact factor f, in float64, with their bounds."""
    v, e = a.floats(op, guard)
    if f == 1:
        return v, e
    try:
        fv, fe = to_float(f)
    except OverflowError:
        raise _too_large(op, "a unit's factor") from None
    out = v * fv
    return out, _mul_err(v, e, np.asarray(fv), np.asarray(fe), out)


def _own(node: Any, args: list[_Arg], *how: str, always: bool = False) -> Label:
    """The label of a float64 result: what its arguments carried, how it was
    made here, and this node among the origins when float64 entered here."""
    entered = always or any(a.kind not in (FLOAT64, COMPLEX) or a.taken == HOW_ROUNDED_IN for a in args)
    extra = tuple(a.taken for a in args if a.taken) + how
    return label_of(*[a.label for a in args], origins=(node.id,) if entered else (), how=extra)


def _undecided(op: str, what: str, i: int, shape: tuple[int, ...], value: float, bound: float, unit: U.Unit) -> Refusal:
    u = U.format_unit(unit)
    sfx = f" {u}" if u else ""
    return Refusal(
        f"{op} cannot decide {what} at element {index_text(i, shape)}: the float64 value there is {value!r}{sfx}, "
        f"within {bound!r}{sfx} of its true value, so flo2-calc does not guess. Decide it another way, or keep the "
        "data exact.",
        kind="undecidable",
    )


def _float_elementwise(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    units = [a.unit for a in args]
    if any(U.scale_of(u) for u in units) or (node.unit is not None and U.scale_of(node.unit)):
        raise Refusal(
            f"{op}: a temperature reading in degC or degF is carried exactly or not at all, and here it would be "
            "float64. Convert it to K first while it is exact, or work with a change of temperature.",
            kind="offset_temperature",
        )
    if op not in RATIONAL or op == "pow" or (op == "convert" and not _plain_conversion(units[0], node.unit)):
        return _arb_elementwise(node, args, shape, guard)
    if op in ("ceil", "floor", "round"):
        return _decided_rounding(node, args[0], shape, guard)
    if op in ("add", "sub", "min", "max") or E.OPS[op][0] == "comparison":
        fs = [Fraction(1)] + [U.conversion(u, units[0], op) for u in units[1:]]
        parts = [_scaled(op, a, f, guard) for a, f in zip(args, fs, strict=True)]
        if E.OPS[op][0] == "comparison":
            return _float_compare(node, parts, shape, units[0])
        if op in ("min", "max"):
            pick = np.minimum if op == "min" else np.maximum
            v, e = parts[0]
            for pv, pe in parts[1:]:
                v, e = pick(v, pv), np.maximum(e, pe)
        else:
            v, e = parts[0]
            sign = -1.0 if op == "sub" else 1.0
            for pv, pe in parts[1:]:
                v = v + sign * pv
                e = (e + pe + U53 * np.abs(v)) * INFLATE
        unit = units[0]
    elif op == "mul":
        unit, scale = units[0], Fraction(1)
        v, e = args[0].floats(op, guard)
        for a in args[1:]:
            unit, s = U.multiply(unit, a.unit)
            scale *= s
            bv, be = a.floats(op, guard)
            nv = v * bv
            e, v = _mul_err(v, e, bv, be, nv), nv
        if scale != 1:
            sv, se = to_float(scale)
            nv = v * sv
            e, v = _mul_err(v, e, np.asarray(sv), np.asarray(se), nv), nv
    elif op == "div":
        unit, scale = U.multiply(units[0], U.invert(units[1]))
        av, ae = _scaled(op, args[0], scale, guard)
        bv, be = args[1].floats(op, guard)
        av, ae, bv, be = (np.broadcast_to(x, shape) for x in (av, ae, bv, be))
        bad = np.abs(bv) <= be
        if np.any(bad):
            i = int(np.flatnonzero(bad.ravel())[0])
            if bv.ravel()[i] == 0 and be.ravel()[i] == 0:
                raise Refusal(f'div: "{names[1]}" is zero at element {index_text(i, shape)}, and division by zero has no value.', kind="division_by_zero")
            raise _undecided("div", f'whether "{names[1]}" is zero', i, shape, float(bv.ravel()[i]), float(be.ravel()[i]), units[1])
        v = av / bv
        with np.errstate(over="ignore", invalid="ignore"):
            e = (np.abs(av) * be + np.abs(bv) * ae) / (np.abs(bv) * (np.abs(bv) - be)) + U53 * np.abs(v)
        e = (e + np.where((np.abs(v) < NORMAL_MIN) & (av != 0), TINY, 0.0)) * INFLATE
    elif op in ("neg", "abs"):
        v, e = args[0].floats(op, guard)
        v = -v if op == "neg" else np.abs(v)
        unit = units[0]
    elif op == "convert":
        v, e = _scaled(op, args[0], U.conversion(units[0], node.unit, "convert"), guard)
        unit = node.unit
    else:  # pragma: no cover
        raise AssertionError(op)
    v, e = np.broadcast_to(v, shape), np.broadcast_to(e, shape)
    finite_or_refuse(op, v, e)
    return float_array(np.array(v), np.array(e), unit, _own(node, args, HOW_ARITH))


def _plain_conversion(frm: U.Unit, to: U.Unit | None) -> bool:
    try:
        U.conversion(frm, to, "convert")  # type: ignore[arg-type]
        return True
    except Refusal:
        return U.pi_conversion(frm, to) is None  # type: ignore[arg-type]


def _float_compare(node: Any, parts: list[tuple[np.ndarray, np.ndarray]], shape: tuple[int, ...], unit: U.Unit) -> Any:
    op, names = node.op, node.args
    (av, ae), (bv, be) = parts
    d = av - bv
    ed = (ae + be + U53 * np.abs(d)) * INFLATE
    d, ed = np.broadcast_to(d, shape).ravel(), np.broadcast_to(ed, shape).ravel()
    pos, neg, zero = d > ed, d < -ed, (d == 0) & (ed == 0)
    table = {
        "eq": (zero, pos | neg), "ne": (pos | neg, zero), "lt": (neg, pos | zero), "le": (neg | zero, pos),
        "gt": (pos, neg | zero), "ge": (pos | zero, neg),
    }
    true, false = table[op]
    undecided = ~(true | false)
    if np.any(undecided):
        i = int(np.flatnonzero(undecided)[0])
        raise Refusal(
            f'{op} cannot decide "{names[0]}" against "{names[1]}" at element {index_text(i, shape)}: their float64 '
            f"values differ by {float(d[i])!r} and their bounds add up to {float(ed[i])!r}"
            f"{' ' + U.format_unit(unit) if unit else ''}, so flo2-calc does not guess. Decide it another way, or keep "
            "the data exact.",
            kind="undecidable",
        )
    if shape == ():
        return bool(true[0])
    return bool_array(true, shape)


def _decided_rounding(node: Any, a: _Arg, shape: tuple[int, ...], guard: L.Guard) -> Any:
    """ceil, floor or round of a float64 value: answered where the bound
    decides it, and then exact (and true of the true value)."""
    places = node.places if node.places is not None else 0
    mode = node.mode or "half_even"
    v, e = a.floats(node.op, guard)
    n = max(1, math.prod(shape))
    large = n > EXACT_MAX_ELEMENTS
    out: list[Any] = []
    fv, fe = (np.empty(n), np.empty(n)) if large else (None, None)
    for i, (x, err) in enumerate(zip(floats_in(np.broadcast_to(v, shape)), floats_in(np.broadcast_to(e, shape)))):
        if i % CHECK_EVERY == 0:
            guard.check_time()
        lo = E._round_to(Fraction(x) - Fraction(err), places, node.op, mode)
        hi = E._round_to(Fraction(x) + Fraction(err), places, node.op, mode)
        if lo != hi:
            raise _undecided(node.op, "which way it rounds", i, shape, x, err, a.unit)
        if large:
            fv[i], fe[i] = to_float(lo)  # type: ignore[index]
        else:
            out.append(lo)
    if large:  # decided, then carried in float64 because it is large
        return float_array(fv.reshape(shape), fe.reshape(shape), a.unit, Label((node.id,), (HOW_LARGE, HOW_TAKEN)))  # type: ignore[union-attr]
    return _result(out, shape, a.unit, node, guard)


# ---------------------------------------------------------------- the rounded class over arrays, through Arb


def _arb_to_float(y: Any) -> tuple[float, float]:
    """(the double nearest an Arb ball's midpoint, an upper bound on its
    distance from every point of the ball: Arb's own bound on |ball - v|).
    Raises OverflowError past float64."""
    v = float(y)  # python-flint rounds the midpoint to the nearest double
    if not math.isfinite(v):
        raise OverflowError
    man, exp = (y - v).abs_upper().man_exp()
    man = int(man)
    return v, (_ldexp_up(man, int(exp)) * INFLATE if man else 0.0)


@dataclass
class _Plan:
    fn: Callable[..., Any]
    scales: list[Fraction]
    unit: U.Unit
    check: Callable[[int, list[Any], list[Any]], None] | None = None  # (index, balls, exact elements or None)


def _unit_refusal(op: str, name: str, unit: U.Unit, what: str) -> Refusal:
    return Refusal(
        f'{op} takes {what}, and "{name}" is in {U.format_unit(unit)} ({U.describe_dimension(unit)}). A unit is never '
        "dropped: divide it by a value in the same unit first if a ratio is what you mean.",
        kind="unit_mismatch",
        units=(U.format_unit(unit), ""),
    )


def fold(unit: U.Unit) -> tuple[U.Unit, Fraction]:
    """A "%" folded out of a unit, as evaluator._fold folds it out of a value:
    (the unit without it, the factor its magnitude takes)."""
    k = dict(unit).get(U.PERCENT)
    if not k:
        return unit, Fraction(1)
    return tuple((s, e) for s, e in unit if s != U.PERCENT), Fraction(1, 100) ** k


def _plain_scale(op: str, name: str, unit: U.Unit, what: str = "a plain number") -> Fraction:
    folded, scale = fold(unit)
    if folded != U.PLAIN:
        raise _unit_refusal(op, name, unit, what)
    return scale


def _domain(op: str, name: str, i: int, shape: tuple[int, ...], ok: bool, known_bad: bool, need: str, kind: str = "out_of_domain") -> None:
    if ok:
        return
    if known_bad:
        raise Refusal(f'{op}: "{name}" at element {index_text(i, shape)} is outside its domain: {need}.', kind=kind)
    raise Refusal(
        f'{op}: "{name}" at element {index_text(i, shape)} may be outside its domain within its error bound ({need}), '
        "so flo2-calc does not guess.",
        kind="undecidable",
    )


def _plan(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> _Plan:
    op, names = node.op, node.args
    F = RM.flint()
    units = [a.unit for a in args]

    def at_(i: int) -> str:
        return index_text(i, shape)

    if op == "sqrt":
        folded, scale = fold(units[0])
        if any(e % 2 for _, e in folded):
            shown = U.format_unit(folded)
            raise Refusal(f'sqrt: "{names[0]}" is in {shown}, which has no exact square root as a unit (its exponents are not all even).', kind="unit_mismatch", units=(shown, ""))

        def chk(i: int, b: list[Any], _x: list[Any]) -> None:
            _domain(op, names[0], i, shape, b[0] >= 0, b[0] < 0, "a number >= 0")

        return _Plan(lambda x: x.sqrt(), [scale], tuple((s, e // 2) for s, e in folded), chk)
    if op in ("exp", "ln", "log10"):
        scale = _plain_scale(op, names[0], units[0])
        if op == "exp":
            return _Plan(lambda x: x.exp(), [scale], U.PLAIN)

        def chk(i: int, b: list[Any], _x: list[Any]) -> None:
            _domain(op, names[0], i, shape, b[0] > 0, b[0] <= 0, "a number > 0")

        fn = (lambda x: x.log()) if op == "ln" else (lambda x: x.log() / F.arb.const_log10())
        return _Plan(fn, [scale], U.PLAIN, chk)
    if op in ("sin", "cos", "tan"):
        kind_f = U.angle_kind(units[0])
        if kind_f is None:
            raise Refusal(
                f'{op} takes an angle in deg or rad (or arcmin, arcsec), and "{names[0]}" is '
                f"{'a plain number' if units[0] == U.PLAIN else 'in ' + U.format_unit(units[0])}. Give the angle its unit.",
                kind="unit_mismatch",
                units=(U.format_unit(units[0]), "deg"),
            )
        kind, f = kind_f
        if op == "tan":

            def chk(i: int, b: list[Any], x: list[Any]) -> None:
                if x[0] is not None and kind == "deg" and (x[0] - 90) % 180 == 0:
                    raise Refusal(f'tan: "{names[0]}" at element {at_(i)} is {x[0]} deg, where the tangent has no value.', kind="undefined")
                c = (b[0] * F.arb.pi() / 180).cos() if kind == "deg" else b[0].cos()
                if not (c > 0 or c < 0):
                    raise Refusal(f'tan: "{names[0]}" at element {at_(i)} may be a pole of the tangent within its error bound.', kind="undecidable")

            return _Plan(RM.TAN[kind].arb, [f], U.PLAIN, chk)
        return _Plan((RM.SIN if op == "sin" else RM.COS)[kind].arb, [f], U.PLAIN)
    if op in ("asin", "acos", "atan"):
        scale = _plain_scale(op, names[0], units[0])
        kind, f = U.angle_kind(node.unit)  # type: ignore[misc]
        fn = RM.scaled({"asin": RM.ASIN, "acos": RM.ACOS, "atan": RM.ATAN}[op][kind], 1 / f).arb
        if op == "atan":
            return _Plan(fn, [scale], node.unit)

        def chk(i: int, b: list[Any], _x: list[Any]) -> None:
            _domain(op, names[0], i, shape, b[0] >= -1 and b[0] <= 1, b[0] > 1 or b[0] < -1, "a number from -1 to 1")

        return _Plan(fn, [scale], node.unit, chk)
    if op == "atan2":
        fx = U.conversion(units[1], units[0], op)
        kind, f = U.angle_kind(node.unit)  # type: ignore[misc]

        def chk(i: int, b: list[Any], _x: list[Any]) -> None:
            y, x = b
            if y == 0 and x == 0:
                raise Refusal(f'atan2: "{names[0]}" and "{names[1]}" are both zero at element {at_(i)}, and the angle of the origin has no value.', kind="undefined")
            if not _angle_decided(y, x):
                raise Refusal(f'atan2: at element {at_(i)} the angle may be either side of 180 deg, or of the origin, within the error bounds.', kind="undecidable")

        return _Plan(RM.scaled(RM.ATAN2[kind], 1 / f).arb, [Fraction(1), fx], node.unit, chk)
    if op == "pow":
        return _pow_plan(node, args, shape)
    if op == "convert":
        turned = U.pi_conversion(units[0], node.unit)
        assert turned is not None
        f, k = turned
        return _Plan(RM.angle_factor(k).arb, [f], node.unit)
    if op in ("normal_cdf", "normal_sf"):
        fn = (RM.NORMAL_CDF if op == "normal_cdf" else RM.NORMAL_SF).arb
        if len(args) == 1:
            scale = _plain_scale(op, names[0], units[0], "a plain number (the standard normal), or [x, mean, sd] in one unit")
            return _Plan(lambda x: fn(x, F.arb(0), F.arb(1)), [scale], U.PLAIN)
        fm, fs = U.conversion(units[1], units[0], op), U.conversion(units[2], units[0], op)

        def chk(i: int, b: list[Any], _x: list[Any]) -> None:
            _domain(op, names[2], i, shape, b[2] > 0, b[2] <= 0, "a standard deviation > 0")

        return _Plan(fn, [Fraction(1), fm, fs], U.PLAIN, chk)
    if op == "normal_quantile":
        sp = _plain_scale(op, names[0], units[0], "a probability, a plain number")
        if len(args) == 1:
            def chk1(i: int, b: list[Any], _x: list[Any]) -> None:
                _domain(op, names[0], i, shape, b[0] > 0 and b[0] < 1, b[0] <= 0 or b[0] >= 1, "a probability strictly between 0 and 1")

            return _Plan(lambda p: RM.NORMAL_QUANTILE.arb(p, F.arb(0), F.arb(1)), [sp], U.PLAIN, chk1)
        fs = U.conversion(units[2], units[1], op)

        def chk3(i: int, b: list[Any], _x: list[Any]) -> None:
            _domain(op, names[0], i, shape, b[0] > 0 and b[0] < 1, b[0] <= 0 or b[0] >= 1, "a probability strictly between 0 and 1")
            _domain(op, names[2], i, shape, b[2] > 0, b[2] <= 0, "a standard deviation > 0")

        return _Plan(RM.NORMAL_QUANTILE.arb, [sp, Fraction(1), fs], units[1], chk3)
    if op == "chi2_sf":
        sx = _plain_scale(op, names[0], units[0], "a chi-square statistic, a plain number")
        sd = _plain_scale(op, names[1], units[1], "degrees of freedom, a plain number")
        if args[1].kind != EXACT:
            raise Refusal(f'chi2_sf: the degrees of freedom "{names[1]}" are not exact; they must be.', kind="out_of_domain")

        def chk(i: int, b: list[Any], _x: list[Any]) -> None:
            _domain(op, names[0], i, shape, b[0] >= 0, b[0] < 0, "a chi-square statistic >= 0")
            _domain(op, names[1], i, shape, b[1] > 0, b[1] <= 0, "degrees of freedom > 0")

        return _Plan(RM.CHI2_SF.arb, [sx, sd], U.PLAIN, chk)
    raise Refusal(f"{op} does not work over arrays yet; apply it to single values (element picks one out).", kind="type_mismatch")


def _angle_decided(y: Any, x: Any) -> bool:
    """Whether the angle of (x, y) is decided by their balls: away from the
    origin, and not straddling the cut at 180 deg."""
    if y > 0 or y < 0:
        return True
    if y == 0:  # exactly on the axis: 0 or 180 deg, as x's sign says
        return bool(x > 0 or x < 0)
    return bool(x > 0)


def _pow_plan(node: Any, args: list[_Arg], shape: tuple[int, ...]) -> _Plan:
    names = node.args
    base, ex = args
    _exponent_plain(node, ex)
    folded, scale = fold(base.unit)
    whole_scalar = ex.kind == EXACT and not ex.shape and ex.exact[()].denominator == 1  # type: ignore[index]
    if folded != U.PLAIN:
        if ex.kind != EXACT or ex.shape and len(set(ex.exact.ravel().tolist())) > 1:  # type: ignore[union-attr]
            raise Refusal(
                f'pow: "{names[0]}" is in {U.format_unit(base.unit)}, so its exponent must be one exact number, or the '
                "power of its unit would not be one unit. Make the base a plain number first.",
                kind="unit_mismatch",
                units=(U.format_unit(base.unit), ""),
            )
        y = next(iter(ex.exact.ravel()))  # type: ignore[union-attr]
        powers = [(s, e * y) for s, e in folded]
        if any(p.denominator != 1 for _, p in powers):
            shown = U.format_unit(folded)
            raise Refusal(f'pow: "{names[0]}" is in {shown}, and {shown} to the power {y} is not a unit.', kind="unit_mismatch", units=(shown, ""))
        unit = tuple((s, int(p)) for s, p in powers)
    else:
        unit = U.PLAIN
    if whole_scalar:
        n = int(ex.exact[()])  # type: ignore[index]
        if abs(n) > E.MAX_POWER_ARG:
            raise Refusal(f"pow: an exponent is at most {E.MAX_POWER_ARG} either way; this one is {n}.", kind="too_large")
        unit, pscale = U.power(base.unit, n)
        # As for a single value: a "%" the power folds is folded into the base first.
        bscale = Fraction(1, 100) ** dict(base.unit)[U.PERCENT] if pscale != 1 else Fraction(1)

        def chk_whole(i: int, b: list[Any], _x: list[Any]) -> None:
            x = b[0]
            if n <= 0 and not (x > 0 or x < 0):
                if x == 0:
                    if n == 0:
                        raise Refusal(f"pow: at element {index_text(i, shape)} zero to the power zero has no single agreed value.", kind="undefined")
                    raise Refusal(f'pow: "{names[0]}" is zero at element {index_text(i, shape)}, and a negative power of zero divides by zero.', kind="division_by_zero")
                raise Refusal(f'pow: "{names[0]}" may be zero at element {index_text(i, shape)} within its error bound.', kind="undecidable")

        return _Plan(lambda x, _y: x**n, [bscale, Fraction(1)], unit, chk_whole)

    def whole(y: Any) -> int | None:
        if not y.is_exact():
            return None
        k = y.unique_fmpz()
        return None if k is None else int(k)

    def chk(i: int, b: list[Any], _x: list[Any]) -> None:
        x, y = b
        k = whole(y)
        if k is not None:  # a whole exponent among them: as a whole power
            if abs(k) > E.MAX_POWER_ARG:
                raise Refusal(f"pow: at element {index_text(i, shape)} the exponent is {k}; an exponent is at most {E.MAX_POWER_ARG} either way.", kind="too_large")
            if k <= 0 and not (x > 0 or x < 0):
                if x == 0:
                    if k == 0:
                        raise Refusal(f"pow: at element {index_text(i, shape)} zero to the power zero has no single agreed value.", kind="undefined")
                    raise Refusal(f'pow: "{names[0]}" is zero at element {index_text(i, shape)}, and a negative power of zero divides by zero.', kind="division_by_zero")
                raise Refusal(f'pow: "{names[0]}" may be zero at element {index_text(i, shape)} within its error bound.', kind="undecidable")
            return
        _domain("pow", names[0], i, shape, x >= 0, x < 0, "a number >= 0 (a negative number has no real non-whole power)")
        if not (x > 0):
            if y > 0:
                return
            if y < 0 and x == 0:
                raise Refusal(f'pow: "{names[0]}" is zero at element {index_text(i, shape)}, and a negative power of zero divides by zero.', kind="division_by_zero")
            raise Refusal(f'pow: at element {index_text(i, shape)} the base may be zero and the exponent not above zero.', kind="undecidable")

    def power(x: Any, y: Any) -> Any:
        k = whole(y)
        if k is not None:
            return x**k
        if x == 0:
            return RM.flint().arb(0)
        return x**y

    return _Plan(power, [scale, Fraction(1)], unit, chk)


def _balls(a: _Arg, shape: tuple[int, ...], scale: Fraction) -> tuple[Any, Any]:
    """Iterators over a's elements as Arb balls (times the exact scale), and
    over its exact elements (None for a float64 argument)."""
    F = RM.flint()
    s = F.fmpq(scale.numerator, scale.denominator)
    if a.kind == EXACT:
        xs = list(np.broadcast_to(a.exact, shape).ravel()) if shape else [a.exact[()]]  # type: ignore[index]

        def gen_exact() -> Any:
            for q in xs:
                yield F.arb(F.fmpq(q.numerator, q.denominator) * s)

        return gen_exact(), [q * scale for q in xs]
    n = max(1, math.prod(shape))

    def gen_float() -> Any:
        for x, r in zip(floats_in(np.broadcast_to(a.v, shape)), floats_in(np.broadcast_to(a.e, shape))):
            b = F.arb(x, r) if r else F.arb(x)
            yield b * s if scale != 1 else b

    return gen_float(), _Nones(n)


class _Nones:
    """No exact elements: None at every index, without a list of them."""

    def __init__(self, n: int) -> None:
        self.n = n

    def __getitem__(self, i: int) -> None:
        return None

    def __len__(self) -> int:
        return self.n


def _arb_elementwise(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> Any:
    op = node.op
    if op == "t_quantile":
        return _t_quantile_elementwise(node, args, shape, guard)
    plan = _plan(node, args, shape, guard)
    n = max(1, math.prod(shape))
    gens = [_balls(a, shape, s) for a, s in zip(args, plan.scales, strict=True)]
    iters = [g[0] for g in gens]
    exacts = [g[1] for g in gens]
    v = np.empty(n, dtype=np.float64)
    e = np.empty(n, dtype=np.float64)
    F = RM.flint()
    with RM._LOCK:
        saved = F.ctx.prec
        F.ctx.prec = ARB_BITS
        try:
            for i in range(n):
                if i % CHECK_EVERY == 0:
                    guard.check_time()
                balls = [next(it) for it in iters]
                if plan.check is not None:
                    plan.check(i, balls, [x[i] for x in exacts])
                y = plan.fn(*balls)
                if not y.is_finite():
                    raise Refusal(
                        f"{op}: at element {index_text(i, shape)} Arb could not bound the result (its arguments' error "
                        "bounds are too wide, or it is past float64's range), so flo2-calc gives none.",
                        kind="undecidable",
                    )
                try:
                    v[i], e[i] = _arb_to_float(y)
                except OverflowError:
                    raise _element_refusal(_too_large(op, "the result"), i, shape) from None
        finally:
            F.ctx.prec = saved
    lab = _own(node, args, how_function(op), always=True)
    return float_array(v.reshape(shape), e.reshape(shape), plan.unit, lab)


def _t_quantile_elementwise(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> Any:
    """t_quantile over an array: each element correctly rounded to 17 digits
    by realmath's bracketing (no Arb function has the t quantile in closed
    form), then taken into float64 with that bound."""
    names = node.args
    p_arg, dof_arg = args
    sp = _plain_scale("t_quantile", names[0], p_arg.unit, "a probability, a plain number")
    _plain_scale("t_quantile", names[1], dof_arg.unit, "degrees of freedom, a plain number")
    if dof_arg.kind != EXACT:
        raise Refusal(f't_quantile: the degrees of freedom "{names[1]}" are not exact; they must be.', kind="out_of_domain")
    n = max(1, math.prod(shape))
    dofs = list(np.broadcast_to(dof_arg.exact, shape).ravel()) if shape else [dof_arg.exact[()]]  # type: ignore[index]
    if p_arg.kind == EXACT:
        ps = [(q * sp, Fraction(0)) for q in (list(np.broadcast_to(p_arg.exact, shape).ravel()) if shape else [p_arg.exact[()]])]  # type: ignore[index]
    else:
        ps = [(Fraction(x) * sp, Fraction(r) * sp) for x, r in zip(np.broadcast_to(p_arg.v, shape).ravel().tolist(), np.broadcast_to(p_arg.e, shape).ravel().tolist())]
    v = np.empty(n)
    e = np.empty(n)
    for i, ((p, rp), nu) in enumerate(zip(ps, dofs, strict=True)):
        guard.check_time()
        ball = RM.Ball(p, rp)
        _domain("t_quantile", names[0], i, shape, ball.lo > 0 and ball.hi < 1, (rp == 0 and not 0 < p < 1) or ball.hi <= 0 or ball.lo >= 1, "a probability strictly between 0 and 1")
        _domain("t_quantile", names[1], i, shape, nu > 0, nu <= 0, "degrees of freedom > 0")
        out = RM.t_quantile(ball, nu, 17, guard)
        f, conv = to_float(out.value)
        v[i] = f
        e[i] = float_up(out.error + Fraction(conv)) if (out.error or conv) else 0.0
    return float_array(v.reshape(shape), e.reshape(shape), U.PLAIN, _own(node, args, "t_quantile: each element correctly rounded to 17 digits by realmath's Arb-decided bracketing, then taken into float64", always=True))


# ---------------------------------------------------------------- complex values (from the FFT)


def _complex_floats(a: _Arg, op: str, guard: L.Guard) -> tuple[np.ndarray, np.ndarray]:
    v, e = a.floats(op, guard)
    return np.asarray(v, dtype=np.complex128), e


def _complex_elementwise(node: Any, args: list[_Arg], shape: tuple[int, ...], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    if op == "abs":
        return _magnitude(node, args[0], guard)
    if op not in ("add", "sub", "mul", "div", "neg"):
        cx = next(a for a in args if a.kind == COMPLEX)
        raise Refusal(
            f'{op} does not take complex values, and "{cx.name}" is complex (an FFT\'s result). Take its abs (the '
            "modulus), phase, real or imag part first.",
            kind="type_mismatch",
        )
    make_room(guard, shape, COMPLEX)
    units = [a.unit for a in args]
    if op in ("add", "sub"):
        fs = [Fraction(1)] + [U.conversion(u, units[0], op) for u in units[1:]]
        parts = []
        for a, f in zip(args, fs, strict=True):
            v, e = _complex_floats(a, op, guard)
            if f != 1:
                fv, fe = to_float(f)
                nv = v * fv
                e = (np.abs(fv) * e + _cabs(v.real, v.imag) * fe + e * fe + U53 * _cabs(nv.real, nv.imag)) * INFLATE
                v = nv
            parts.append((v, e))
        v, e = parts[0]
        for pv, pe in parts[1:]:
            v = v - pv if op == "sub" else v + pv
            e = (e + pe + U53 * _cabs(v.real, v.imag)) * INFLATE
        unit = units[0]
    elif op == "neg":
        v, e = _complex_floats(args[0], op, guard)
        v, unit = -v, units[0]
    elif op == "mul":
        unit, scale = units[0], Fraction(1)
        v, e = _complex_floats(args[0], op, guard)
        for a in args[1:]:
            unit, s = U.multiply(unit, a.unit)
            scale *= s
            bv, be = _complex_floats(a, op, guard)
            ar, ai, br, bi = v.real, v.imag, bv.real, bv.imag
            # The textbook product, one IEEE operation at a time (no fused multiply-add), so it is the same on
            # every machine: its rounding is at most sqrt(5) u |a b| (Brent, Percival and Zimmermann, "Error
            # bounds on complex floating-point multiplication", Math. Comp. 76 (2007)).
            re_ = ar * br - ai * bi
            im_ = ar * bi + ai * br
            na, nb = _cabs(ar, ai) * (1 + CABS_REL), _cabs(br, bi) * (1 + CABS_REL)
            e = (na * be + nb * e + e * be + 2.25 * U53 * na * nb) * INFLATE
            v = re_ + 1j * im_
        if scale != 1:
            sv, se = to_float(scale)
            nv = v * sv
            e = (abs(sv) * e + _cabs(v.real, v.imag) * se + e * se + U53 * _cabs(nv.real, nv.imag)) * INFLATE
            v = nv
    else:  # div: by a real value only
        if args[1].kind == COMPLEX:
            raise Refusal(f'div: "{names[1]}" is complex; flo2-calc divides a complex value by a real one only, for now.', kind="type_mismatch")
        unit, scale = U.multiply(units[0], U.invert(units[1]))
        av, ae = _complex_floats(args[0], op, guard)
        bv, be = args[1].floats(op, guard)
        if scale != 1:
            sv, se = to_float(scale)
            nv = av * sv
            ae = (abs(sv) * ae + _cabs(av.real, av.imag) * se + ae * se + U53 * _cabs(nv.real, nv.imag)) * INFLATE
            av = nv
        bb, beb = np.broadcast_to(bv, shape), np.broadcast_to(be, shape)
        bad = np.abs(bb) <= beb
        if np.any(bad):
            i = int(np.flatnonzero(bad.ravel())[0])
            if bb.ravel()[i] == 0 and beb.ravel()[i] == 0:
                raise Refusal(f'div: "{names[1]}" is zero at element {index_text(i, shape)}, and division by zero has no value.', kind="division_by_zero")
            raise _undecided("div", f'whether "{names[1]}" is zero', i, shape, float(bb.ravel()[i]), float(beb.ravel()[i]), units[1])
        v = (av.real / bv) + 1j * (av.imag / bv)
        na = _cabs(av.real, av.imag) * (1 + CABS_REL)
        with np.errstate(over="ignore", invalid="ignore"):
            e = ((na * be + np.abs(bv) * ae) / (np.abs(bv) * (np.abs(bv) - be)) + U53 * _cabs(v.real, v.imag)) * INFLATE
    v, e = np.broadcast_to(v, shape), np.broadcast_to(e, shape)
    finite_or_refuse(op, v.real, v.imag, e)
    return float_array(np.array(v), np.array(e), unit, _own(node, args, HOW_ARITH))


def _magnitude(node: Any, a: _Arg, guard: L.Guard) -> Any:
    v, e = a.floats(node.op, guard)
    if a.kind == COMPLEX:
        m = _cabs(v.real, v.imag)
        err = (e + CABS_REL * m) * INFLATE
    else:
        m, err = np.abs(v), e
    finite_or_refuse(node.op, m, err)
    return float_array(m, err, a.unit, _own(node, [a], HOW_ARITH))


def _complex_part(node: Any, values: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    a = operand(values[0], names[0])
    if a.kind == BOOL:
        raise Refusal(f'{op} takes numbers, and "{names[0]}" is true/false.', kind="type_mismatch")
    if not isinstance(values[0], Array):
        raise Refusal(f'{op} takes a complex value or an array (an FFT\'s result), and "{names[0]}" is a single real value.', kind="type_mismatch")
    if op == "phase" and a.kind != COMPLEX:
        return _real_phase(node, a, guard)
    if a.kind != COMPLEX:
        if op in ("real", "conj"):
            return values[0]
        if op == "imag":
            if a.kind == EXACT:
                return _result([Fraction(0)] * values[0].size, a.shape, a.unit, node, guard)
            return float_array(np.zeros(a.shape), np.zeros(a.shape), a.unit, a.label or Label((), ()))
        # the phase of a real value is 0 or 180 deg, decided by its sign, as below
    v, e = _complex_floats(a, op, guard)
    norm = values[0].norm  # a part's error vector is no longer than the whole one's
    if op == "real":
        return float_array(v.real.copy(), e, a.unit, a.label or Label((), ()), norm)
    if op == "imag":
        return float_array(v.imag.copy(), e, a.unit, a.label or Label((), ()), norm)
    if op == "conj":
        return float_array(np.conj(v), e, a.unit, a.label or Label((), ()), norm)
    # phase: the angle of each element, through Arb's atan2 over a box that holds its error disc
    kind, f = U.angle_kind(node.unit)  # type: ignore[misc]
    fn = RM.scaled(RM.ATAN2[kind], 1 / f).arb
    shape = a.shape
    n = max(1, v.size)
    re_it, im_it, err_it = floats_in(v.real), floats_in(v.imag), floats_in(np.broadcast_to(e, v.shape))
    out_v, out_e = np.empty(n), np.empty(n)
    F = RM.flint()
    with RM._LOCK:
        saved = F.ctx.prec
        F.ctx.prec = ARB_BITS
        try:
            for i in range(n):
                if i % CHECK_EVERY == 0:
                    guard.check_time()
                xr, xi, xe = next(re_it), next(im_it), next(err_it)
                y = F.arb(xi, xe) if xe else F.arb(xi)
                x = F.arb(xr, xe) if xe else F.arb(xr)
                if y == 0 and x == 0:
                    raise Refusal(f'phase: "{names[0]}" is zero at element {index_text(i, shape)}, and the angle of zero has no value. Pick the elements you need with element first.', kind="undefined")
                if not _angle_decided(y, x):
                    raise Refusal(
                        f'phase: at element {index_text(i, shape)} "{names[0]}" may be zero, or its angle either side of '
                        "180 deg, within its error bound, so flo2-calc does not guess. Pick the elements you need with "
                        "element first (an FFT's tiny bins have no meaningful phase).",
                        kind="undecidable",
                    )
                out_v[i], out_e[i] = _arb_to_float(fn(y, x))
        finally:
            F.ctx.prec = saved
    return float_array(out_v.reshape(shape), out_e.reshape(shape), node.unit, _own(node, [a], how_function("phase"), always=True))


def _real_phase(node: Any, a: _Arg, guard: L.Guard) -> Any:
    """The phase of a real value: 0 where it is decided positive, 180 deg (pi
    rad) where decided negative; refused at zero, or where its sign is not
    decided."""
    names = node.args
    kind, f = U.angle_kind(node.unit)  # type: ignore[misc]
    if a.kind == EXACT:
        xs, es = [(q, Fraction(0)) for q in a.exact.ravel()], None  # type: ignore[union-attr]
    else:
        xs = ((Fraction(x), Fraction(r)) for x, r in zip(floats_in(a.v), floats_in(a.e)))  # type: ignore[assignment]
    half_turn = Fraction(180) / f if kind == "deg" else None  # 180 deg in the node's deg-kind unit, exactly
    # math.pi is within 1.23e-16 of pi; in a rad-kind unit of factor f, pi / f, with that division's rounding.
    pi_v = math.pi / float(f) if kind == "rad" else 0.0
    pi_e = (1.23e-16 / float(f) + U53 * pi_v) * INFLATE if kind == "rad" else 0.0
    v, e = np.empty(a.shape).ravel(), np.zeros(a.shape).ravel()
    for i, (x, r) in enumerate(xs):
        if i % CHECK_EVERY == 0:
            guard.check_time()
        if x == 0 and r == 0:
            raise Refusal(f'phase: "{names[0]}" is zero at element {index_text(i, a.shape)}, and the angle of zero has no value.', kind="undefined")
        if x - r > 0:
            v[i] = 0.0
        elif x + r < 0:
            if half_turn is not None:
                v[i], e[i] = to_float(half_turn)
            else:
                v[i], e[i] = pi_v, pi_e
        else:
            raise Refusal(f'phase: the sign of "{names[0]}" at element {index_text(i, a.shape)} is not decided within its error bound.', kind="undecidable")
    return float_array(v.reshape(a.shape), e.reshape(a.shape), node.unit, _own(node, [a], "phase of a real value: 0, or a half turn, by its decided sign", always=True))


# ---------------------------------------------------------------- reductions


def _an_array(op: str, value: Any, name: str) -> Array:
    if not isinstance(value, Array) or value.shape == ():
        what = "true/false" if isinstance(value, bool) else "a single value"
        raise Refusal(f'{op} takes an array, and "{name}" is {what}.', kind="type_mismatch")
    return value


def _reduce(node: Any, values: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    if op == "count_true" and (len(values) > 1 or not isinstance(values[0], Array)):
        for v, n in zip(values, names, strict=True):
            if not isinstance(v, bool):
                raise Refusal(f'count_true counts true/false values, and "{n}" is {"an array" if isinstance(v, Array) else "a number"}; give one true/false array, or several true/false values.', kind="type_mismatch")
        return E.Quantity(Fraction(sum(values)))
    a = _an_array(op, values[0], names[0])
    if op in ("count_true", "any", "all"):
        if a.kind != BOOL:
            raise Refusal(f'{op} takes true/false values, and "{names[0]}" is an array of numbers; compare it first (lt, gt ...).', kind="type_mismatch")
    elif a.kind == BOOL:
        raise Refusal(f'{op} takes numbers, and "{names[0]}" is a true/false array' + ("; count_true counts its trues." if op == "sum" else "."), kind="type_mismatch")
    if a.kind == COMPLEX and op not in ("sum", "mean"):
        raise Refusal(f'{op} does not take complex values, and "{names[0]}" is complex; take its abs (the modulus) or real part first.', kind="type_mismatch")
    if U.scale_of(a.unit) and op not in ("min", "max", "mean", "argmin", "argmax"):
        raise Refusal(
            f'{op}: "{names[0]}" holds temperature readings in {U.format_unit(a.unit)}, whose zero is not zero '
            "temperature, so their sum or product has no meaning. Convert them to K first, or take their mean.",
            kind="offset_temperature",
        )
    if op == "product" and fold(a.unit)[0] != U.PLAIN:
        raise Refusal(f'product takes a plain array, and "{names[0]}" is in {U.format_unit(a.unit)}: its product\'s unit would grow with its length.', kind="unit_mismatch", units=(U.format_unit(a.unit), ""))
    axis = getattr(node, "axis", None)
    if op in ("argmin", "argmax"):
        if a.data.ndim != 1:
            raise Refusal(f"{op} takes a 1-D array; pick a row or column of a grid first.", kind="shape_mismatch")
        return _argext(node, a, guard)
    if axis is None:
        return _reduce_flat(node, a, a.data.ravel(), None if a.error is None else a.error.ravel(), guard)
    if a.data.ndim != 2:
        raise Refusal(f'{op}: "axis" sums along one axis of a grid (2-D), and "{names[0]}" is 1-D; leave "axis" out.', kind="shape_mismatch")
    lines = a.data.T if axis == 0 else a.data
    errs = (a.error.T if axis == 0 else a.error) if a.error is not None else None
    results = [_reduce_flat(node, a, lines[k], None if errs is None else errs[k], guard) for k in range(lines.shape[0])]
    return _assemble(node, results, guard)


def _assemble(node: Any, results: list[Any], guard: L.Guard) -> Any:
    first = results[0]
    if isinstance(first, bool):
        return bool_array(results, (len(results),))
    if isinstance(first, E.Quantity):
        if any(r.rounding is not None for r in results):  # pragma: no cover - reductions of exact data are exact
            raise AssertionError("a rounded reduction")
        return _result([r.magnitude for r in results], (len(results),), first.unit, node, guard)
    v = np.array([r.data.item() for r in results])
    e = np.array([float(r.error) for r in results])
    return float_array(v, e, first.unit, label_of(*[r.label for r in results]))


def _reduce_flat(node: Any, a: Array, xs: np.ndarray, es: np.ndarray | None, guard: L.Guard) -> Any:
    op = node.op
    n = xs.size
    if a.kind == BOOL:
        bs = xs.astype(bool)
        if op == "count_true":
            return E.Quantity(Fraction(int(bs.sum())))
        return bool(bs.any()) if op == "any" else bool(bs.all())
    if a.kind == EXACT:
        if op in ("sum", "mean"):
            total = Fraction(0)
            for i, q in enumerate(xs):
                total += q
                guard.check_number(total, "partial sum")
            return E.Quantity(total if op == "sum" else total / n, a.unit)
        if op == "product":
            unit, f = fold(a.unit)
            p = Fraction(1)
            for q in xs:
                p *= q * f
                guard.check_number(p, "partial product")
            return E.Quantity(p, unit)
        if op in ("min", "max"):
            return E.Quantity((min if op == "min" else max)(xs.tolist()), a.unit)
        raise AssertionError(op)  # pragma: no cover
    assert es is not None
    label = (a.label or Label((), ())).plus(how=(HOW_SUM,) if op in ("sum", "mean") else (HOW_ARITH,) if op == "product" else ())
    if a.kind == COMPLEX:
        re_ = math.fsum(floats_in(xs.real))
        im_ = math.fsum(floats_in(xs.imag))
        err = math.fsum(floats_in(es)) * INFLATE
        z = complex(re_, im_)
        if op == "mean":
            z = complex(re_ / n, im_ / n)
            err = (err / n + U53 * abs(complex(re_, im_)) / n) * INFLATE
        err = (err + U53 * float(_cabs(np.asarray(z.real), np.asarray(z.imag)))) * INFLATE
        finite_or_refuse(op, np.asarray([z.real, z.imag, err]))
        return float_array(np.asarray(z), np.asarray(err), a.unit, label)
    if op in ("sum", "mean"):
        s = math.fsum(floats_in(xs))
        err = (math.fsum(floats_in(es)) + U53 * abs(s)) * INFLATE
        if op == "mean":
            s2 = s / n
            err = (err / n + U53 * abs(s2)) * INFLATE
            s = s2
        finite_or_refuse(op, np.asarray([s, err]))
        return float_array(np.asarray(s), np.asarray(err), a.unit, label)
    if op in ("min", "max"):
        k = int(np.argmin(xs) if op == "min" else np.argmax(xs))
        return float_array(np.asarray(float(xs[k])), np.asarray(float(np.max(es))), a.unit, label)
    if op == "product":
        unit, f = fold(a.unit)
        p, ep = 1.0, 0.0
        for i, (x, ex) in enumerate(zip(floats_in(xs), floats_in(es))):
            if i % CHECK_EVERY == 0:
                guard.check_time()
            q = p * x
            ep = (abs(p) * ex + abs(x) * ep + ep * ex + U53 * abs(q) + (TINY if abs(q) < NORMAL_MIN and p and x else 0.0)) * INFLATE
            p = q
        if f != 1:
            fv, fe = to_float(f)
            q = p * fv
            ep = (abs(p) * fe + abs(fv) * ep + ep * fe + U53 * abs(q)) * INFLATE
            p = q
        finite_or_refuse(op, np.asarray([p, ep]))
        return float_array(np.asarray(p), np.asarray(ep), unit, label)
    raise AssertionError(op)  # pragma: no cover


def _argext(node: Any, a: Array, guard: L.Guard) -> E.Quantity:
    op, names = node.op, node.args
    xs = a.data
    if a.kind == EXACT:
        vals = xs.tolist()
        best = (min if op == "argmin" else max)(vals)
        return E.Quantity(Fraction(vals.index(best)))
    v = xs if op == "argmax" else -xs
    e = a.error
    k = int(np.argmax(v))
    lo = v[k] - e[k]
    others = np.ones(v.size, dtype=bool)
    others[k] = False
    rival = (v + e > lo) & others
    exact_ties = (v == v[k]) & (e == 0) & (e[k] == 0) & others
    rival = rival & ~(exact_ties & (np.arange(v.size) > k))
    if np.any(rival):
        j = int(np.flatnonzero(rival)[0])
        raise Refusal(
            f'{op}: elements [{k}] and [{j}] of "{names[0]}" ({float(xs[k])!r} and {float(xs[j])!r}) are within their '
            "error bounds of each other, so which is the extreme is not decided. flo2-calc does not guess.",
            kind="undecidable",
        )
    return E.Quantity(Fraction(k))


# ---------------------------------------------------------------- statistics over data


def _data(op: str, value: Any, name: str, numbers_only: bool = True) -> Array:
    a = _an_array(op, value, name)
    if a.data.ndim != 1:
        raise Refusal(f'{op} takes a 1-D array of data, and "{name}" is {shape_text(a.shape)}.', kind="shape_mismatch")
    if a.kind == BOOL:
        raise Refusal(f'{op} takes numbers, and "{name}" is a true/false array.', kind="type_mismatch")
    if a.kind == COMPLEX:
        raise Refusal(f'{op} does not take complex values, and "{name}" is complex.', kind="type_mismatch")
    if U.scale_of(a.unit):
        raise Refusal(
            f'{op}: "{name}" holds temperature readings in {U.format_unit(a.unit)}; convert them to K first (a spread or '
            "a slope of readings is a change of temperature).",
            kind="offset_temperature",
        )
    return a


def _places(node: Any) -> int:
    return node.digits if node.digits is not None else RM.DEFAULT_DIGITS


def _exact_sqrt(node: Any, q: Fraction, unit: U.Unit, guard: L.Guard) -> E.Quantity:
    """The square root of an exact rational: exact when it is one, else
    correctly rounded (the rounded class), labelled."""
    places = _places(node)
    out = RM.evaluate(RM.SQRT, [RM.Ball(q)], places, guard)
    return E._outcome(out, unit, node, [], places)


def _arb_data(a: Array) -> list[Any]:
    F = RM.flint()
    if a.kind == EXACT:
        return [F.arb(F.fmpq(q.numerator, q.denominator)) for q in a.data.tolist()]
    return [F.arb(x, r) if r else F.arb(x) for x, r in zip(a.data.tolist(), a.error.tolist())]  # type: ignore[union-attr]


def _with_arb(compute: Callable[[], Any], guard: L.Guard) -> Any:
    F = RM.flint()
    with RM._LOCK:
        saved = F.ctx.prec
        F.ctx.prec = 128
        try:
            guard.check_time()
            return compute()
        finally:
            F.ctx.prec = saved


def _float_scalar(node: Any, y: Any, unit: U.Unit, label: Label) -> Array:
    if not y.is_finite():
        raise Refusal(f"{node.op}: Arb could not bound the result (the data's error bounds are too wide), so flo2-calc gives none.", kind="undecidable")
    try:
        v, e = _arb_to_float(y)
    except OverflowError:
        raise _too_large(node.op, "the result") from None
    return float_array(np.asarray(v), np.asarray(e), unit, label)


def _data_stats(node: Any, values: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    a = _data(op, values[0], names[0])
    n = a.size
    sample = op.endswith("_sample")
    if n < (2 if sample else 1):
        raise Refusal(f'{op}: "{names[0]}" has {n} element(s); a sample variance needs at least 2 (it divides by n - 1).', kind="undefined")
    ddof = 1 if sample else 0
    unit2, fold = U.power(a.unit, 2)
    if a.kind == EXACT:
        xs = a.data.tolist()
        mean = sum(xs, Fraction(0)) / n
        ss = Fraction(0)
        for x in xs:
            ss += (x - mean) ** 2
            guard.check_number(ss, "sum of squared deviations")
        var = ss / (n - ddof) * fold
        if op.startswith("variance"):
            return E.Quantity(var, unit2)
        unit = tuple((s, e // 2) for s, e in unit2)
        return _exact_sqrt(node, var, unit, guard)

    def compute() -> Any:
        F = RM.flint()
        bs = _arb_data(a)
        m = sum(bs, F.arb(0)) / n
        ss = sum(((b - m) ** 2 for b in bs), F.arb(0))
        var = ss / (n - ddof) * F.arb(F.fmpq(fold.numerator, fold.denominator))
        if op.startswith("variance"):
            return var
        if not var > 0:
            hi = var.mid() + var.rad()
            var = F.arb(hi / 2, hi / 2) if hi > 0 else F.arb(0)
        return var.sqrt()

    y = _with_arb(compute, guard)
    unit = unit2 if op.startswith("variance") else tuple((s, e // 2) for s, e in unit2)
    return _float_scalar(node, y, unit, _own_data(node, [a], how_stats(op)))


def _own_data(node: Any, arrays: list[Array], how: str) -> Label:
    return label_of(*[x.label for x in arrays], origins=(node.id,), how=(how,))


def _fit(node: Any, values: list[Any], guard: L.Guard) -> Any:
    """Least squares y = intercept + slope x, with the standard errors of
    both and the residual standard error s = sqrt(SSR / (n - 2))."""
    op, names = node.op, node.args
    x = _data(op, values[0], names[0])
    y = _data(op, values[1], names[1])
    n = x.size
    if y.size != n:
        raise Refusal(f'{op}: "{names[0]}" has {n} elements and "{names[1]}" has {y.size}; a fit pairs them one to one.', kind="shape_mismatch")
    need = 2 if op in ("fit_slope", "fit_intercept") else 3
    if n < need:
        raise Refusal(
            f"{op}: {n} point(s) is too few; "
            + ("a line needs at least 2." if need == 2 else "a standard error needs at least 3 (it divides by n - 2)."),
            kind="undefined",
        )
    slope_unit, sscale = U.multiply(y.unit, U.invert(x.unit))
    if x.kind == EXACT and y.kind == EXACT:
        xs, ys = x.data.tolist(), y.data.tolist()
        xm = sum(xs, Fraction(0)) / n
        ym = sum(ys, Fraction(0)) / n
        sxx = sum(((xi - xm) ** 2 for xi in xs), Fraction(0))
        guard.check_number(sxx, "sum of squares of x")
        if sxx == 0:
            raise Refusal(f'{op}: every value of "{names[0]}" is the same, so no line through them has a slope.', kind="undefined")
        sxy = sum(((xi - xm) * (yi - ym) for xi, yi in zip(xs, ys, strict=True)), Fraction(0))
        b = sxy / sxx
        a0 = ym - b * xm
        if op == "fit_slope":
            return E.Quantity(b * sscale, slope_unit)
        if op == "fit_intercept":
            return E.Quantity(a0, y.unit)
        ssr = sum(((yi - a0 - b * xi) ** 2 for xi, yi in zip(xs, ys, strict=True)), Fraction(0))
        guard.check_number(ssr, "sum of squared residuals")
        s2 = ssr / (n - 2)
        if op == "fit_residual_se":
            return _exact_sqrt(node, s2, y.unit, guard)
        if op == "fit_slope_se":
            return _exact_sqrt(node, s2 / sxx * sscale * sscale, slope_unit, guard)
        return _exact_sqrt(node, s2 * (Fraction(1, n) + xm * xm / sxx), y.unit, guard)

    def compute() -> Any:
        F = RM.flint()
        bx, by = _arb_data(x), _arb_data(y)
        xm = sum(bx, F.arb(0)) / n
        ym = sum(by, F.arb(0)) / n
        sxx = sum(((xi - xm) ** 2 for xi in bx), F.arb(0))
        if not sxx > 0:
            raise Refusal(f'{op}: the values of "{names[0]}" may all be the same within their error bounds, so the slope is not decided.', kind="undecidable")
        sxy = sum(((xi - xm) * (yi - ym) for xi, yi in zip(bx, by, strict=True)), F.arb(0))
        b = sxy / sxx
        a0 = ym - b * xm
        sc = F.arb(F.fmpq(sscale.numerator, sscale.denominator))
        if op == "fit_slope":
            return b * sc
        if op == "fit_intercept":
            return a0
        ssr = sum(((yi - a0 - b * xi) ** 2 for xi, yi in zip(bx, by, strict=True)), F.arb(0))
        s2 = ssr / (n - 2)
        if op == "fit_residual_se":
            q = s2
        elif op == "fit_slope_se":
            q = s2 / sxx * sc * sc
        else:
            q = s2 * (F.arb(1) / n + xm * xm / sxx)
        if not q > 0:
            hi = q.mid() + q.rad()
            q = F.arb(hi / 2, hi / 2) if hi > 0 else F.arb(0)
        return q.sqrt()

    yv = _with_arb(compute, guard)
    unit = slope_unit if op in ("fit_slope", "fit_slope_se") else y.unit
    return _float_scalar(node, yv, unit, _own_data(node, [x, y], how_stats(op)))


# ---------------------------------------------------------------- the FFT

# Higham, Accuracy and Stability of Numerical Algorithms, 2nd ed. (SIAM, 2002), Theorem 24.2: for the radix-2
# Cooley-Tukey FFT of length n = 2^t, with computed twiddle factors within mu of the true ones,
#     ||y_computed - y||_2 / ||y||_2 <= t eta / (1 - t eta),   eta = mu + gamma_4 (sqrt(2) + mu),
# gamma_4 = 4u / (1 - 4u). flo2-calc takes mu = 8u for numpy's precomputed twiddles and doubles the bound for
# pocketfft's radix-4 passes (two radix-2 stages each).
MU = 8 * U53


def higham_bound(t: int) -> float:
    """The normwise relative bound flo2-calc states for a power-of-two FFT
    with t = log2 n stages in all (a grid's axes add)."""
    gamma4 = 4 * U53 / (1 - 4 * U53)
    eta = MU + gamma4 * (math.sqrt(2) + MU)
    te = t * eta
    return 2 * te / (1 - te) * INFLATE


def _power_of_two(n: int) -> bool:
    return n >= 1 and n & (n - 1) == 0


def _norm2(v: np.ndarray) -> float:
    """||v||_2, rounded up, with math.fsum (the same on every machine)."""
    sq = math.fsum(floats_in(v.real * v.real)) + math.fsum(floats_in(v.imag * v.imag))
    return math.sqrt(sq) * (1 + 4 * U53) * INFLATE


def _ldexp_up(n: int, e: int) -> float:
    """An upper bound on n 2^e (n >= 0), as a float, never overflowing early."""
    if n == 0:
        return 0.0
    shift = max(0, n.bit_length() - 900)
    return math.ldexp(float(n >> shift) * (1 + 2**-52) + 1.0, e + shift) + TINY


def _arb_fft_errors(x: np.ndarray, y: np.ndarray, inverse: bool, guard: L.Guard) -> np.ndarray:
    """For each element of numpy's result y, a bound on its distance from the
    exact DFT of the float64 input x: Arb's upper bound on |enclosure - y|,
    over the whole of its rigorous enclosure of that DFT (FLINT's acb_dft),
    1-D, or row by row and then column by column for a grid."""
    F = RM.flint()

    def compare(out: list[Any], ys: Any) -> list[float]:
        errs = []
        for z, yv in zip(out, ys):
            man, exp = (z - F.acb(yv.real, yv.imag)).abs_upper().man_exp()
            errs.append(_ldexp_up(int(man), int(exp)) * INFLATE)
        return errs

    if x.ndim == 1:
        guard.check_time()
        out = F.acb.dft([F.acb(z.real, z.imag) for z in floats_in(x)], inverse=inverse)
        return np.asarray(compare(out, floats_in(y)))
    m, n = x.shape
    rows = []
    for r in range(m):
        guard.check_time()
        rows.append(F.acb.dft([F.acb(z.real, z.imag) for z in x[r].tolist()], inverse=inverse))
    errs = np.empty((m, n))
    for c in range(n):
        guard.check_time()
        out = F.acb.dft([rows[r][c] for r in range(m)], inverse=inverse)
        errs[:, c] = compare(out, y[:, c].tolist())
    return errs


def _transform(node: Any, values: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    a = _an_array(op, values[0], names[0])
    dims = 2 if op.endswith("2") else 1
    if a.data.ndim != dims:
        raise Refusal(
            f'{op} takes a {dims}-D array, and "{names[0]}" is {shape_text(a.shape)}'
            + (f"; use {'fft2' if dims == 1 else 'fft'} for that." if a.data.ndim in (1, 2) else "."),
            kind="shape_mismatch",
        )
    if a.kind == BOOL:
        raise Refusal(f'{op} takes numbers, and "{names[0]}" is a true/false array.', kind="type_mismatch")
    if U.scale_of(a.unit):
        raise Refusal(f'{op}: "{names[0]}" holds temperature readings in {U.format_unit(a.unit)}; convert them to K first.', kind="offset_temperature")
    make_room(guard, a.shape, COMPLEX)
    arg = operand(a, names[0])
    v, e = arg.floats(op, guard)
    x = np.asarray(v, dtype=np.complex128)
    inverse = op.startswith("i")
    guard.check_time()
    y = (np.fft.ifft2 if inverse else np.fft.fft2)(x) if dims == 2 else (np.fft.ifft if inverse else np.fft.fft)(x)
    guard.check_time()
    lengths = a.shape
    total = a.size
    # The input's own error d, carried through. Each output is a sum of every input times a unit-modulus factor,
    # so it moves by at most sum|d| (divided by n for the inverse); and the transform scales the 2-norm of d by
    # sqrt(n) (by 1/sqrt(n) for the inverse), so each output also moves by at most that 2-norm, bounded by the
    # input's own normwise bound when it has one (an FFT's result does). The smaller of the two holds.
    ea = np.asarray(e, dtype=np.float64)
    sum_e = math.fsum(floats_in(ea))
    d2 = math.sqrt(math.fsum(floats_in(ea * ea))) * (1 + 4 * U53) * INFLATE
    if a.norm is not None:
        d2 = min(d2, a.norm)
    root_n = math.sqrt(total) * (1 + U53)
    if inverse:
        carried = min(sum_e / total, d2 / root_n * (1 + U53)) * INFLATE
        carried_norm = d2 / root_n * (1 + 2 * U53) * INFLATE
    else:
        carried = min(sum_e, d2 * root_n) * INFLATE
        carried_norm = d2 * root_n * INFLATE
    if all(_power_of_two(n) for n in lengths):
        t = sum(int(math.log2(n)) for n in lengths)
        b = higham_bound(t)
        alg = b / (1 - b) * _norm2(y) * INFLATE
        alg_norm = alg
        how = (
            f"{op} of {shape_text(lengths)} (numpy's pocketfft): every element within (B / (1 - B)) ||y||_2 of the exact "
            f"DFT of its float64 input, B = {b:.3g}, twice Higham's bound for the radix-2 FFT (Accuracy and Stability "
            f"of Numerical Algorithms, 2nd ed., SIAM 2002, Theorem 24.2: t eta / (1 - t eta), t = {t}, eta = mu + "
            "gamma_4 (sqrt 2 + mu), mu = 8u, u = 2^-53), plus the input's own bound carried through"
        )
        err = np.full(y.shape, (alg + carried) * INFLATE)
    else:  # alg_norm is set below, from the elements' bounds
        # Arb's enclosure holds about ARB_CHECK_BYTES per element while it is checked: room the host's budget
        # must have, beside the arrays already held, though it is given back afterwards.
        guard.check_array_room(total * (ARB_CHECK_BYTES + BYTES_PER[COMPLEX]), total, "FFT's check against Arb's rigorous DFT")
        F = RM.flint()
        with RM._LOCK:
            saved = F.ctx.prec
            F.ctx.prec = ARB_BITS
            try:
                errs = _arb_fft_errors(x, y, inverse, guard)
            finally:
                F.ctx.prec = saved
        err = (errs.reshape(y.shape) + carried) * INFLATE
        alg_norm = math.sqrt(math.fsum(floats_in(errs * errs))) * (1 + 4 * U53) * INFLATE
        how = (
            f"{op} of {shape_text(lengths)} (numpy's pocketfft; a length that is not a power of two): every element "
            "checked against Arb's rigorous enclosure of the exact DFT of its float64 input (FLINT acb_dft, "
            "python-flint), plus the input's own bound carried through"
        )
    finite_or_refuse(op, y.real, y.imag, err)
    norm = (alg_norm + carried_norm) * INFLATE
    return float_array(y, err, a.unit, _own(node, [arg], how, always=True), norm)


# ---------------------------------------------------------------- making and shaping arrays


def _whole(op: str, q: Any, name: str, lo: int, what: str) -> int:
    if not isinstance(q, E.Quantity) or q.rounding is not None or q.unit != U.PLAIN or q.magnitude.denominator != 1 or q.magnitude < lo:
        raise Refusal(f'{op}: "{name}" is {what}: an exact whole plain number, at least {lo}.', kind="out_of_domain")
    return int(q.magnitude)


def _shaping(node: Any, values: list[Any], guard: L.Guard) -> Any:
    op, names = node.op, node.args
    if op == "linspace":
        start, stop, count = values
        for v, nm in ((start, names[0]), (stop, names[1])):
            if not isinstance(v, E.Quantity):
                raise Refusal(f'linspace: "{nm}" is {"an array" if isinstance(v, Array) else "true/false"}; its ends are single numbers.', kind="type_mismatch")
        n = _whole(op, count, names[2], 2, "how many values")
        if n > MAX_ELEMENTS:
            raise Refusal(f"linspace: at most {MAX_ELEMENTS:,} values; {n:,} were asked for.", kind="too_large")
        f = U.conversion(stop.unit, start.unit, op)
        lo, hi = start.magnitude, stop.magnitude * f
        exact_ends = start.rounding is None and stop.rounding is None
        make_room(guard, (n,), EXACT if n <= EXACT_MAX_ELEMENTS and exact_ends else FLOAT64)
        step = (hi - lo) / (n - 1)
        if exact_ends and n <= EXACT_MAX_ELEMENTS:
            return _result([lo + step * k for k in range(n)], (n,), start.unit, node, guard)
        v, e = np.empty(n), np.empty(n)
        for k in range(n):  # each exact, straight into float64: no large list of exact numbers is held
            if k % CHECK_EVERY == 0:
                guard.check_time()
            try:
                v[k], e[k] = to_float(lo + step * k)
            except OverflowError:
                raise _too_large(op, "a value") from None
        if exact_ends:
            return float_array(v, e, start.unit, Label((node.id,), (HOW_LARGE, HOW_TAKEN)))
        bound = float_up(max(start.error, stop.error * f))  # interpolation weights lie in [0, 1]
        lab = label_of(origins=_origin_ids(start, stop) + (node.id,), how=(HOW_ROUNDED_IN, HOW_TAKEN))
        return float_array(v, (e + bound) * INFLATE, start.unit, lab)
    if op == "element":
        a = _an_array(op, values[0], names[0])
        idx = [_whole(op, q, nm, 0, "an index (0 for the first)") for q, nm in zip(values[1:], names[1:], strict=True)]
        if len(idx) != a.data.ndim:
            raise Refusal(f'element: "{names[0]}" is {shape_text(a.shape)}, so it takes {a.data.ndim} index(es); this node gives {len(idx)}.', kind="shape_mismatch")
        for k, (i, n) in enumerate(zip(idx, a.shape, strict=True)):
            if i >= n:
                raise Refusal(f'element: index {i} is past the end of "{names[0]}" (its {"rows" if a.data.ndim == 2 and k == 0 else "length"} is {n}; the first is 0).', kind="out_of_domain")
        x = a.data[tuple(idx)]
        if a.kind == EXACT:
            return E.Quantity(x, a.unit)
        if a.kind == BOOL:
            return bool(x)
        return float_array(np.asarray(x), np.asarray(a.error[tuple(idx)]), a.unit, a.label)  # type: ignore[index]
    a = _an_array(op, values[0], names[0])
    if op == "column":
        if a.data.ndim != 1:
            raise Refusal(f'column takes a 1-D array, and "{names[0]}" is {shape_text(a.shape)}.', kind="shape_mismatch")
        data, err = a.data.reshape(a.size, 1), None if a.error is None else a.error.reshape(a.size, 1)
    else:  # transpose
        if a.data.ndim != 2:
            raise Refusal(f'transpose takes a grid (2-D), and "{names[0]}" is 1-D; column turns a 1-D array into a column.', kind="shape_mismatch")
        data, err = a.data.T.copy(), None if a.error is None else a.error.T.copy()
    return Array(_frozen(np.ascontiguousarray(data)), a.unit, None if err is None else _frozen(np.ascontiguousarray(err)), a.label)


def _origin_ids(*qs: Any) -> tuple[str, ...]:
    return tuple(o for q in qs if isinstance(q, E.Quantity) and q.rounding is not None for o in q.rounding.origins)
