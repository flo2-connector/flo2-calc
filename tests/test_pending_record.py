"""The not-yet-computed record: made when a recorded calculation passes a limit, completed on a larger machine.

ver:a-pending-record-completes-to-the-direct-record and
ver:a-tampered-pending-record-is-caught in design 0bee0c00b35845f6
(cap:a-not-yet-computed-record-is-completed-on-a-larger-machine), and
ver:a-version-1-record-still-re-runs. A "small machine" here is a flo2-calc
started with low limits (--max-digits 100, --deadline 0.001, a small reply
budget); the "larger machine" is one with the defaults (the laptop's, or, in
CI's image job, flo2.io's profile, which is still far above the small one).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import anyio
import jsonschema
import pytest
from conftest import answer_of, graph, inp, op, reason_of, session

from flo2_calc import __version__
from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc.evaluator import evaluate, read_graph

DATA = Path(__file__).parent / "data"

# A margin computed through a chain of squarings: exact, and its numbers grow to
# about 500 digits, past a small machine's budget of 100 and inside any other.
GROWING = graph(
    inp("ratio", "1234567/1000000", {"design_node": "con:gain-per-stage", "design": "83d2b0775fe79af6"}),
    op("r2", "mul", "ratio", "ratio"),
    op("r4", "mul", "r2", "r2"),
    op("r8", "mul", "r4", "r4"),
    op("r16", "mul", "r8", "r8"),
    op("r32", "mul", "r16", "r16"),
    op("r64", "mul", "r32", "r32"),
    inp("limit", "1e6", "requirement: the gain stays under a million"),
    op("under", "lt", "r64", "limit"),
    result="under",
)
SUPPORTS = {"design_node": "dec:stage-count"}
SMALL = L.Limits(max_digits=100)


def pending_of(g=GROWING, limits=SMALL, name="stage-gain", supports=SUPPORTS):
    ev = evaluate(read_graph(g), L.Guard(limits))
    assert ev.stopped, ev.refusal
    return R.build_pending(ev.graph, name, supports, ev.refusal, limits)


def direct_of(g=GROWING, name="stage-gain", supports=SUPPORTS):
    ev = evaluate(read_graph(g))
    assert ev.ok, ev.refusal
    return R.build(ev, name, supports)


# ---------------------------------------------------------------- what a not-yet-computed record holds


def test_a_pending_record_holds_the_graph_the_inputs_and_the_limit_and_no_result():
    rec = pending_of()
    assert rec["record_format"] == "flo2-calc computation record"
    assert rec["schema_version"] == 4 and rec["status"] == "not_computed"
    assert rec["graph"] == GROWING
    assert rec["supports"] == SUPPORTS
    assert "values" not in rec and "result" not in rec, "no values and no result"
    by_id = {i["id"]: i for i in rec["inputs"]}
    assert by_id["ratio"]["source"] == {"design_node": "con:gain-per-stage", "design": "83d2b0775fe79af6"}
    assert by_id["limit"] == {"id": "limit", "value": "1000000", "unit": "", "source": "requirement: the gain stays under a million"}
    stopped = rec["stopped"]
    # ratio has 7 digits, and each squaring doubles them: r32 is the first past 100, with 195.
    assert stopped["limit"] == {"name": "max_digits", "value": 100, "needed_at_least": 195}
    assert (stopped["node"], stopped["op"]) == ("r32", "mul")
    assert stopped["reached"] == {"nodes_done": 5, "nodes": 9, "largest_digits": 195}
    assert "budget of 100 digits" in stopped["reason"]
    assert rec["limits_in_force"] == {"deadline": "45 s", "max_digits": 100, "max_reply_bytes": 8388608, "max_array_bytes": 536870912}
    assert rec["produced_by"]["flo2_calc"] == __version__
    assert rec["content_hash"] == R.content_hash(rec)
    jsonschema.Draft202012Validator(R.schema()).validate(rec)


def test_the_same_stop_gives_a_byte_identical_pending_record():
    assert R.file_bytes(pending_of()) == R.file_bytes(pending_of(copy.deepcopy(GROWING)))


def test_a_computed_record_validates_and_a_pending_one_cannot_carry_a_result():
    v = jsonschema.Draft202012Validator(R.schema())
    assert v.is_valid(direct_of())
    with_result = pending_of()
    with_result["result"] = {"node": "under", "value": "true"}
    assert not v.is_valid(with_result)
    computed_without = direct_of()
    del computed_without["result"]
    assert not v.is_valid(computed_without)
    claims_computed = pending_of()
    claims_computed["status"] = "computed"
    assert not v.is_valid(claims_computed)


# ---------------------------------------------------------------- completed on a larger machine


def complete_in_process(pending, limits=L.LAPTOP):
    """What record_computation does with a pending record, without the transport."""
    g = read_graph(pending["graph"], "record.graph")
    ev = evaluate(g, L.Guard(limits))
    assert ev.ok, ev.refusal
    return R.build(ev, pending["name"], pending.get("supports"))


def test_completing_a_pending_record_gives_the_direct_record_byte_for_byte():
    completed = complete_in_process(pending_of())
    direct = direct_of()
    assert R.file_bytes(completed) == R.file_bytes(direct)
    assert completed["content_hash"] == direct["content_hash"]
    assert completed["status"] == "computed" and completed["result"] == {"node": "under", "value": "true"}
    assert R.rerun(completed)["reproduces"] is True


async def _two_machines(small: tuple[str, ...], large: tuple[str, ...], g=GROWING):
    async with session(*small) as s:
        made = await s.call_tool("record_computation", {"graph": g, "name": "stage-gain", "supports": SUPPORTS})
        rerun_small = await s.call_tool("rerun_record", {"record": made.content[1].resource.text})
    pending_text = made.content[1].resource.text
    async with session(*large) as s:
        completed = await s.call_tool("record_computation", {"record": pending_text})
        direct = await s.call_tool("record_computation", {"graph": g, "name": "stage-gain", "supports": SUPPORTS})
        rerun_pending_here = await s.call_tool("rerun_record", {"record": json.loads(pending_text)})
        rerun_completed = await s.call_tool("rerun_record", {"record": completed.content[1].resource.text})
    return made, rerun_small, completed, direct, rerun_pending_here, rerun_completed


@pytest.mark.parametrize("small, limit", [
    (("--max-digits", "100"), "max_digits"),
    (("--deadline", "0.001"), "deadline"),
    (("--max-reply-bytes", "6000"), "max_reply_bytes"),
])
def test_a_pending_record_made_under_low_limits_completes_under_higher_ones_to_the_direct_record(small, limit):
    g = GROWING
    if limit == "deadline":  # a millisecond is too short for 500 nodes on any machine
        g = graph(*GROWING["nodes"][:-2], *[op(f"s{i}", "add", "r2" if i == 0 else f"s{i - 1}", "ratio") for i in range(480)],
                  inp("limit", "1e6", "requirement"), op("under", "lt", "s479", "limit"), result="under")
    made, rerun_small, completed, direct, rerun_pending_here, rerun_completed = anyio.run(_two_machines, small, (), g)

    # The small machine: a normal reply, the refusal, and the not-yet-computed record.
    answer = answer_of(made)
    assert answer["status"] == "refused" and answer["refused"]["kind"] == "exceeds_limits"
    assert answer["refused"]["limit"]["name"] == limit
    assert answer["record"]["status"] == "not_computed"
    assert "not yet computed" in answer["next"].lower() or "NOT YET COMPUTED" in answer["next"]
    pending = json.loads(made.content[1].resource.text)
    assert pending["status"] == "not_computed" and pending["stopped"]["limit"]["name"] == limit
    assert str(made.content[1].resource.uri) == "calcfile:///stage-gain.calc.json"
    small_rerun = answer_of(rerun_small)
    assert small_rerun["status"] == "not_computed" and small_rerun["result"] is None and small_rerun["reproduces"] is None
    assert "no result to check" in small_rerun["verdict"] and "no higher" in small_rerun["verdict"]

    # The larger machine: rerun_record says it has no result yet and that this machine has room.
    here = answer_of(rerun_pending_here)
    assert here["status"] == "not_computed" and here["content_hash"]["matches"] is True
    assert "complete it here" in here["verdict"], here["verdict"]

    # Completing it gives the record a direct computation gives, byte for byte.
    done = answer_of(completed)
    assert done["status"] == "ok" and done["record"]["status"] == "computed"
    assert completed.content[1].resource.text == direct.content[1].resource.text
    assert done["record"]["content_hash"] == answer_of(direct)["record"]["content_hash"]
    final = json.loads(completed.content[1].resource.text)
    assert final["graph"] == pending["graph"] and final["inputs"] == pending["inputs"], "the same graph and inputs"
    assert final["result"] == {"node": "under", "value": "true"}
    assert "stopped" not in final and "limits_in_force" not in final
    assert answer_of(rerun_completed)["reproduces"] is True


def test_completing_where_there_is_still_not_enough_room_gives_a_new_pending_record():
    pending = pending_of(limits=L.Limits(max_digits=50))
    r = anyio.run(_one, ("--max-digits", "100"), "record_computation", {"record": pending})
    answer = answer_of(r)
    assert answer["status"] == "refused" and answer["record"]["status"] == "not_computed"
    again = json.loads(r.content[1].resource.text)
    assert pending["stopped"]["node"] == "r16"
    assert again["limits_in_force"]["max_digits"] == 100 and again["stopped"]["node"] == "r32"
    assert again["graph"] == pending["graph"]


async def _one(extra, tool, args):
    async with session(*extra) as s:
        return await s.call_tool(tool, args)


def one(tool, args, *extra):
    return anyio.run(_one, extra, tool, args)


# ---------------------------------------------------------------- tampering is caught


def test_a_pending_record_edited_by_hand_is_not_completed():
    pending = pending_of()
    pending["graph"]["nodes"][0]["value"] = "1/2"  # the ratio, edited; the seal not
    answer = answer_of(one("record_computation", {"record": pending}))
    assert answer["status"] == "refused" and answer["result"] is None
    assert answer["refused"]["kind"] == "record_changed"
    assert "content hash does not match" in answer["refused"]["reason"]
    rerun = R.rerun(R.load(pending))
    assert rerun["reproduces"] is False and rerun["content_hash"]["matches"] is False
    assert "changed after it was made" in rerun["verdict"]


def test_a_pending_record_whose_inputs_no_longer_follow_from_its_graph_is_caught_even_with_a_new_seal():
    pending = pending_of()
    pending["inputs"][0]["value"] = "2"  # the input as it would be quoted, edited, and the hash recomputed
    pending["content_hash"] = R.content_hash(pending)
    answer = answer_of(one("record_computation", {"record": pending}))
    assert answer["refused"]["kind"] == "record_changed"
    assert answer["refused"]["differences"][0]["field"] == "inputs"
    rerun = R.rerun(R.load(pending))
    assert rerun["reproduces"] is False and rerun["content_hash"]["matches"] is True
    assert rerun["differences"][0]["field"] == "inputs"


@pytest.mark.parametrize("edit, field", [
    (lambda r: r.pop("stopped"), "record"),
    (lambda r: r.update(status="computed"), "record"),
    (lambda r: r.update(result={"node": "under", "value": "true"}), "record"),
    (lambda r: r["stopped"]["limit"].update(name="patience"), "record.stopped.limit.name"),
])
def test_a_pending_record_that_no_longer_fits_its_schema_is_a_malformed_call(edit, field):
    pending = pending_of()
    edit(pending)
    reason = reason_of(one("record_computation", {"record": pending}))
    assert reason.startswith(f"Malformed call. {field}"), reason
    assert "schema" in reason


def test_a_computed_record_is_not_completed_again():
    reason = reason_of(one("record_computation", {"record": direct_of()}))
    assert reason.startswith("Malformed call. record.status:") and "already computed" in reason and "rerun_record" in reason


@pytest.mark.parametrize("args, field", [
    ({"graph": GROWING}, "graph"),
    ({"name": "another-name"}, "name"),
    ({"supports": "something else"}, "supports"),
])
def test_completing_takes_the_records_own_graph_name_and_supports(args, field):
    reason = reason_of(one("record_computation", {"record": pending_of(), **args}))
    assert reason.startswith(f"Malformed call. {field}:"), reason


def test_a_call_with_neither_graph_nor_record_says_what_to_pass():
    reason = reason_of(one("record_computation", {"name": "n"}))
    assert reason.startswith("Malformed call. graph:") and "not-yet-computed `record`" in reason
    assert reason_of(one("record_computation", {"graph": GROWING})).startswith("Malformed call. name:")


# ---------------------------------------------------------------- version 1 still re-runs


@pytest.mark.parametrize("fixture", ["fiber-bend-margin.v1.calc.json", "battery.v1.calc.json"])
def test_a_version_1_record_made_by_flo2_calc_0_1_0_still_re_runs(fixture):
    text = (DATA / fixture).read_text(encoding="utf-8")
    rec = json.loads(text)
    assert rec["schema_version"] == 1 and "status" not in rec and rec["produced_by"]["flo2_calc"] == "0.1.0"
    jsonschema.Draft202012Validator(R.schema(1)).validate(rec)
    answer = R.rerun(R.load(text))
    assert answer["reproduces"] is True, answer
    assert answer["status"] == "ok" and answer["record_status"] == "computed"
    assert answer["note"] == f"recorded with flo2-calc 0.1.0, re-run with {__version__}."
    over_the_client = answer_of(one("rerun_record", {"record": text}))
    assert over_the_client["reproduces"] is True


def test_a_version_2_record_made_by_flo2_calc_0_2_0_still_re_runs():
    text = (DATA / "stage-gain.v2.calc.json").read_text(encoding="utf-8")
    rec = json.loads(text)
    assert rec["schema_version"] == 2 and rec["produced_by"] == {"flo2_calc": "0.2.0", "pint": "0.26.1"}
    jsonschema.Draft202012Validator(R.schema(2)).validate(rec)
    answer = R.rerun(R.load(text))
    assert answer["reproduces"] is True, answer
    assert answer["note"] == f"recorded with flo2-calc 0.2.0, re-run with {__version__}."
    assert answer_of(one("rerun_record", {"record": text}))["reproduces"] is True


def test_a_version_2_not_yet_computed_record_completes_to_this_versions_direct_record():
    """Made by 0.2.0 on a small machine, completed by this version: the record a
    direct computation gives here, byte for byte (schema version 3 now)."""
    text = (DATA / "stage-gain.not-computed.v2.calc.json").read_text(encoding="utf-8")
    pending = R.load(text)
    assert pending["schema_version"] == 2 and pending["status"] == "not_computed"
    completed = one("record_computation", {"record": text})
    assert answer_of(completed)["status"] == "ok"
    direct = one("record_computation", {"graph": GROWING, "name": "stage-gain", "supports": SUPPORTS})
    assert completed.content[1].resource.text == direct.content[1].resource.text
    assert json.loads(completed.content[1].resource.text)["schema_version"] == 4


def test_a_tampered_version_1_record_is_still_caught():
    rec = json.loads((DATA / "battery.v1.calc.json").read_text(encoding="utf-8"))
    rec["graph"]["nodes"][0]["value"] = "2600 mAh"
    rec["content_hash"] = R.content_hash(rec)
    answer = R.rerun(R.load(rec))
    assert answer["reproduces"] is False and answer["content_hash"]["matches"] is True


def test_a_record_re_run_where_it_passes_the_limits_is_neither_confirmed_nor_contradicted():
    """Made on a larger machine, checked on a small one: not "does NOT reproduce"."""
    rec = direct_of()
    answer = R.rerun(R.load(rec), L.Guard(SMALL))
    assert answer["status"] == "refused" and answer["reproduces"] is None
    assert answer["refused"]["limit"]["name"] == "max_digits"
    assert "neither confirmed nor contradicted" in answer["verdict"] and "content hash matches" in answer["verdict"]
    rec["result"]["value"] = "false"  # and once edited, the seal still says so
    assert R.rerun(R.load(rec), L.Guard(SMALL))["reproduces"] is False
