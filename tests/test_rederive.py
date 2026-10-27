"""A kept record is re-derived when an input changes, and says what moved (flo2-calc 0.14.0).

req:a-calc-record-keeps-its-formula-and-is-re-derived-when-an-input-changes (design 0bee0c00b35845f6, accepted
2026-10-27), under dec:calc-keeps-live-formulas-and-solves-for-a-variable-proved-on-a-test-case-first and
dec:solving-ships-as-a-separate-helper-image-so-calc-stays-lean-and-exact: live formulas are built in calc itself,
with no new dependency. The proof of concept that came first
(fact:the-symbolic-proof-of-concept-passed-live-formulas-need-no-sympy-and-solving-works-when-calc-checks-every-
answer-2026-10-27) showed a record's graph is already its formula: re-deriving is evaluating the same graph with
new inputs, under calc's own exact arithmetic.

Until 0.14.0 a design could only say a kept record was OWED a re-run when a bound quantity changed (0.13.0); the
record itself could not be brought up to date without composing its graph again by hand.

THE CLASS, pinned here:
  - rederive_record takes a kept, computed record and new values for one or more of its INPUTS, each with its
    source; it evaluates the same graph with them and returns a new record, with what moved, old -> new, for every
    result, and every other node whose value changed;
  - the new record keeps the change in its `history` (schema version 12), each entry naming the record it was
    re-derived from by its content hash, and it re-runs with rerun_record to the same content;
  - a new value must measure what the input it replaces measured (a temperature stays a temperature, a change a
    change); any unit of that kind is taken, and converted exactly; otherwise it is refused, saying what arrived;
  - a name that is not one of the record's inputs is refused, naming its inputs;
  - a record of version 7 to 11 is re-derived; one of version 1 to 6 was made under the rules before delta_K and is
    refused with that reason; a record changed after it was made, or one that does not reproduce here, is refused.

The public test cases are the proof of concept's: steady one-dimensional wall heat loss q = A * dT / R (ASHRAE
Handbook - Fundamentals 2021, ch. 25; the inputs are illustrative: a 1,200 ft^2 wall, a 70 F design difference,
R-19) and a generic excavation (footprint times depth, and the bottom's elevation; 1 ft = 0.3048 m exactly, NIST
SP 811 appendix B).
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import jsonschema
import pytest
from conftest import answer_of, graph, inp, op, reason_of, session

from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, read_graph
from flo2_calc.rederive import rederive

DATA = Path(__file__).parent / "data"

HEAT = graph(
    inp("A", "1200 ft^2", "illustrative net wall area"),
    inp("dT", "70 delta_degF", "illustrative design difference, 70 degF in, 0 degF out"),
    inp("R", "19 h*ft^2*delta_degF/Btu", "illustrative R-19 wall [ASHRAE]"),
    op("AdT", "mul", "A", "dT"),
    op("Q", "div", "AdT", "R"),
    result="Q",
)


def dig(footprint: str = "1200 ft^2", unit: str = "ft^3") -> dict:
    return graph(
        inp("grade", "100 ft", "site datum, generic"),
        inp("depth", "9 ft", "planned dig depth, generic"),
        inp("footprint", footprint, "basement footprint, generic"),
        op("bottom", "sub", "grade", "depth"),
        op("V.raw", "mul", "footprint", "depth"),
        op("V", "convert", "V.raw", unit=unit),
        result=["bottom", "V"],
    )


def made(g: dict, name: str = "calc") -> dict:
    ev = evaluate(read_graph(g))
    assert ev.ok, ev.refusal
    return R.build(ev, name, None)


def change(input_id: str, value, source="test", **extra) -> dict:
    return {"input": input_id, "value": value, "source": source, **extra}


# ---------------------------------------------------------------- the heat-loss case


def test_a_changed_area_re_derives_the_heat_loss_exactly_and_says_what_moved():
    old = made(HEAT, "wall-heat-loss")
    answer, new = rederive(old, [change("A", "1350 ft^2", "re-measured wall")])
    assert answer["status"] == "ok"
    assert answer["moved"] == [{
        "node": "Q",
        "old": {"value": "4421.05263157894736842105263158 Btu/h", "exact": "84000/19 Btu/h"},
        "new": {"value": "4973.68421052631578947368421053 Btu/h", "exact": "94500/19 Btu/h"},
    }]
    assert answer["unchanged"] == []
    assert answer["result"] == {"node": "Q", "value": "4973.68421052631578947368421053 Btu/h", "exact": "94500/19 Btu/h"}
    assert answer["changed"] == [{
        "input": "A",
        "old": {"value": "1200 ft^2", "unit": "ft^2", "source": "illustrative net wall area"},
        "new": {"value": "1350 ft^2", "unit": "ft^2", "source": "re-measured wall"},
    }]
    # every other node that moved: here the product A*dT
    assert answer["values"] == [{"node": "AdT", "old": {"value": "84000 ft^2*delta_degF"},
                                 "new": {"value": "94500 ft^2*delta_degF"}}]
    assert new["result"] == answer["result"] and new["name"] == "wall-heat-loss"


def test_the_new_record_keeps_its_history_matches_schema_12_and_re_runs_to_the_same_content():
    old = made(HEAT, "wall-heat-loss")
    _, new = rederive(old, [change("A", "1350 ft^2", "re-measured wall")])
    assert new["schema_version"] == R.SCHEMA_VERSION == 12
    jsonschema.validate(new, R.schema(12))
    (entry,) = new["history"]
    assert entry["rederived_from"] == old["content_hash"]
    assert entry["changed"][0]["input"] == "A" and entry["changed"][0]["new"]["value"] == "1350 ft^2"
    assert entry["moved"] == [{"node": "Q", "old": {"value": "4421.05263157894736842105263158 Btu/h", "exact": "84000/19 Btu/h"},
                               "new": {"value": "4973.68421052631578947368421053 Btu/h", "exact": "94500/19 Btu/h"}}]
    assert entry["unchanged"] == []
    again = R.rerun(new)
    assert again["outcome"] == "reproduced" and again["content_hash"]["matches"], again
    # The graph is the same graph with the new value: composing it whole gives the same values.
    direct = made(json.loads(json.dumps(new["graph"])), "wall-heat-loss")
    assert direct["values"] == new["values"] and direct["formula"] == new["formula"]


def test_a_second_change_adds_to_the_history_and_moves_only_what_rests_on_it():
    first = made(HEAT, "wall-heat-loss")
    _, second = rederive(first, [change("A", "1350 ft^2", "re-measured wall")])
    answer, third = rederive(second, [change("R", "21 h*ft^2*delta_degF/Btu", "R-21 batts, illustrative")])
    assert [h["rederived_from"] for h in third["history"]] == [first["content_hash"], second["content_hash"]]
    assert answer["moved"][0]["new"]["exact"] == "4500 Btu/h"  # 1350 * 70 / 21
    assert answer["values"] == []  # A*dT did not move
    assert R.rerun(third)["outcome"] == "reproduced"


def test_a_change_of_source_alone_moves_nothing_but_is_kept():
    old = made(HEAT)
    answer, new = rederive(old, [change("A", "1200 ft^2", {"design_quantity": "cst:wall-area"})])
    assert answer["moved"] == [] and answer["unchanged"] == ["Q"]
    assert new["history"][0]["changed"][0]["new"]["source"] == {"design_quantity": "cst:wall-area"}
    assert answer["inputs_bound"]["bound"][0]["input"] == "A"


# ---------------------------------------------------------------- the excavation case, US and SI


def test_a_changed_footprint_moves_the_volume_and_not_the_bottom_us_units():
    answer, new = rederive(made(dig(), "excavation"), [change("footprint", "1350 ft^2", "revised plan")])
    assert [m["node"] for m in answer["moved"]] == ["V"]
    assert answer["moved"][0]["old"] == {"value": "10800 ft^3"} and answer["moved"][0]["new"] == {"value": "12150 ft^3"}
    assert answer["unchanged"] == ["bottom"]
    assert [r["value"] for r in new["results"]] == ["91 ft", "12150 ft^3"]
    assert R.rerun(new)["outcome"] == "reproduced"


def test_a_depth_given_in_metres_replaces_one_in_feet_and_converts_exactly_si_units():
    old = made(dig("120 m^2", "m^3"), "excavation-si")
    assert [r["value"] for r in old["results"]] == ["91 ft", "329.184 m^3"]
    answer, new = rederive(old, [change("depth", "3 m", "SI depth")])
    moved = {m["node"]: m for m in answer["moved"]}
    assert moved["V"]["new"] == {"value": "360 m^3"}
    # 100 ft - 3 m, with 1 ft = 0.3048 m exactly: 11450/127 ft
    assert moved["bottom"]["old"] == {"value": "91 ft"} and moved["bottom"]["new"]["exact"] == "11450/127 ft"
    assert R.rerun(new)["outcome"] == "reproduced"


def test_several_inputs_change_at_once():
    answer, new = rederive(made(dig(), "excavation"), [change("footprint", "1000 ft^2"), change("depth", "10 ft")])
    assert [c["input"] for c in answer["changed"]] == ["footprint", "depth"]
    assert [r["value"] for r in new["results"]] == ["90 ft", "10000 ft^3"]


# ---------------------------------------------------------------- refused, saying why


def test_a_new_value_that_measures_something_else_is_refused_saying_what_arrived():
    answer, new = rederive(made(dig(), "excavation"), [change("footprint", "1350 ft", "revised plan")])
    assert new is None and answer["status"] == "refused"
    refused = answer["refused"]
    assert refused["kind"] == "unit_mismatch" and refused["node"] == "footprint"
    assert "1350 ft" in refused["reason"] and "1200 ft^2" in refused["reason"]
    assert refused["units"] == ["ft^2", "ft"]


def test_a_temperature_never_replaces_a_change_of_temperature():
    answer, new = rederive(made(HEAT), [change("dT", "70 degF")])
    assert new is None and answer["refused"]["kind"] == "unit_mismatch"
    assert "temperature change" in answer["refused"]["reason"] and "70 degF" in answer["refused"]["reason"]


def test_a_plain_number_never_replaces_a_quantity():
    answer, new = rederive(made(HEAT), [change("A", "1350")])
    assert new is None and answer["refused"]["kind"] == "unit_mismatch"


def test_a_name_that_is_not_one_of_the_records_inputs_is_refused_naming_them():
    with pytest.raises(CallError) as caught:
        rederive(made(HEAT), [change("area", "1350 ft^2")])
    assert caught.value.path == "changes[0].input"
    assert '"area"' in caught.value.problem and "A, dT, R" in caught.value.problem


def test_a_computed_node_is_not_an_input():
    with pytest.raises(CallError) as caught:
        rederive(made(HEAT), [change("Q", "5000 Btu/h")])
    assert caught.value.path == "changes[0].input" and "computed" in caught.value.problem


def test_a_change_needs_a_source_and_names_an_input_once():
    with pytest.raises(CallError) as caught:
        rederive(made(HEAT), [{"input": "A", "value": "1350 ft^2"}])
    assert caught.value.path == "changes[0].source"
    with pytest.raises(CallError) as caught:
        rederive(made(HEAT), [change("A", "1350 ft^2"), change("A", "1400 ft^2")])
    assert caught.value.path == "changes[1].input"
    with pytest.raises(CallError):
        rederive(made(HEAT), [])


def test_a_change_that_changes_nothing_is_refused():
    with pytest.raises(CallError) as caught:
        rederive(made(HEAT), [change("A", "1200 ft^2", "illustrative net wall area")])
    assert "already holds" in caught.value.problem


def test_a_record_changed_after_it_was_made_is_refused():
    old = made(HEAT)
    old["values"][0]["value"] = "1300 ft^2"  # edited by hand; the seal no longer matches
    answer, new = rederive(old, [change("A", "1350 ft^2")])
    assert new is None and answer["refused"]["kind"] == "record_changed"


def test_a_value_the_new_input_cannot_give_is_a_refusal_with_no_record():
    answer, new = rederive(made(HEAT), [change("R", "0 h*ft^2*delta_degF/Btu")])
    assert new is None and answer["status"] == "refused" and answer["refused"]["node"] == "Q"
    assert "No record was made" in answer["note"]


def test_a_not_yet_computed_record_is_completed_not_re_derived():
    pending = json.loads((DATA / "stage-gain.not-computed.v2.calc.json").read_text())
    with pytest.raises(CallError) as caught:
        rederive(pending, [change("x", "1")])
    assert caught.value.path == "record.status" and "record_computation" in caught.value.problem


# ---------------------------------------------------------------- records of older versions


def test_a_version_7_record_is_re_derived_into_a_version_12_record():
    old = json.loads((DATA / "statistics.v7.calc.json").read_text())
    assert old["schema_version"] == 7 and R.rerun(old)["outcome"] == "reproduced"
    answer, new = rederive(old, [change("m0", "950 mg/L", "a later published mean, illustrative")])
    assert answer["status"] == "ok" and new["schema_version"] == 12
    assert answer["record"]["rederived_from"] == {"content_hash": old["content_hash"], "schema_version": 7,
                                                  "flo2_calc": old["produced_by"]["flo2_calc"]}
    assert any(m["node"] == "z" for m in answer["moved"])
    jsonschema.validate(new, R.schema(12))
    assert R.rerun(new)["outcome"] == "reproduced"


def test_a_version_1_record_is_refused_with_the_reason():
    old = json.loads((DATA / "battery.v1.calc.json").read_text())
    answer, new = rederive(old, [change("draw", "200 mA")])
    assert new is None and answer["refused"]["kind"] == "older_rules"
    assert "version 1" in answer["refused"]["reason"] and "record_computation" in answer["refused"]["reason"]


# ---------------------------------------------------------------- over MCP


def test_rederive_record_is_a_writing_tool_that_returns_the_new_record_as_a_file():
    old = made(HEAT, "wall-heat-loss")

    async def main():
        async with session() as s:
            tools = {t.name: t for t in (await s.list_tools()).tools}
            reply = await s.call_tool("rederive_record", {
                "record": json.dumps(old), "changes": [change("A", "1350 ft^2", "re-measured wall")]})
            bad = await s.call_tool("rederive_record", {"record": old, "changes": [change("area", "1 ft^2")]})
            again = await s.call_tool("rerun_record", {"record": reply.content[1].resource.text})
            return tools, reply, bad, again

    tools, reply, bad, again = anyio.run(main)
    assert tools["rederive_record"].annotations.readOnlyHint is False
    answer = answer_of(reply)
    assert answer["moved"][0]["new"]["exact"] == "94500/19 Btu/h"
    assert answer["record"]["file"] == "wall-heat-loss.calc.json"
    assert str(reply.content[1].resource.uri) == "calcfile:///wall-heat-loss.calc.json"
    assert "changes[0].input" in reason_of(bad)
    assert answer_of(again)["outcome"] == "reproduced"


def test_a_re_derived_reply_fits_flo2_ios_answer_budget():
    """The trial's winter heat graph (tests/data/answer-budget, 234 nodes): one input changed moves many nodes, and
    the reply still fits 24,000 characters, its outcome whole and the rest named."""
    from test_answer_budget import FLO2_IO_ANSWER_CHARS, FLO2_IO_ENV, fixture

    g = fixture("winter-heat")
    ev = evaluate(read_graph(g))
    assert ev.ok, ev.refusal
    old = R.build(ev, "winter-heat", None)
    first = next(i for i in old["inputs"] if "unit" in i and i["unit"] and "array" not in i)
    number, _, unit = first["value"].partition(" ")
    import os

    async def main():
        async with session(env={**os.environ, **FLO2_IO_ENV}) as s:
            return await s.call_tool("rederive_record", {
                "record": old, "changes": [change(first["id"], f"{number}1 {unit}", "a revised value, for the test")]})

    reply = anyio.run(main)
    text = reply.content[0].text
    assert len(text) <= FLO2_IO_ANSWER_CHARS
    answer = json.loads(text)
    assert answer["status"] == "ok" and answer["changed"][0]["input"] == first["id"]
    assert "moved" in answer and "record" in answer
