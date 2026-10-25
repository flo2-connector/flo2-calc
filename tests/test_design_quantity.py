"""An input names the design quantity it holds the value of (flo2-calc 0.13.0).

The web of rules @ajs accepted on 2026-10-24 (reflow2's
dec:idea-reflow2-becomes-the-web-of-rules-for-a-buildings-ifc-model, option
(c), and req:a-changed-quantity-names-every-kept-computation-that-used-it). The
case it comes from: a household changed from four to five, and a food calc's
input `persons` cited the requirement as {"design_node": ...} but held its own
copy of "4", so nothing could say the record was owed a re-run
(fact:root-cause-a-changed-requirement-does-not-flow-because-the-accepted-web-
of-rules-was-never-built-2026-10-25).

- An input may say `"source": {"design_quantity": "<id>"}` (and "design" for
  another design): the value it holds is that design quantity's. The record
  keeps the id, so a design can name the input as one the record took.
- Copying a value with no design quantity stays legal, and a reply says which
  inputs are UNBOUND: a change to the design cannot reach them.
- flo2-calc still never resolves the id (req:sister-mcp): the binding is data.
- Only an input's value can be a design quantity; a unit's source cannot.

OBSERVED FAILING FIRST on main 31e88b3 (flo2-calc 0.12.0): "a design source
has only design_node and, for another design, design".
"""

from __future__ import annotations

import json

import anyio
import jsonschema
import pytest
from conftest import graph, inp, op, session, text_of

from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import evaluate, read_graph

FOOD = graph(
    inp("persons", "5", {"design_quantity": "cst:household"}),
    inp("area_per_person", "8 m^2", "a grow-loop rule of thumb, copied"),
    op("area", "mul", "persons", "area_per_person"),
    result="area",
)


def test_an_input_may_name_the_design_quantity_it_holds():
    g = read_graph(FOOD)
    persons = next(n for n in g.nodes if n.id == "persons")
    assert persons.source == {"design_quantity": "cst:household"}


def test_the_record_keeps_the_id_and_matches_its_schema():
    ev = evaluate(read_graph(FOOD))
    assert ev.ok, ev.refusal
    rec = R.build(ev, "food", None)
    jsonschema.validate(rec, R.schema(R.SCHEMA_VERSION))
    persons = next(i for i in rec["inputs"] if i["id"] == "persons")
    assert persons["source"] == {"design_quantity": "cst:household"}
    assert R.rerun(rec)["outcome"] == "reproduced"


def test_another_designs_quantity_is_named_with_its_design():
    g = read_graph(graph(inp("persons", "5", {"design_quantity": "cst:household", "design": "671a764fa790c030"})))
    assert g.nodes[0].source == {"design_quantity": "cst:household", "design": "671a764fa790c030"}


@pytest.mark.parametrize(
    "source, says",
    [
        ({"design_quantity": "cst:household", "design_node": "req:x"}, "one of"),
        ({"design_quantity": "has space"}, "no spaces"),
        ({"design_quantity": ""}, "no spaces"),
    ],
)
def test_a_malformed_binding_is_refused_by_name(source, says):
    with pytest.raises(CallError) as e:
        read_graph(graph(inp("persons", "5", source)))
    assert says in str(e.value), str(e.value)


def test_a_units_source_is_not_a_design_quantity():
    g = graph(
        inp("x", "2"),
        {"id": "y", "op": "with_unit", "args": ["x"], "unit": "m", "source": {"design_quantity": "cst:k"}},
    )
    with pytest.raises(CallError) as e:
        read_graph(g)
    assert "design quantity" in str(e.value) and "input" in str(e.value), str(e.value)


def test_a_version_10_record_made_by_0_12_0_re_runs_as_it_was_made():
    """tests/data/food.v10.calc.json: the four-person food calc as 0.12.0 wrote it, its persons citing a design
    node with its own copied "4". It re-runs unchanged; nothing about it is read as bound."""
    from pathlib import Path

    rec = json.loads((Path(__file__).parent / "data" / "food.v10.calc.json").read_text())
    assert rec["schema_version"] == 10 and rec["produced_by"]["flo2_calc"] == "0.12.0"
    jsonschema.validate(rec, R.schema(10))
    assert R.rerun(R.load(rec))["reproduces"] is True
    assert R.inputs_bound(rec)["bound"] == [] and R.inputs_bound(rec)["unbound"] == ["persons", "area_per_person"]


def test_the_reply_names_each_bound_input_and_reads_a_copied_value_as_unbound():
    async def go():
        async with session() as s:
            return await s.call_tool("record_computation", {"graph": FOOD, "name": "food"})

    answer = json.loads(text_of(anyio.run(go)))
    assert answer["status"] == "ok", answer
    b = answer["inputs_bound"]
    assert b["bound"] == [{"input": "persons", "design_quantity": "cst:household", "value": "5", "unit": ""}], b
    assert b["unbound"] == ["area_per_person"], b
    assert "unbound" in b["note"] and "design" in b["note"], b
