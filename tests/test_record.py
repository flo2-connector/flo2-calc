"""The computation record: deterministic, schema-valid, re-runnable, tamper-evident.

ver:record-reruns-and-catches-tampering and ver:record-matches-its-schema in
design 0bee0c00b35845f6.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest
from conftest import graph, inp, op

from flo2_calc import __version__
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, read_graph

FIBER = graph(
    inp("cavity", "2 mm", {"design_node": "con:cavity-depth", "design": "83d2b0775fe79af6"}),
    inp("bend", "1.4 mm", "fiber datasheet: minimum bend radius"),
    op("margin", "sub", "cavity", "bend"),
    inp("needed", "0.5 mm", "assumed"),
    op("fits", "ge", "margin", "needed"),
    result="fits",
)

BATTERY = graph(
    inp("capacity", "2400 mAh", "cell datasheet"),
    inp("draw", "180 mA", {"design_node": "con:led-current"}),
    op("hours", "div", "capacity", "draw"),
    op("in_h", "convert", "hours", unit="h"),
    inp("wanted", "12 h", "requirement: lit through one night"),
    op("enough", "ge", "in_h", "wanted"),
    inp("thirds", "1/3", "a plain ratio"),
    op("third_of_hours", "mul", "in_h", "thirds"),
    inp("flag", True, "assumed"),
    op("both", "and", "enough", "flag"),
)


def make(g=FIBER, name="fiber-bend-margin", supports=None):
    ev = evaluate(read_graph(g))
    assert ev.ok, ev.refusal
    return R.build(ev, name, supports)


def validator():
    return jsonschema.Draft202012Validator(R.schema())


# ---------------------------------------------------------------- what a record holds


def test_a_record_holds_what_a_decision_needs():
    rec = make(supports={"design_node": "dec:fiber-route"})
    assert rec["record_format"] == "flo2-calc computation record"
    assert rec["schema_version"] == 2
    assert rec["status"] == "computed"
    assert "stopped" not in rec and "limits_in_force" not in rec, "a computed record carries no host limits"
    assert rec["graph"] == FIBER
    assert rec["result"] == {"node": "fits", "value": "true"}
    assert rec["produced_by"]["flo2_calc"] == __version__
    assert rec["supports"] == {"design_node": "dec:fiber-route"}
    by_id = {i["id"]: i for i in rec["inputs"]}
    assert by_id["cavity"] == {
        "id": "cavity", "value": "2 mm", "unit": "mm",
        "source": {"design_node": "con:cavity-depth", "design": "83d2b0775fe79af6"},
    }
    assert by_id["bend"]["source"] == "fiber datasheet: minimum bend radius"
    assert [v["node"] for v in rec["values"]] == ["cavity", "bend", "margin", "needed", "fits"]
    assert {v["node"]: v["value"] for v in rec["values"]}["margin"] == "0.6 mm"
    assert rec["content_hash"] == R.content_hash(rec)
    assert rec["content_hash"].startswith("sha256:") and len(rec["content_hash"]) == 71


def test_the_same_graph_gives_a_byte_identical_record():
    assert R.file_bytes(make()) == R.file_bytes(make())
    assert R.file_bytes(make(BATTERY, "battery")) == R.file_bytes(make(copy.deepcopy(BATTERY), "battery"))


def test_every_input_needs_a_source_to_be_recorded():
    no_source = graph(inp("a", "1 mm", None), inp("b", "2 mm"), op("s", "add", "a", "b"))
    with pytest.raises(CallError) as caught:
        make(no_source)
    assert "'a'" in caught.value.problem and "source" in caught.value.problem


# ---------------------------------------------------------------- the schema


def test_the_schema_is_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(R.schema())


@pytest.mark.parametrize("g, name", [(FIBER, "fiber"), (BATTERY, "battery"), (graph(inp("x", "0.1", "t")), "one-input")])
def test_records_validate_against_the_published_schema(g, name):
    rec = make(g, name, supports="the decision about the fiber route")
    validator().validate(rec)
    validator().validate(json.loads(R.file_bytes(rec)))


def test_a_rounded_value_carries_its_exact_fraction_and_still_validates():
    rec = make(BATTERY, "battery")
    third = {v["node"]: v for v in rec["values"]}["third_of_hours"]
    assert third["exact"] == "40/9 h"
    assert third["value"].startswith("4.44444")
    validator().validate(rec)


@pytest.mark.parametrize("field", ["content_hash", "graph", "inputs", "values", "result", "produced_by", "name"])
def test_a_record_missing_a_required_field_fails_the_schema(field):
    rec = make()
    del rec[field]
    assert list(validator().iter_errors(rec)), field
    with pytest.raises(CallError):
        R.load(rec)


# ---------------------------------------------------------------- re-running


def test_a_record_re_runs_to_the_same_result():
    rec = make(BATTERY, "battery")
    answer = R.rerun(R.load(rec))
    assert answer["reproduces"] is True, answer
    assert answer["differences"] == []
    assert answer["content_hash"]["matches"] is True
    assert answer["result"] == rec["result"]


def test_a_record_re_runs_from_its_file_text_too():
    rec = make()
    assert R.rerun(R.load(R.file_bytes(rec).decode("utf-8")))["reproduces"] is True


def test_a_record_whose_result_was_edited_is_caught():
    rec = make()
    rec["result"]["value"] = "false"
    answer = R.rerun(R.load(rec))
    assert answer["reproduces"] is False
    assert answer["content_hash"]["matches"] is False
    assert any(d["field"] == "result" for d in answer["differences"])
    assert "does NOT reproduce" in answer["verdict"]


def test_a_record_whose_input_was_edited_and_hash_recomputed_is_still_caught():
    """The hash is a seal, not a signature: someone can recompute it. Re-running
    the graph is what catches a result that no longer follows from its inputs."""
    rec = make()
    rec["graph"]["nodes"][1]["value"] = "1.9 mm"  # the bend radius, edited
    rec["content_hash"] = R.content_hash(rec)
    answer = R.rerun(R.load(rec))
    assert answer["content_hash"]["matches"] is True
    assert answer["reproduces"] is False
    fields = {d["field"] for d in answer["differences"]}
    assert {"inputs", "result", "values[bend]", "values[margin]", "values[fits]"} <= fields


def test_a_record_from_a_newer_schema_is_refused_by_name():
    rec = make()
    rec["schema_version"] = 3
    with pytest.raises(CallError) as caught:
        R.load(rec)
    assert caught.value.path == "record.schema_version"
    assert "newer" in caught.value.problem


def test_text_that_is_not_json_is_not_a_record():
    with pytest.raises(CallError) as caught:
        R.load("{not json")
    assert "not JSON" in caught.value.problem


def test_a_record_whose_graph_can_no_longer_be_read_does_not_reproduce_rather_than_failing():
    rec = make()
    rec["graph"]["nodes"][0]["value"] = "2 furlong"
    rec["content_hash"] = R.content_hash(rec)
    answer = R.rerun(R.load(rec))
    assert answer["reproduces"] is False
    assert "cannot be read now" in answer["differences"][0]["rerun"]
