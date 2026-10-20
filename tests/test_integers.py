"""The exact integer operators: mod, divides, gcd, is_prime, factorize and integer_range.

req:integer-arithmetic-has-remainder-divisibility-and-primality in design 0bee0c00b35845f6
(flo2-calc 0.9.0, dec:v0-9-0-integer-operator-choices). Each operator is checked against an
INDEPENDENT computation written here: the floored remainder from its definition with Fraction,
divisibility as n == d k, a sieve and trial division for primality, Legendre's formula for the
primes of a factorial, the Fibonacci gcd identity, and known primes and factorizations (Mersenne
primes, Fermat numbers, Arnault's strong pseudoprime). Every input is exact on integers of any
size within the digits budget; a non-integer is refused with its reason; a primality proof or a
factorization past the host's limits is stopped, naming the limit, never guessed.

THE TRIAL. On flo2.io (2026-10-17), testing that n^2 + n + 41 is prime for n = 0..39 needed
v/d == floor(v/d) over a typed 40 x 39 grid. It is now integer_range 0..39, the values, is_prime
over them, and all; and n = 40 gives 1681 = 41 * 41.
"""

from __future__ import annotations

import json
import math

import anyio
from fractions import Fraction

import jsonschema
import pytest
from conftest import answer_of, graph, inp, op, session

from flo2_calc import integers as IN
from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.evaluator import OPS, evaluate, evaluation_json, read_graph
from flo2_calc.numbers import parse_number


def run(*nodes, limits=L.LAPTOP, result=None):
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result)), L.Guard(limits)))


def value_of(answer):
    assert answer["status"] == "ok", answer.get("refused")
    return answer["result"]["value"]


CHUNK = 60  # a typed number is at most 80 characters, so a longer integer is built from 60-digit pieces


def number_nodes(id, n):
    """Nodes whose last is `id`, the exact integer n: typed whole when short, else built by Horner's rule from
    60-digit pieces, so the integer operators meet numbers far longer than a value may be typed."""
    if len(str(n)) <= 70:
        return [inp(id, str(n))]
    digits = str(abs(n))
    pieces = [digits[max(0, k - CHUNK):k] for k in range(len(digits), 0, -CHUNK)][::-1]
    nodes = [inp(f"{id}_base", "1" + "0" * CHUNK, "10^60"), inp(f"{id}_p0", pieces[0], "a piece")]
    acc = f"{id}_p0"
    for i, piece in enumerate(pieces[1:], 1):
        nodes += [inp(f"{id}_p{i}", str(int(piece)), "a piece"), op(f"{id}_s{i}", "mul", acc, f"{id}_base"),
                  op(f"{id}_h{i}", "add", f"{id}_s{i}", f"{id}_p{i}")]
        acc = f"{id}_h{i}"
    nodes.append(op(id, "neg", acc) if n < 0 else op(id, "add", acc, f"{id}_zero"))
    if n >= 0:
        nodes.insert(0, inp(f"{id}_zero", "0", "zero"))
    return nodes


def one(name, *values, limits=L.LAPTOP):
    """One integer operator over single values a0, a1, ..."""
    ins = [node for i, v in enumerate(values) for node in number_nodes(f"a{i}", v)]
    return run(*ins, op("r", name, *[f"a{i}" for i in range(len(values))]), result="r", limits=limits)


def integer(text):
    if text.lstrip("-").isdigit():
        return int(text)
    q = parse_number(text)
    assert q.denominator == 1, text
    return q.numerator


def grid(answer):
    return [[integer(x) for x in row] for row in answer["result"]["array"]["values"]]


def sieve(n):
    flags = [True] * n
    flags[0:2] = [False, False]
    for p in range(2, math.isqrt(n - 1) + 1):
        if flags[p]:
            for q in range(p * p, n, p):
                flags[q] = False
    return flags


def trial_prime(n):
    return n >= 2 and all(n % d for d in range(2, math.isqrt(n) + 1))


M127, M521, M607 = 2**127 - 1, 2**521 - 1, 2**607 - 1  # Mersenne primes: 39, 157 and 183 digits
F7 = 2**128 + 1  # the Fermat number F7 = 59649589127497217 * 5704689200685129054721 (Morrison and Brillhart, 1970)
# Arnault (1995): a 397-digit composite that is a strong probable prime to every prime base below 307.
ARNAULT_P1 = 29674495668685510550154174642905332730771991799853043350995075531276838753171770199594238596428121188033664754218345562493168782883
ARNAULT = ARNAULT_P1 * (313 * (ARNAULT_P1 - 1) + 1) * (353 * (ARNAULT_P1 - 1) + 1)


def strong_probable_prime(n, a):
    d, s = n - 1, 0
    while d % 2 == 0:
        d, s = d // 2, s + 1
    x = pow(a, d, n)
    if x in (1, n - 1):
        return True
    for _ in range(s - 1):
        x = x * x % n
        if x == n - 1:
            return True
    return False


# ---------------------------------------------------------------- the trial: n^2 + n + 41


def euler_graph(a, b):
    return graph(
        inp("a", str(a), "the first n"), inp("b", str(b), "the last n"), inp("c", "41", "Euler's polynomial n^2 + n + 41"),
        op("n", "integer_range", "a", "b"),
        op("n2", "mul", "n", "n"),
        op("v", "add", "n2", "n", "c"),
        op("prime", "is_prime", "v"),
        op("every", "all", "prime"),
        op("count", "length", "n"),
        result=["every", "count", "v"],
    )


def test_n_squared_plus_n_plus_41_is_prime_for_every_n_from_0_to_39():
    answer = evaluation_json(evaluate(read_graph(euler_graph(0, 39))))
    assert answer["status"] == "ok"
    every, count, v = answer["results"]
    assert every["value"] == "true"
    assert count["value"] == "40", "the count comes from the range, never typed"
    assert [int(x) for x in v["array"]["values"]] == [n * n + n + 41 for n in range(40)]
    assert all(trial_prime(n * n + n + 41) for n in range(40))
    assert answer["exactness"].startswith("Exact for these inputs")
    texts = [f["text"] for f in answer["formula"]]
    assert "n = integer_range(a, b) = array 40 (exact)" in texts
    assert "every = all(is_prime(v)) = true" in texts


def test_at_n_40_it_is_1681_which_is_41_squared():
    answer = evaluation_json(evaluate(read_graph(graph(
        inp("n", "40", "the first n past the run"), inp("c", "41", "Euler's polynomial"),
        op("n2", "mul", "n", "n"), op("v", "add", "n2", "n", "c"),
        op("prime", "is_prime", "v"), op("f", "factorize", "v"), op("d", "divides", "c", "v"), op("m", "mod", "v", "c"),
        result=["v", "prime", "f", "d", "m"]))))
    v, prime, f, d, m = answer["results"]
    assert v["value"] == "1681" and prime["value"] == "false"
    assert f["array"]["shape"] == [1, 2] and f["array"]["values"] == [["41", "2"]], "1681 = 41^2: {41: 2}"
    assert d["value"] == "true" and m["value"] == "0"


def test_the_first_n_where_it_fails_is_found_without_typing_a_count():
    answer = evaluation_json(evaluate(read_graph(graph(
        inp("a", "0", "t"), inp("b", "80", "t"), inp("c", "41", "t"),
        op("n", "integer_range", "a", "b"), op("n2", "mul", "n", "n"), op("v", "add", "n2", "n", "c"),
        op("prime", "is_prime", "v"), op("composite", "not", "prime"), op("c01", "to_number", "composite"),
        op("first", "argmax", "c01"),
        op("how_many", "count_true", "composite")))))
    values = {e["node"]: e for e in answer["values"]}
    assert values["first"]["value"] == "40"
    assert values["how_many"]["value"] == str(sum(not trial_prime(n * n + n + 41) for n in range(81)))


def test_the_trial_reads_the_same_node_by_node():
    from flo2_calc.evaluator import read_nodes

    g = euler_graph(0, 39)
    whole = evaluation_json(evaluate(read_graph(g)))
    grown = evaluation_json(evaluate(read_nodes([(n, f"nodes[{i}]") for i, n in enumerate(g["nodes"])], g["result"])))
    assert grown["results"] == whole["results"]


# ---------------------------------------------------------------- mod


@pytest.mark.parametrize("a, b", [(7, 3), (-7, 3), (7, -3), (-7, -3), (0, 5), (5, 5), (3, 7), (-3, 7), (10**60 + 7, 97),
                                  (-(10**60), 10**30 + 1), (2**4000 + 1, 2**61 - 1)])
def test_mod_is_the_floored_remainder_with_the_sign_of_b(a, b):
    expected = Fraction(a) - b * math.floor(Fraction(a, b))
    assert integer(value_of(one("mod", a, b))) == expected
    if b > 0:
        assert 0 <= expected < b


def test_mod_by_zero_is_refused():
    r = one("mod", 7, 0)["refused"]
    assert r["kind"] == "division_by_zero" and r["node"] == "r" and r["op"] == "mod" and '"a1" is zero' in r["reason"]


# ---------------------------------------------------------------- divides


@pytest.mark.parametrize("d, n, expected", [(3, 12, True), (5, 12, False), (-3, 12, True), (3, -12, True), (7, 0, True),
                                             (0, 0, True), (0, 5, False), (1, 10**100 + 1, True),
                                             (41, 1681, True), (41, 1682, False), (2**89 - 1, (2**89 - 1) * (10**40 + 3), True),
                                             (2**89 - 1, (2**89 - 1) * (10**40 + 3) + 1, False)])
def test_divides_is_true_when_n_is_a_whole_multiple_of_d(d, n, expected):
    assert value_of(one("divides", d, n)) == ("true" if expected else "false")
    assert expected == (n == 0 if d == 0 else Fraction(n, d).denominator == 1)


# ---------------------------------------------------------------- gcd


def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


@pytest.mark.parametrize("args, expected", [((12, 18), 6), ((-12, 18), 6), ((12, -18), 6), ((0, 0), 0), ((0, 7), 7),
                                            ((12, 18, 8), 2), ((17, 31), 1), ((2**200 * 3**50, 2**150 * 3**80 * 5), 2**150 * 3**50)])
def test_gcd_is_the_greatest_common_divisor_of_the_absolute_values(args, expected):
    assert integer(value_of(one("gcd", *args))) == expected
    assert math.gcd(*args) == expected


def test_gcd_of_two_large_fibonacci_numbers_is_the_fibonacci_number_of_their_indices_gcd():
    # gcd(F_m, F_n) = F_gcd(m, n): an identity, not the function under test.
    assert integer(value_of(one("gcd", fib(3000), fib(1800)))) == fib(600)


# ---------------------------------------------------------------- is_prime


def test_is_prime_agrees_with_a_sieve_over_every_number_below_65536():
    flags = sieve(65_536)
    answer = run(inp("a", "0"), inp("b", "65535"), op("n", "integer_range", "a", "b"), op("p", "is_prime", "n"),
                 op("k", "count_true", "p"))
    assert value_of(answer) == str(sum(flags)) == "6542"
    for lo in range(0, 65_536, 1024):  # every element, a written-out block at a time
        answer = run(inp("a", str(lo)), inp("b", str(lo + 1023)), op("n", "integer_range", "a", "b"), op("p", "is_prime", "n"))
        got = [x == "true" for x in answer["result"]["array"]["values"]]
        assert got == flags[lo:lo + 1024], lo


@pytest.mark.parametrize("n", [-7, -1, 0, 1])
def test_below_2_nothing_is_prime(n):
    assert value_of(one("is_prime", n)) == "false"


@pytest.mark.parametrize("n, expected", [(2, True), (65_521, True), (65_537, True), (2**31 - 1, True), (2**32 + 1, False),
                                         (561, False), (3_215_031_751, False), (2**61 - 1, True), (2**64 + 1, False),
                                         (18_446_744_073_709_551_557, True), (M127, True), (M127 + 2, False),
                                         (M521, True), (M607, True), (M521 * M607, False), (F7, False)])
def test_is_prime_on_known_primes_and_composites(n, expected):
    assert value_of(one("is_prime", n)) == ("true" if expected else "false")


def test_strong_pseudoprimes_are_not_prime():
    # 3215031751 = 151 * 751 * 28351 is a strong probable prime to bases 2, 3, 5 and 7.
    assert 151 * 751 * 28351 == 3_215_031_751 and all(strong_probable_prime(3_215_031_751, a) for a in (2, 3, 5, 7))
    assert value_of(one("is_prime", 3_215_031_751)) == "false"
    # Arnault's number passes Miller-Rabin to every prime base below 307: a test that trusted those bases would say prime.
    assert len(str(ARNAULT)) == 397
    assert all(strong_probable_prime(ARNAULT, a) for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53))
    assert value_of(one("is_prime", ARNAULT)) == "false"
    # Past the host's max_prime_digits too: a composite that fails a probable-prime test is answered, exactly.
    assert value_of(one("is_prime", ARNAULT, limits=L.Limits(max_prime_digits=100))) == "false"


def test_a_probable_prime_past_the_hosts_limit_is_refused_never_answered_as_prime():
    answer = one("is_prime", M521, limits=L.Limits(max_prime_digits=100))
    r = answer["refused"]
    assert answer["status"] == "refused" and r["kind"] == "exceeds_limits"
    assert r["limit"] == {"name": "max_prime_digits", "value": 100, "needed_at_least": 157,
                          "setting": "--max-prime-digits or FLO2_CALC_MAX_PRIME_DIGITS"}
    assert (r["node"], r["op"]) == ("r", "is_prime")
    assert "157 digits" in r["reason"] and "not a proof" in r["reason"] and "never answered as prime" in r["reason"]
    assert answer["result"] is None
    # A product of two such primes is past the limit too, and is still answered: false, proven.
    assert value_of(one("is_prime", M521 * M607, limits=L.Limits(max_prime_digits=100))) == "false"


def test_is_prime_over_an_array_stops_at_the_first_element_past_the_limit_naming_it():
    answer = run(inp("x", {"array": ["7", "1"]}), *number_nodes("m", M521), op("y", "mul", "x", "m"), op("p", "is_prime", "y"),
                 limits=L.Limits(max_prime_digits=100))
    r = answer["refused"]
    assert r["limit"]["name"] == "max_prime_digits" and r["limit"]["needed_at_least"] == 157


# ---------------------------------------------------------------- factorize


def legendre(n, p):
    e, q = 0, p
    while q <= n:
        e += n // q
        q *= p
    return e


@pytest.mark.parametrize("n, expected", [
    (2, [[2, 1]]), (4, [[2, 2]]), (12, [[2, 2], [3, 1]]), (1681, [[41, 2]]), (65_521, [[65_521, 1]]),
    (65_537, [[65_537, 1]]), (65_521 * 65_537, [[65_521, 1], [65_537, 1]]), (65_537**2, [[65_537, 2]]),
    (2**64 + 1, [[274_177, 1], [67_280_421_310_721, 1]]),
    (F7, [[59_649_589_127_497_217, 1], [5_704_689_200_685_129_054_721, 1]]),
    (10**100, [[2, 100], [5, 100]]), (M127, [[M127, 1]]), (2 * 3 * M127**2, [[2, 1], [3, 1], [M127, 2]]),
    (M127**6 * 5**3, [[5, 3], [M127, 6]]), (7 * F7**2, [[7, 1], [59_649_589_127_497_217, 2],
                                                        [5_704_689_200_685_129_054_721, 2]]),
])
def test_factorize_gives_each_prime_with_its_multiplicity(n, expected):
    answer = one("factorize", n)
    assert answer["result"]["array"]["kind"] == "exact" and answer["result"]["array"]["shape"] == [len(expected), 2]
    assert grid(answer) == expected
    assert math.prod(p**e for p, e in expected) == n and all(trial_prime(p) for p, _ in expected if p < 10**12)


def test_factorize_of_1000_factorial_is_legendres_formula():
    answer = run(inp("n", "1000"), op("f", "factorial", "n"), op("g", "factorize", "f"))
    primes = [p for p in range(2, 1001) if trial_prime(p)]
    assert grid(answer) == [[p, legendre(1000, p)] for p in primes]


def test_factorize_a_large_number_with_small_factors_whatever_its_size():
    n = 2**5000 * 3**2000 * 65_521**3
    assert grid(one("factorize", n)) == [[2, 5000], [3, 2000], [65_521, 3]]


def test_the_factorization_is_a_grid_the_array_operators_read():
    answer = run(inp("n", "360"), op("f", "factorize", "n"), op("primes", "transpose", "f"), inp("i", "0"), inp("j", "1"),
                 op("e_of_3", "element", "f", "j", "j"), op("rows", "length", "f", axis=0), result=["e_of_3", "rows"])
    assert [r["value"] for r in answer["results"]] == ["2", "3"]


def test_a_composite_part_past_the_hosts_factor_limit_is_refused_never_answered_in_part():
    answer = one("factorize", 2**10 * F7, limits=L.Limits(max_factor_digits=30))
    r = answer["refused"]
    assert answer["status"] == "refused" and r["kind"] == "exceeds_limits"
    assert r["limit"] == {"name": "max_factor_digits", "value": 30, "needed_at_least": 39,
                          "setting": "--max-factor-digits or FLO2_CALC_MAX_FACTOR_DIGITS"}
    assert "39 digits" in r["reason"] and "below 65,536" in r["reason"] and "never answered in part" in r["reason"]
    assert grid(one("factorize", 2**10 * F7, limits=L.Limits(max_factor_digits=39))) == [
        [2, 10], [59_649_589_127_497_217, 1], [5_704_689_200_685_129_054_721, 1]]


def test_a_perfect_power_is_factored_by_its_root_and_only_the_root_is_held_to_the_limit():
    # (274177 F7)^2 has 88 digits; its root has 44, within the laptop's 50 and past flo2.io's 40.
    root = 274_177 * F7
    assert grid(one("factorize", root**2)) == [[274_177, 2], [59_649_589_127_497_217, 2], [5_704_689_200_685_129_054_721, 2]]
    r = one("factorize", root**2, limits=L.FLO2_IO)["refused"]
    assert r["limit"]["name"] == "max_factor_digits" and r["limit"]["needed_at_least"] == len(str(root)) == 44


def test_a_prime_part_past_the_hosts_prime_limit_is_refused():
    r = one("factorize", 6 * M521, limits=L.Limits(max_prime_digits=100))["refused"]
    assert r["limit"]["name"] == "max_prime_digits" and r["limit"]["needed_at_least"] == 157
    # A composite part is not held to the prime limit, only to the factor limit.
    assert grid(one("factorize", 6 * F7, limits=L.Limits(max_prime_digits=30))) == [
        [2, 1], [3, 1], [59_649_589_127_497_217, 1], [5_704_689_200_685_129_054_721, 1]]


@pytest.mark.parametrize("n, words", [(1, "empty product"), (0, "at least 2"), (-12, "factorize its abs")])
def test_factorize_refuses_what_has_no_factorization_into_primes(n, words):
    r = one("factorize", n)["refused"]
    assert r["kind"] == "out_of_domain" and words in r["reason"]


def test_factorize_and_integer_range_take_single_values():
    for name, args in (("factorize", ["x"]), ("integer_range", ["x", "x"])):
        r = run(inp("x", {"array": ["4", "6"]}), op("r", name, *args))["refused"]
        assert r["kind"] == "type_mismatch" and "single whole numbers" in r["reason"]


# ---------------------------------------------------------------- integer_range


@pytest.mark.parametrize("a, b", [(0, 39), (-3, 3), (5, 5), (10**40, 10**40 + 4)])
def test_integer_range_holds_every_whole_number_from_a_to_b(a, b):
    answer = one("integer_range", a, b)
    assert answer["result"]["array"]["kind"] == "exact" and answer["result"]["array"]["shape"] == [b - a + 1]
    assert [integer(x) for x in answer["result"]["array"]["values"]] == list(range(a, b + 1))


def test_an_empty_range_is_refused():
    r = one("integer_range", 5, 3)["refused"]
    assert r["kind"] == "out_of_domain" and "would be empty" in r["reason"]


def test_a_range_past_the_hosts_exact_elements_is_stopped_never_made_float64():
    answer = one("integer_range", 1, 4097, limits=L.FLO2_IO)
    r = answer["refused"]
    assert r["kind"] == "exceeds_limits"
    assert r["limit"] == {"name": "max_exact_elements", "value": 4096, "needed_at_least": 4097,
                          "setting": "--max-exact-elements or FLO2_CALC_MAX_EXACT_ELEMENTS"}
    assert "stays exact" in r["reason"]
    assert one("integer_range", 1, 4096, limits=L.FLO2_IO)["result"]["array"]["shape"] == [4096]


def test_the_range_has_an_absolute_cap_whatever_the_host():
    r = one("integer_range", 0, 1 << 22)["refused"]
    assert r["kind"] == "too_large" and "2,097,152" in r["reason"]


# ---------------------------------------------------------------- every operator: exact inputs only


@pytest.mark.parametrize("name, arity", [("mod", 2), ("divides", 2), ("gcd", 2), ("is_prime", 1), ("factorize", 1),
                                         ("integer_range", 2)])
@pytest.mark.parametrize("bad, kind, words", [
    ("7/2", "out_of_domain", "a whole number"),
    ("2.5", "out_of_domain", "a whole number"),
    ("12 mm", "unit_mismatch", "a plain number"),
    (True, "type_mismatch", "is true"),
])
def test_a_non_integer_argument_is_refused_with_its_reason(name, arity, bad, kind, words):
    nodes = [inp("bad", bad), inp("ok", "12")]
    args = ["bad"] + ["ok"] * (arity - 1)
    answer = run(*nodes, op("r", name, *args))
    r = answer["refused"]
    assert answer["status"] == "refused" and r["node"] == "r" and r["op"] == name
    assert r["kind"] == kind and words in r["reason"] and '"bad"' in r["reason"], r


@pytest.mark.parametrize("name, arity", [("mod", 2), ("divides", 2), ("gcd", 2), ("is_prime", 1), ("factorize", 1),
                                         ("integer_range", 2)])
def test_a_rounded_argument_is_refused_even_when_it_looks_whole(name, arity):
    nodes = [inp("four", "4"), op("two", "sqrt", "four"), inp("x", "2"), op("r2", "sqrt", "x"), op("two_ish", "mul", "r2", "r2")]
    answer = run(*nodes, op("r", name, *(["two_ish"] * arity)))
    r = answer["refused"]
    assert r["kind"] == "out_of_domain" and "rounded value" in r["reason"]


def test_over_exact_arrays_mod_divides_and_gcd_work_element_by_element():
    answer = run(inp("x", {"array": ["10", "-7", "12", "0"]}), inp("y", {"array": ["3", "3", "-5", "4"]}),
                 op("m", "mod", "x", "y"), op("d", "divides", "y", "x"), op("g", "gcd", "x", "y"), result=["m", "d", "g"])
    m, d, g = (r["array"]["values"] for r in answer["results"])
    assert m == ["1", "2", "-3", "0"] and d == ["false", "false", "false", "true"] and g == ["1", "1", "1", "4"]


def test_over_an_array_a_non_integer_element_is_named():
    r = run(inp("x", {"array": ["4", "9/2"]}), op("p", "is_prime", "x"))["refused"]
    assert r["kind"] == "out_of_domain" and "element [1]" in r["reason"]


def test_over_a_float64_array_they_are_refused():
    r = run(inp("x", {"array": ["4", "9"]}), op("s", "sqrt", "x"), op("p", "is_prime", "s"))["refused"]
    assert r["kind"] == "type_mismatch" and "exact values" in r["reason"]


def test_the_trial_division_bound_is_every_prime_below_65536():
    assert len(IN.SMALL_PRIMES) == 6542 and IN.SMALL_PRIMES[-1] == 65_521 and IN.TRIAL_BOUND == 65_536
    assert all(trial_prime(p) for p in IN.SMALL_PRIMES[-50:])


def test_every_integer_operator_is_listed_and_said_to_be_exact():
    for name in ("mod", "divides", "gcd", "is_prime", "factorize", "integer_range"):
        family, *_rest, words = OPS[name]
        assert family == "integers"
        assert "exact" in words


# ---------------------------------------------------------------- the formula


def test_the_formula_writes_mod_divides_gcd_and_the_range_as_mathematics():
    answer = run(inp("a", "17"), inp("b", "5"), op("m", "mod", "a", "b"), op("d", "divides", "b", "a"),
                 op("g", "gcd", "a", "b"), op("r", "integer_range", "b", "a"), result=["m", "d", "g", "r"])
    by_node = {f["node"]: f for f in answer["formula"]}
    assert by_node["m"]["text"] == "m = a mod b = 2" and r"\bmod" in by_node["m"]["latex"]
    assert by_node["d"]["text"] == "d = divides(b, a) = false" and r"\mid" in by_node["d"]["latex"]
    assert r"\gcd" in by_node["g"]["latex"]
    assert r"\ldots" in by_node["r"]["latex"]


# ---------------------------------------------------------------- the record


def test_a_record_of_the_trial_validates_under_the_current_schema_and_re_runs_byte_for_byte():
    g = read_graph(euler_graph(0, 39))
    rec = R.build(evaluate(g), "euler-41", "the primes trial")
    assert rec["schema_version"] == 10
    jsonschema.Draft202012Validator(R.schema()).validate(rec)
    again = R.rerun(R.load(json.loads(R.file_bytes(rec))))
    assert again["reproduces"] is True, again["differences"]


def test_a_factorization_stopped_at_the_limit_is_a_pending_record_a_larger_host_completes():
    g = read_graph(graph(inp("n", str(2**10 * F7), "2^10 F7"), op("f", "factorize", "n")))
    small = L.Limits(max_factor_digits=30)
    ev = evaluate(g, L.Guard(small))
    assert ev.stopped
    pending = R.build_pending(g, "f7", None, ev.refusal, small)
    jsonschema.Draft202012Validator(R.schema()).validate(pending)
    assert pending["limits_in_force"]["max_factor_digits"] == 30 and pending["limits_in_force"]["max_prime_digits"] == 300
    assert "max_factor_digits of at least 39 digits" in R.needs_of(pending["stopped"])
    assert R._room_here(pending["stopped"], L.LAPTOP) and not R._room_here(pending["stopped"], small)
    done = R.build(evaluate(g), "f7", None)
    assert done["result"]["array"]["values"] == [["2", "10"], ["59649589127497217", "1"], ["5704689200685129054721", "1"]]


def test_an_integer_range_stopped_at_the_exact_array_limit_is_a_valid_pending_record():
    g = read_graph(graph(inp("a", "1", "t"), inp("b", "5000", "t"), op("n", "integer_range", "a", "b")))
    ev = evaluate(g, L.Guard(L.FLO2_IO))
    pending = R.build_pending(g, "range", None, ev.refusal, L.FLO2_IO)
    jsonschema.Draft202012Validator(R.schema()).validate(pending)
    assert "max_exact_elements of at least 5,000 elements" in R.needs_of(pending["stopped"])


def test_every_integer_operator_is_in_schema_9_and_none_in_version_8():
    def ops_of(version):
        node = R.schema(version)["$defs"]["graph"]["properties"]["nodes"]["items"]["oneOf"][1]
        return set(node["properties"]["op"]["enum"])

    assert ops_of(9) <= set(OPS)
    assert ops_of(9) - ops_of(8) == {"mod", "divides", "gcd", "is_prime", "factorize", "integer_range"}


# ---------------------------------------------------------------- over MCP


def test_the_trial_over_mcp():
    async def calls():
        async with session() as s:
            answer = answer_of(await s.call_tool("evaluate_graph", {"graph": euler_graph(0, 39)}))
            listed = {t.name: t for t in (await s.list_tools()).tools}
            return answer, json.dumps(listed["evaluate_graph"].input_schema)

    answer, schema_text = anyio.run(calls)
    assert answer["results"][0]["value"] == "true" and answer["results"][1]["value"] == "40"
    for name in ("mod (", "divides (", "gcd (", "is_prime (", "factorize (", "integer_range ("):
        assert name in schema_text


def test_the_evaluator_takes_exactly_the_element_wise_integer_operators_element_by_element():
    from flo2_calc.evaluator import PER_ELEMENT

    assert set(IN.ELEMENT_WISE) <= PER_ELEMENT and not set(IN.SINGLE) & PER_ELEMENT
