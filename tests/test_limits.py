"""Host-set limits: a deadline, a digits budget and a reply budget, each tripping with its reason.

ver:each-limit-stops-with-its-reason and ver:a-huge-power-is-refused-before-it-stalls in
design 0bee0c00b35845f6 (cap:a-calculation-is-stopped-at-the-hosts-limits). The
server tests here also run against the image under flo2's sandbox flags with a
128m cap (CI's image job, FLO2_CALC_SERVER), where the image's own limits are
flo2.io's profile: so they read the limits in force from each reply rather
than assume them, and they check that the confined container stays alive and
answers the next call after every stop.
"""

from __future__ import annotations

import json
import subprocess
import time
from fractions import Fraction

import anyio
import pytest
from conftest import answer_of, graph, inp, installed_command, op, session, text_of, under_image

from flo2_calc import limits as L
from flo2_calc.evaluator import evaluate, evaluation_json, read_graph

# ---------------------------------------------------------------- helpers


def run(g, limits=L.LAPTOP, clock=None):
    guard = L.Guard(limits) if clock is None else L.Guard(limits, clock=clock)
    return evaluation_json(evaluate(read_graph(g), guard))


def stopped(g, limits=L.LAPTOP, clock=None):
    answer = run(g, limits, clock)
    assert answer["status"] == "refused", answer
    r = answer["refused"]
    assert r["kind"] == "exceeds_limits", r
    assert answer["result"] is None
    return r


def squarings(n: int, start: str = "123456789012345678901234567890") -> dict:
    """x, x^2, x^4, ... by multiplying each by itself: the digits double every node."""
    nodes = [inp("x0", start)]
    for i in range(1, n + 1):
        nodes.append(op(f"x{i}", "mul", f"x{i - 1}", f"x{i - 1}"))
    return graph(*nodes)


def heavy_graph(n: int = 500) -> dict:
    """tools/measure.py's 500-node chain: additions and multiplications whose fractions grow to a few hundred digits."""
    nodes = [inp("x0", "1.5 mm"), inp("d", "1/3 mm"), inp("c", "7/5")]
    i = 0
    while len(nodes) < n - 1:
        i += 1
        nodes.append(op(f"x{i}", "add", f"x{i - 1}", "d") if i % 2 else op(f"x{i}", "mul", f"x{i - 1}", "c"))
    nodes.append(op("bigger", "gt", f"x{i}", "x0"))
    return graph(*nodes)


# ---------------------------------------------------------------- the settings (option d)


def test_the_defaults_suit_a_laptop_and_flo2_io_has_a_lower_profile():
    assert L.from_settings(None, None, None) == L.LAPTOP == L.Limits(45_000, 20_000, 8 * 1024 * 1024)
    assert L.FLO2_IO == L.Limits(20_000, 2_000, 2 * 1024 * 1024, 16 * 1024 * 1024, 4_096)
    assert L.LAPTOP.max_array_bytes == 512 * 1024 * 1024
    for field in ("deadline_ms", "max_digits", "max_reply_bytes", "max_array_bytes"):
        assert getattr(L.FLO2_IO, field) < getattr(L.LAPTOP, field), field
    # flo2's gateway stops a helper call at 60 s (CAD_CALL_MS, DEFAULT_CALL_MS), and the MCP
    # TypeScript SDK's clients at 60 s too: both deadlines answer well before either gives up.
    assert L.LAPTOP.deadline_ms < 60_000 and L.FLO2_IO.deadline_ms <= 60_000 // 3
    assert L.FLO2_IO.describe() == {"deadline": "20 s", "max_digits": 2000, "max_reply_bytes": 2097152, "max_array_bytes": 16777216,
                                    "max_exact_elements": 4096}


@pytest.mark.parametrize("text, ms", [("20", 20_000), ("0.5", 500), ("20 s", 20_000), ("0.001", 1), ("86400", 86_400_000)])
def test_a_deadline_is_read_as_seconds(text, ms):
    assert L.parse_deadline(text) == ms
    assert L.from_settings(text, None, None).deadline_ms == ms


@pytest.mark.parametrize("deadline, digits, reply, words", [
    ("abc", None, None, "--deadline (or FLO2_CALC_DEADLINE)"),
    ("0", None, None, "0.001 to 86400"),
    ("0.0005", None, None, "whole milliseconds"),
    (None, "5", None, "--max-digits (or FLO2_CALC_MAX_DIGITS)"),
    (None, "200000", None, "10 to 100,000"),
    (None, "2e3", None, "a whole number"),
    (None, None, "100", "--max-reply-bytes (or FLO2_CALC_MAX_REPLY_BYTES)"),
])
def test_a_setting_flo2_calc_cannot_use_is_refused_with_its_name(deadline, digits, reply, words):
    with pytest.raises(ValueError) as caught:
        L.from_settings(deadline, digits, reply)
    assert words in str(caught.value)


def test_the_command_stops_at_start_up_on_a_bad_setting_saying_which():
    out = subprocess.run([installed_command(), "--max-digits", "5"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert out.returncode != 0
    assert "--max-digits (or FLO2_CALC_MAX_DIGITS)" in out.stderr
    assert out.stdout == "", "nothing but MCP messages reaches stdout"
    env_out = subprocess.run([installed_command()], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                             env={"PATH": "/usr/bin:/bin", "FLO2_CALC_DEADLINE": "soon"})
    assert env_out.returncode != 0 and "FLO2_CALC_DEADLINE" in env_out.stderr


# ---------------------------------------------------------------- the digits budget (option b)


def test_a_value_past_the_digits_budget_is_stopped_naming_the_node_the_limit_and_the_size():
    r = stopped(squarings(6), L.Limits(max_digits=200))
    # x0 has 30 digits, x1 59, x2 117, x3 233: x3 is the first past 200.
    assert (r["node"], r["op"]) == ("x3", "mul")
    assert r["limit"] == {"name": "max_digits", "value": 200, "needed_at_least": 233, "setting": "--max-digits or FLO2_CALC_MAX_DIGITS"}
    assert r["reached"]["nodes_done"] == 3 and r["reached"]["nodes"] == 7
    assert r["reached"]["largest_digits"] == 233
    assert r["limits"] == {"deadline": "45 s", "max_digits": 200, "max_reply_bytes": 8388608, "max_array_bytes": 536870912,
                           "max_exact_elements": 65536}
    assert 'mul at node "x3": the product has a numerator of 233 digits' in r["reason"]
    assert "budget of 200 digits" in r["reason"] and "stopped cleanly" in r["reason"]


def test_the_values_before_the_stop_are_still_reported():
    answer = run(squarings(6), L.Limits(max_digits=200))
    assert [v["node"] for v in answer["values"]] == ["x0", "x1", "x2"]


def test_an_input_past_the_digits_budget_is_stopped_at_that_input():
    r = stopped(graph(inp("big", "1e1000"), inp("one", "1"), op("s", "add", "big", "one")), L.Limits(max_digits=500))
    assert r["node"] == "big" and r["op"] is None
    assert r["limit"]["needed_at_least"] == 1001
    assert r["reason"].startswith('input "big": the value has a numerator of 1,001 digits')


def test_a_partial_product_is_held_to_the_budget_so_no_step_runs_long():
    """A product of 100 arguments is computed and checked one argument at a time:
    the step that passes the budget is the one that stops it."""
    x = "9" * 80
    nodes = [inp(f"a{i}", x) for i in range(100)] + [op("p", "mul", *[f"a{i}" for i in range(100)])]
    r = stopped(graph(*nodes), L.Limits(max_digits=1000))
    assert r["node"] == "p"
    assert "partial product (of the first 13 arguments)" in r["reason"], r["reason"]  # 13 * 80 = 1040 digits


def test_a_long_sum_is_held_to_the_budget_step_by_step():
    """Adding fractions with coprime denominators grows the denominator like a product."""
    primes = [1009, 1013, 1019, 1021, 1031, 1033, 1039, 1049, 1051, 1061, 1063, 1069, 1087, 1091, 1093, 1097, 1103, 1109,
              1117, 1123, 1129, 1151, 1153, 1163, 1171, 1181, 1187, 1193, 1201, 1213]
    nodes = [inp(f"f{i}", f"1/{p}") for i, p in enumerate(primes)] + [op("s", "add", *[f"f{i}" for i in range(len(primes))])]
    r = stopped(graph(*nodes), L.Limits(max_digits=50))
    assert r["node"] == "s" and "partial sum" in r["reason"] and "denominator" in r["reason"]


def test_one_e_1000_to_the_fifth_is_exact_or_stopped_never_a_crash():
    """v0.1 failed here ("failed unexpectedly"): a 5,001-digit value passed its
    20,000-bit cap, then Python refused to write it out (its 4,300-digit limit)."""
    g = graph(inp("x", "1e1000"), inp("n", "5"), op("p", "pow", "x", "n"))
    assert run(g)["result"]["value"] == "1e+5000"
    r = stopped(g, L.FLO2_IO)
    assert r["node"] == "p" and 2000 < r["limit"]["needed_at_least"] <= 5001


def test_a_rounded_value_of_thousands_of_digits_carries_its_exact_fraction_in_full():
    g = graph(inp("t", "2/3"), inp("n", "1000"), op("p", "pow", "t", "n"), op("q", "mul", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p", "p"))
    answer = run(g)
    assert answer["status"] == "ok", answer
    exact = answer["result"]["exact"]
    num, den = exact.split("/")
    assert Fraction(int(num), int(den)) == Fraction(2, 3) ** 19000
    assert len(den) == L.digits(3**19000) > 4300, "past the 4,300 digits Python writes by default"


# ---------------------------------------------------------------- a huge power, refused before it stalls


def test_a_huge_power_is_refused_before_it_is_computed():
    """y has 20,000 digits (inside the laptop budget); y ^ 1000 would have about
    20 million. Computed, that one Python operation takes about 44 s on one CPU
    and cannot be interrupted (measured 2026-10-04: a 20,000-digit number to the
    power 1000, 44.2 s). Sized from its operands first, it is refused at once."""
    g = graph(inp("x", "9" * 80), inp("e1", "250"), op("y", "pow", "x", "e1"), inp("e2", "1000"), op("z", "pow", "y", "e2"))
    started = time.perf_counter()
    r = stopped(g)
    took = time.perf_counter() - started
    assert took < 2, f"refused in {took:.2f} s: it was computed, not sized"
    assert (r["node"], r["op"]) == ("z", "pow")
    assert r["reached"]["largest_digits"] == 20_000
    assert r["limit"]["name"] == "max_digits" and r["limit"]["needed_at_least"] > 19_000_000
    assert "would have at least" in r["reason"] and "so it was not computed" in r["reason"]


@pytest.mark.parametrize("base, n", [("2", 997), ("3", 999), ("1/7", 1000), ("123456789", 977), ("99999/100000", 951), ("12345678901234567890", -999)])
def test_the_size_of_a_power_is_never_overestimated(base, n):
    """The bound refuses only a power that really would pass the budget."""
    actual = Fraction(base) ** n
    biggest = max(L.digits(actual.numerator), L.digits(actual.denominator))
    b = Fraction(base)
    num, den = (b.numerator, b.denominator) if n >= 0 else (b.denominator, b.numerator)
    bound = max(L.power_digits_at_least(num, abs(n)), L.power_digits_at_least(den, abs(n)))
    assert bound <= biggest
    assert bound >= biggest * 0.6, "close enough to refuse early"
    just_fits = L.Limits(max_digits=biggest)
    g = graph(inp("b", base), inp("n", str(n)), op("p", "pow", "b", "n"))
    assert run(g, just_fits)["status"] == "ok"
    assert stopped(g, L.Limits(max_digits=biggest - 1))["node"] == "p"


def test_a_power_of_a_percentage_is_sized_after_the_percent_is_folded_in():
    """(10 %)^1000 is 0.1^1000: 10^-1000, not 10^1000 / 100^1000 sized as 10^1000."""
    g = graph(inp("p", "10 %"), inp("n", "1000"), op("q", "pow", "p", "n"))
    assert run(g, L.Limits(max_digits=1001))["result"]["value"] == "1e-1000"


@pytest.mark.parametrize("n", [0, 1, 2, 9, 10, 99, 100, 10**40 - 1, 10**40, 3**5000, 10**5000, 10**5000 - 1],
                         ids=["0", "1", "2", "9", "10", "99", "100", "1e40-1", "1e40", "3^5000", "1e5000", "1e5000-1"])
def test_digits_are_counted_exactly_without_writing_the_number_out(n):
    import sys

    sys.set_int_max_str_digits(0)
    assert L.digits(n) == len(str(n)) == L.digits(-n)


# ---------------------------------------------------------------- the deadline


def test_the_deadline_is_checked_before_every_node():
    ticks = iter(range(0, 10**15, 10**9))  # one second passes at every look at the clock
    r = stopped(squarings(6), L.Limits(deadline_ms=2500), clock=lambda: next(ticks))
    assert r["limit"] == {"name": "deadline", "value": "2.5 s", "setting": "--deadline or FLO2_CALC_DEADLINE"}
    assert r["node"] == "x1" and r["reached"]["nodes_done"] == 1
    assert "passed this host's deadline of 2.5 s at node \"x1\" (mul), after 1 of 7 nodes" in r["reason"]
    assert r["reached"]["elapsed"] == "4 s"


def test_the_deadline_is_checked_while_the_reply_is_written():
    ticks = iter(range(0, 10**15, 10**8))  # 0.1 s at every look
    guard = L.Guard(L.Limits(deadline_ms=1000), clock=lambda: next(ticks))
    ev = evaluate(read_graph(graph(*[inp(f"a{i}", str(i)) for i in range(5)])), guard)
    assert ev.ok
    answer = evaluation_json(ev)
    assert answer["status"] == "refused" and answer["refused"]["limit"]["name"] == "deadline"
    assert "while writing the reply" in answer["refused"]["reason"]


# ---------------------------------------------------------------- over the client, and in the confined image


async def _calls(extra, steps):
    out = []
    async with session(*extra) as s:
        for tool, args in steps:
            out.append(await s.call_tool(tool, args))
    return out


def calls(steps, *extra):
    return anyio.run(_calls, extra, steps)


ALIVE = ("evaluate_graph", {"graph": graph(inp("a", "0.1"), inp("b", "0.2"), op("s", "add", "a", "b"))})


def assert_alive(result):
    assert answer_of(result)["result"] == {"node": "s", "value": "0.3"}, "the server answered the next call"


def test_runaway_calculations_are_stopped_with_their_reason_and_the_server_stays_alive():
    """In the image under flo2's sandbox flags and a 128m cap (CI), as on a laptop."""
    runaway_pow = graph(inp("x", "9" * 80), inp("e1", "250"), op("y", "pow", "x", "e1"), inp("e2", "1000"), op("z", "pow", "y", "e2"))
    runaway_chain = squarings(30)
    pow_r, chain_r, alive = calls([
        ("evaluate_graph", {"graph": runaway_pow}),
        ("evaluate_graph", {"graph": runaway_chain}),
        ALIVE,
    ])
    for r in (pow_r, chain_r):
        assert r.is_error is False, "passing a limit is a normal reply, never isError"
        answer = answer_of(r)
        assert answer["status"] == "refused" and answer["refused"]["kind"] == "exceeds_limits"
        assert answer["refused"]["limit"]["name"] == "max_digits"
        assert answer["refused"]["limits"]["max_digits"] == answer["refused"]["limit"]["value"]
    assert answer_of(pow_r)["refused"]["op"] == "pow"
    assert answer_of(chain_r)["refused"]["node"].startswith("x")
    assert_alive(alive)


def test_the_limits_in_force_are_told_to_the_agent_in_the_servers_instructions():
    from flo2_calc.server import build_server

    server = build_server(None, L.Limits(max_digits=777))
    assert "at most 777 digits in any exact numerator or denominator" in server.instructions


def test_the_deadline_stops_a_call_over_the_client():
    r, alive = calls([("evaluate_graph", {"graph": heavy_graph()}), ALIVE], "--deadline", "0.001")
    answer = answer_of(r)
    assert answer["status"] == "refused", "a 500-node graph cannot answer in a millisecond"
    assert answer["refused"]["limit"] == {"name": "deadline", "value": "0.001 s", "setting": "--deadline or FLO2_CALC_DEADLINE"}
    assert "deadline of 0.001 s" in answer["refused"]["reason"]
    assert answer_of(alive)["status"] in ("ok", "refused"), "the server answered the next call"


def test_the_reply_budget_stops_a_reply_too_large_to_send():
    g = squarings(5)  # values of 30 to 474 digits, each written out exactly
    small = calls([("evaluate_graph", {"graph": g})], "--max-reply-bytes", "1024")[0]
    answer = answer_of(small)
    assert answer["status"] == "refused" and answer["values"] is None
    r = answer["refused"]
    assert r["limit"]["name"] == "max_reply_bytes" and r["limit"]["value"] == 1024
    assert r["limit"]["needed_at_least"] > 1024
    assert len(text_of(small).encode("utf-8")) < 4096, "the refusal itself is small"
    roomy = calls([("evaluate_graph", {"graph": g})], "--max-reply-bytes", "65536")[0]
    assert answer_of(roomy)["status"] == "ok"


def test_add_node_past_a_limit_does_not_add_the_node():
    before = squarings(2)
    r = calls([("add_node", {"graph": before, "node": op("x3", "mul", "x2", "x2")})], "--max-digits", "200")[0]
    answer = answer_of(r)
    assert answer["status"] == "refused" and answer["refused"]["kind"] == "exceeds_limits"
    assert answer["refused"]["node"] == "x3"
    assert answer["graph"] == before and "not added" in answer["note"]


def test_rerun_of_a_record_larger_than_the_reply_budget_is_refused_as_a_limit_not_an_error():
    made = calls([("record_computation", {"graph": graph(*[inp(f"v{i}", str(i), "t") for i in range(60)]), "name": "wide"})])[0]
    assert answer_of(made)["status"] == "ok"
    record_text = made.content[1].resource.text
    assert len(record_text) > 2000
    r = calls([("rerun_record", {"record": record_text})], "--max-reply-bytes", "2000")[0]
    answer = answer_of(r)
    assert answer["status"] == "refused" and answer["refused"]["limit"]["name"] == "max_reply_bytes"


@pytest.mark.skipif(not under_image(), reason="the memory question is the confined image's (CI's image job, 128m)")
def test_the_heaviest_legal_work_fits_in_the_confined_container():
    """500 nodes, every value about 1,900 digits (inside flo2.io's 2,000), each
    written out exactly: the most the hosted profile lets one call hold. The
    container answers each call (a result, or a stop at the reply budget with a
    not-yet-computed record) and is still alive afterwards: no sandbox kill."""
    nodes = [inp("x0", "9" * 80, "t"), inp("e", "23", "t"), op("y0", "pow", "x0", "e"), inp("one", "1/7", "t")]
    for i in range(1, 497):
        nodes.append(op(f"y{i}", "add", f"y{i - 1}", "one"))
    g = graph(*nodes)
    evaluated, recorded, alive = calls([
        ("evaluate_graph", {"graph": g}),
        ("record_computation", {"graph": g, "name": "heaviest"}),
        ALIVE,
    ])
    for r in (evaluated, recorded):
        answer = answer_of(r)
        assert answer["status"] == "ok" or answer["refused"]["kind"] == "exceeds_limits", json.dumps(answer)[:500]
    rec = answer_of(recorded)
    if rec["status"] == "refused":
        assert rec["record"]["status"] == "not_computed"
    assert_alive(alive)


def test_rounded_runaway_calculations_are_stopped_with_their_reason_and_the_server_stays_alive():
    """An exponential, a far tail and a precision past any budget: each stopped
    by flo2-calc, never by the sandbox, and the next call is answered."""
    exp_r, tail_r, alive = calls([
        ("evaluate_graph", {"graph": graph(inp("x", "1e5"), op("y", "exp", "x"))}),
        ("evaluate_graph", {"graph": graph(inp("x", "1e6"), op("q", "normal_sf", "x"))}),
        ALIVE,
    ])
    for r in (exp_r, tail_r):
        answer = answer_of(r)
        assert answer["status"] == "refused" and answer["refused"]["kind"] == "exceeds_limits"
        assert answer["refused"]["limit"]["name"] == "max_digits"
    assert_alive(alive)
    precise, alive = calls([("evaluate_graph", {"graph": graph(inp("x", "2"), op("s", "sqrt", "x", digits=1000))}), ALIVE],
                           "--max-digits", "500")
    answer = answer_of(precise)
    assert answer["refused"]["limit"]["name"] == "max_digits" and "working precision" in answer["refused"]["reason"]
    assert_alive(alive)


@pytest.mark.skipif(not under_image(), reason="the memory question is the confined image's (CI's image job, 128m)")
def test_the_heaviest_rounded_work_fits_in_the_confined_container():
    """Every rounded operator at 1,000 digits, 480 nodes of them, sent whole
    and recorded under flo2.io's profile: answered (or stopped at a limit with
    its reason), and the container is still alive."""
    nodes = [inp("x", "0.7", "t"), inp("p", "0.975", "t"), inp("k", "4", "t"), inp("a", "37.5 deg", "t")]
    kinds = [("sqrt", ["x"], {}), ("exp", ["x"], {}), ("ln", ["x"], {}), ("sin", ["a"], {}), ("atan", ["x"], {"unit": "rad"}),
             ("normal_quantile", ["p"], {}), ("chi2_sf", ["x", "k"], {}), ("t_quantile", ["p", "k"], {})]
    for i in range(480):
        name, args, extra = kinds[i % len(kinds)]
        nodes.append(op(f"n{i}", name, *args, digits=1000, **extra))
    g = graph(*nodes)
    evaluated, recorded, alive = calls([
        ("evaluate_graph", {"graph": g}),
        ("record_computation", {"graph": g, "name": "heaviest-rounded"}),
        ALIVE,
    ])
    for r in (evaluated, recorded):
        answer = answer_of(r)
        assert answer["status"] == "ok" or answer["refused"]["kind"] == "exceeds_limits", json.dumps(answer)[:500]
    assert_alive(alive)
