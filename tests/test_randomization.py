"""The randomization test of an on/off trial: an exact p-value over every arrangement the stated scheme allows.

req:randomization-test-for-on-off-trials and cap:a-randomization-test-gives-an-on-off-trials-exact-p-value
in design 0bee0c00b35845f6 (flo2-calc 0.8.0, dec:v0-8-0-bayes-randomization-shapley-choices,
choices 3 and 5). Each p-value is checked against an INDEPENDENT enumeration written here:
every set of on periods (or every flip of the pairs) listed by index, each one's difference of
means computed afresh as exact fractions, and compared with the observed one in the direction
asked. None of scheme, statistic or alternative is ever defaulted; past max_arrangements the
test is refused before it starts.
"""

from __future__ import annotations

import itertools
from fractions import Fraction
from typing import Any

import jsonschema
import pytest
from conftest import graph, inp, op

from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph
from flo2_calc.numbers import parse_number


def run(*nodes, limits=L.LAPTOP, result=None):
    return evaluation_json(evaluate(read_graph(graph(*nodes, result=result)), L.Guard(limits)))


def rt_node(**fields: Any) -> dict:
    base = {"scheme": "every_arrangement", "statistic": "mean_difference", "alternative": "two_sided"}
    base.update(fields)
    return op("p", "randomization_test", "y", "on", **base)


def trial(y: list[str], on: list[bool], unit: str = "") -> list[dict]:
    value: dict[str, Any] = {"array": y}
    if unit:
        value["unit"] = unit
    return [inp("y", value, "outcome per period"), inp("on", {"array": on}, "the randomized assignment")]


def mean_difference(y: list[Fraction], on: tuple[bool, ...]) -> Fraction:
    a = [v for v, o in zip(y, on) if o]
    b = [v for v, o in zip(y, on) if not o]
    return sum(a, Fraction(0)) / len(a) - sum(b, Fraction(0)) / len(b)


def oracle(y: list[str], on: list[bool], scheme: str, alternative: str) -> tuple[Fraction, int, int]:
    """(p, as extreme, arrangements) by listing every arrangement the scheme allows."""
    ys = [parse_number(v) for v in y]
    n, k = len(ys), sum(on)
    if scheme == "every_arrangement":
        arrangements = [tuple(i in c for i in range(n)) for c in itertools.combinations(range(n), k)]
    else:
        arrangements = []
        for flips in itertools.product((0, 1), repeat=n // 2):
            arrangements.append(tuple(bool((i % 2) ^ flips[i // 2]) for i in range(n)))
    obs = mean_difference(ys, tuple(on))
    hits = 0
    for a in arrangements:
        t = mean_difference(ys, a)
        hits += {"greater": t >= obs, "less": t <= obs, "two_sided": abs(t) >= abs(obs)}[alternative]
    return Fraction(hits, len(arrangements)), hits, len(arrangements)


PAIN = (["6", "4", "3", "7", "2", "6", "5", "3"], [False, True, True, False, True, False, False, True])
SLEEP = (["6.5", "7.2", "7.0", "6.1", "6.8", "7.5", "7.4", "6.6", "6.2", "6.9"],
         [False, True, True, False, False, True, True, False, False, True])
FATIGUE = (["5.1", "6.3", "4.8", "6.9", "5.5", "6.1", "4.9", "6.6", "5.8", "5.2", "6.4", "5.0"],
           [False, True, False, True, False, True, False, True, True, False, True, False])
CASES = [(PAIN, "every_arrangement", a) for a in ("greater", "less", "two_sided")] + \
        [(SLEEP, "within_pairs", a) for a in ("greater", "less", "two_sided")] + \
        [(SLEEP, "every_arrangement", "two_sided"), (FATIGUE, "every_arrangement", "two_sided"), (FATIGUE, "every_arrangement", "less")]


@pytest.mark.parametrize("data, scheme, alternative", CASES, ids=[f"{len(c[0][0])}-{c[1]}-{c[2]}" for c in CASES])
def test_the_p_value_is_exact_and_matches_an_independent_enumeration(data, scheme, alternative):
    y, on = data
    answer = run(*trial(y, on, "h"), rt_node(scheme=scheme, alternative=alternative))
    assert answer["status"] == "ok", answer
    p, hits, total = oracle(y, on, scheme, alternative)
    r = answer["result"]
    assert parse_number((r.get("exact") or r["value"])) == p and "rounded" not in r
    detail = {d["name"]: d["value"] for d in r["detail"]}
    assert detail["as_extreme"] == str(hits) and detail["arrangements"] == str(total)
    assert detail["observed"].endswith(" h")


def test_the_pain_trial_of_round_4_is_one_in_seventy():
    answer = run(*trial(*PAIN), rt_node(alternative="less"))
    assert answer["result"]["exact"] == "1/70"
    step = next(w for w in answer["working"] if w["node"] == "p")
    assert "observed = -3" in step["text"] and "as_extreme = 1" in step["text"] and "arrangements = 70" in step["text"]
    line = {f["node"]: f["text"] for f in answer["formula"]}["p"]
    assert line.startswith("p = randomization_test(y, on; scheme=every_arrangement, statistic=mean_difference, alternative=less)")


def test_the_scheme_changes_the_p_value_so_it_is_never_assumed():
    within = run(*trial(*SLEEP), rt_node(scheme="within_pairs"))["result"]
    every = run(*trial(*SLEEP), rt_node(scheme="every_arrangement"))["result"]
    assert within["value"] == "0.0625" and within["value"] != every["value"]


@pytest.mark.parametrize("missing", ["scheme", "statistic", "alternative"])
def test_scheme_statistic_and_alternative_are_never_defaulted(missing):
    node = rt_node()
    del node[missing]
    with pytest.raises(CallError) as caught:
        read_graph(graph(*trial(*PAIN), node))
    assert caught.value.path == f"graph.nodes[2].{missing}" and "never" in caught.value.problem


@pytest.mark.parametrize("field, value", [("scheme", "random"), ("statistic", "median_difference"), ("alternative", "one_sided")])
def test_an_unknown_scheme_statistic_or_alternative_is_named(field, value):
    with pytest.raises(CallError) as caught:
        read_graph(graph(*trial(*PAIN), rt_node(**{field: value})))
    assert caught.value.path == f"graph.nodes[2].{field}" and repr(value) in caught.value.problem


def test_only_the_randomization_test_takes_its_fields():
    with pytest.raises(CallError) as caught:
        read_graph(graph(inp("a", "1"), op("b", "neg", "a", scheme="within_pairs")))
    assert caught.value.path == "graph.nodes[1].scheme"


@pytest.mark.parametrize("y, on, kind, words", [
    (["1", "2", "3"], [True, False], "shape_mismatch", "the same length"),
    (["1", "2", "3", "4"], [True, True, True, True], "undefined", "on and at least one off"),
    (["1", "2", "3"], [True, False, True], "out_of_domain", "an even number"),
    (["1", "2", "3", "4"], [True, True, False, False], "out_of_domain", "periods 1 and 2"),
])
def test_a_trial_the_scheme_cannot_take_is_refused_with_its_reason(y, on, kind, words):
    scheme = "every_arrangement" if kind in ("shape_mismatch", "undefined") else "within_pairs"
    answer = run(*trial(y, on), rt_node(scheme=scheme))
    assert answer["status"] == "refused", answer
    assert answer["refused"]["kind"] == kind and words in answer["refused"]["reason"], answer["refused"]


@pytest.mark.parametrize("nodes, kind", [
    ([inp("y", "3"), inp("on", {"array": [True, False]})], "type_mismatch"),
    ([inp("y", {"array": ["1", "2"]}), inp("on", {"array": ["1", "0"]})], "type_mismatch"),
    ([inp("y", {"array": ["20", "21"], "unit": "degC"}), inp("on", {"array": [True, False]})], "offset_temperature"),
])
def test_outcomes_must_be_exact_numbers_and_on_a_true_false_array(nodes, kind):
    answer = run(*nodes, rt_node())
    assert answer["status"] == "refused" and answer["refused"]["kind"] == kind, answer


def test_past_max_arrangements_the_test_is_refused_before_it_starts():
    y = [str(i) for i in range(24)]
    on = [i % 2 == 0 for i in range(24)]  # C(24, 12) = 2,704,156 arrangements
    answer = run(*trial(y, on), rt_node(), limits=L.Limits(max_arrangements=1_000_000))
    r = answer["refused"]
    assert r["kind"] == "exceeds_limits" and r["limit"]["name"] == "max_arrangements"
    assert r["limit"]["needed_at_least"] == 2_704_156 and r["limit"]["setting"] == "--max-arrangements or FLO2_CALC_MAX_ARRANGEMENTS"
    assert "2,704,156 arrangements" in r["reason"] and r["reached"]["elapsed"] is not None


def test_the_deadline_stops_a_long_enumeration_cleanly():
    """C(24, 12) = 2,704,156 arrangements, within the laptop's max_arrangements, take
    about 1.7 s: a 0.3 s deadline stops the enumeration itself, at its node."""
    y = [str(i) for i in range(24)]
    on = [i % 2 == 0 for i in range(24)]
    answer = run(*trial(y, on), rt_node(), limits=L.Limits(deadline_ms=300))
    r = answer["refused"]
    assert r["limit"]["name"] == "deadline" and r["node"] == "p" and r["op"] == "randomization_test"


def test_a_stopped_test_comes_back_not_yet_computed_and_completes_on_a_larger_host():
    y = [str(i) for i in range(16)]
    on = [i % 3 == 0 for i in range(16)]
    g = read_graph(graph(*trial(y, on), rt_node()))
    small = L.Limits(max_arrangements=1000)
    ev = evaluate(g, L.Guard(small))
    assert ev.stopped
    pending = R.build_pending(g, "trial", None, ev.refusal, small)
    jsonschema.Draft202012Validator(R.schema()).validate(pending)
    assert pending["limits_in_force"]["max_arrangements"] == 1000
    assert "max_arrangements of at least 8,008 arrangements" in R.needs_of(pending["stopped"])
    direct = R.build(evaluate(g), "trial", None)
    assert R.rerun(direct)["reproduces"] is True
