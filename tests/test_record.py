"""The computation record: deterministic, schema-valid, re-runnable, tamper-evident.

ver:record-reruns-and-catches-tampering and ver:record-matches-its-schema in
design 0bee0c00b35845f6.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

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
    assert rec["schema_version"] == 4
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


def test_a_record_says_its_values_are_exact_for_these_inputs():
    note = make()["arithmetic"]
    assert "exact FOR THESE INPUTS" in note and "no more accurate than they are" in note
    assert "truncated pi or e" in note


def test_records_with_money_and_temperatures_validate_and_re_run():
    g = graph(
        inp("price", "987.50 USD", "quote"), inp("rate", "0.92 EUR/USD", "ECB reference rate, 2026-10-02"),
        op("in_eur", "mul", "price", "rate"), inp("budget", "1000 EUR", "assumed"), op("fits", "le", "in_eur", "budget"),
        inp("ta", "40 degC", "datasheet"), inp("rise", "27.9 delta_degC", "computed"), op("tj", "add", "ta", "rise"),
        inp("limit", "158 degF", "datasheet"), op("cool", "lt", "tj", "limit"), op("both", "and", "fits", "cool"),
    )
    rec = make(g, "money-and-heat")
    validator().validate(rec)
    values = {v["node"]: v["value"] for v in rec["values"]}
    assert values["in_eur"] == "908.5 EUR" and values["tj"] == "67.9 degC" and rec["result"]["value"] == "true"
    assert R.rerun(json.loads(R.file_bytes(rec)))["reproduces"] is True


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
    rec["schema_version"] = 5
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
    rec["graph"]["nodes"][0]["value"] = "2 notaunit"
    rec["content_hash"] = R.content_hash(rec)
    answer = R.rerun(R.load(rec))
    assert answer["reproduces"] is False
    assert "cannot be read now" in answer["differences"][0]["rerun"]


# ---------------------------------------------------------------- schema version 4 (flo2-calc 0.5.0, dec:round-2-fixes)

DATA = Path(__file__).resolve().parent / "data"


def test_a_record_with_several_results_holds_each_by_name_fits_its_schema_and_re_runs():
    g = graph(inp("mid", "12 mm", "measured"), inp("half", "0.3 mm", "computed"), op("lo", "sub", "mid", "half"),
              op("hi", "add", "mid", "half"), result=["lo", "hi"])
    rec = make(g, "interval")
    assert "result" not in rec and rec["results"] == [{"node": "lo", "value": "11.7 mm"}, {"node": "hi", "value": "12.3 mm"}]
    assert rec["graph"]["result"] == ["lo", "hi"]
    validator().validate(rec)
    assert R.rerun(rec)["reproduces"] is True
    assert R.rerun(rec)["results"] == rec["results"]


def test_a_computed_record_holds_one_of_result_and_results_never_both():
    rec = make()
    both = copy.deepcopy(rec)
    both["results"] = [rec["result"]]
    assert not validator().is_valid(both)
    neither = copy.deepcopy(rec)
    del neither["result"]
    assert not validator().is_valid(neither)


def test_a_record_carries_its_formula_and_working_and_the_new_writing():
    g = graph(inp("C", "450 mAh", "datasheet"), inp("I", "13 mA", "measured"), op("t", "div", "C", "I"),
              inp("two", "2", "whole"), inp("n", "200", "whole"), op("big", "pow", "two", "n"), op("root", "sqrt", "two", digits=40),
              result=["t", "big", "root"])
    rec = make(g, "writing")
    values = {v["node"]: v for v in rec["values"]}
    assert values["t"] == {"node": "t", "value": "34.6153846153846153846153846154 h", "exact": "450/13 h", "simplified_from": "mAh/mA"}
    assert values["big"] == {"node": "big", "value": str(2**200)}
    assert values["root"]["value"] == "1.414213562373095048801688724209698078570"
    assert [f["node"] for f in rec["formula"]] == ["t", "big", "root"]
    assert rec["working"][-1]["step"] == len(rec["values"])
    validator().validate(rec)


def test_the_operators_of_round_2_are_in_the_record_with_their_fields():
    g = graph(inp("y", "42.39", "computed"), op("a", "with_unit", "y", unit="mil^2", source="IPC-2221: A in mil^2"),
              inp("g", "6 dB", "datasheet"), op("r", "db_to_ratio", "g", kind="amplitude"), inp("b", True, "test"),
              op("n", "count_true", "b"), inp("k", "1", "rule"), op("v", "k_of_n", "k", "b"), op("m", "magnitude", "a", unit="mil^2"))
    rec = make(g, "round-2-operators")
    validator().validate(rec)
    assert R.rerun(rec)["reproduces"] is True


@pytest.mark.parametrize("name", ["display.v3.calc.json", "battery.v1.calc.json", "fiber-bend-margin.v1.calc.json", "stage-gain.v2.calc.json"])
def test_records_made_by_earlier_versions_still_reproduce_under_their_own_writing(name):
    """display.v3.calc.json was made by flo2-calc 0.4.0 with every value whose
    writing 0.5.0 changes: a compound unit 0.5.0 shows simpler (mAh/mA, V/mA,
    V*mA, um^2/m, mm/m), 2^1000 as 30 digits and ".../1", and sqrt(2) at 40
    digits written with 39. Re-run under its own version's writing, it
    reproduces byte for byte."""
    rec = json.loads((DATA / name).read_text())
    answer = R.rerun(R.load(rec))
    assert answer["reproduces"] is True, answer["differences"]
    assert answer["formula"] and answer["working"], "the re-run is shown back too"


def test_the_version_3_record_holds_the_writing_0_5_0_changes():
    rec = json.loads((DATA / "display.v3.calc.json").read_text())
    assert rec["schema_version"] == 3 and rec["produced_by"]["flo2_calc"] == "0.4.0"
    values = {v["node"]: v for v in rec["values"]}
    assert values["hours"]["value"].endswith(" mAh/mA")
    assert values["big"]["exact"].endswith("/1")
    assert values["root"]["value"] == "1.41421356237309504880168872420969807857"
    assert values["pct"]["value"] == "900 mm/m"


def test_the_same_graph_made_now_is_written_the_new_way():
    rec = json.loads((DATA / "display.v3.calc.json").read_text())
    now = make(rec["graph"], rec["name"], rec["supports"])
    values = {v["node"]: v for v in now["values"]}
    assert values["hours"]["value"].endswith(" h") and values["ohms"]["value"].endswith(" kohm")
    assert values["big"] == {"node": "big", "value": str(2**1000)}
    assert values["root"]["value"].endswith("078570")
    assert values["pct"] == {"node": "pct", "value": "0.9", "simplified_from": "mm/m"}
    assert values["growth"] == {"node": "growth", "value": "0.001105 um", "simplified_from": "um^2/m"}
