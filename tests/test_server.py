"""The four tools over a real MCP client session (stdio, the installed server).

ver:refusals-reach-the-agent and ver:whole-equals-node-by-node in design
0bee0c00b35845f6. Every reason is read off the CLIENT's side: the python-sdk
2.x hides the text of any exception that is not a ToolError, so a test that
only called the functions would miss a reason that never arrives.
"""

from __future__ import annotations

import json

import anyio
import pytest
from conftest import answer_of, graph, inp, op, reason_of, session, text_of

FIBER = graph(
    inp("cavity", "2 mm", {"design_node": "con:cavity-depth"}),
    inp("bend", "1.4 mm", "fiber datasheet"),
    op("margin", "sub", "cavity", "bend"),
    inp("needed", "0.5 mm", "assumed"),
    op("fits", "ge", "margin", "needed"),
)


async def calls(steps):
    """Run (tool, arguments) steps in one session; return each result."""
    out = []
    async with session() as s:
        for tool, args in steps:
            out.append(await s.call_tool(tool, args))
    return out


def one(tool, args):
    return anyio.run(calls, [(tool, args)])[0]


# ---------------------------------------------------------------- refusals reach the agent


def test_a_unit_mismatch_reaches_the_agent_as_a_normal_reply_naming_the_operation_and_both_units():
    r = one("evaluate_graph", {"graph": graph(inp("a", "2 mm"), inp("b", "3 g"), op("total", "add", "a", "b"))})
    assert r.is_error is False, "a refused computation is a normal reply, not an error"
    answer = json.loads(text_of(r))
    assert answer["status"] == "refused"
    assert answer["result"] is None, "no result is given"
    refused = answer["refused"]
    assert refused["node"] == "total" and refused["op"] == "add" and refused["units"] == ["mm", "g"]
    assert "add cannot combine mm and g" in refused["reason"]


def test_an_unknown_unit_reaches_the_agent_as_a_malformed_call_with_its_reason():
    r = one("evaluate_graph", {"graph": graph(inp("a", "2 furlong"))})
    reason = reason_of(r)
    assert reason.startswith("Malformed call. graph.nodes[0].value:"), reason
    assert '"furlong" is not a unit flo2-calc knows' in reason
    assert "never guessed" in reason


def test_a_near_miss_spelling_reaches_the_agent_with_the_spelling_to_use():
    reason = reason_of(one("evaluate_graph", {"graph": graph(inp("a", "2 khz"))}))
    assert 'Write "kHz"' in reason


@pytest.mark.parametrize("text, never", [("2 MV", 'Write "mV"'), ("2 PF", 'Write "pF"'), ("2 MM", 'Write "mm"'), ("2 Nm", 'Write "nm"')])
def test_a_case_that_could_change_a_size_reaches_the_agent_with_no_hint(text, never):
    """Round 1, q022: 0.1.0 answered "mJ" with 'Write "MJ"', 10^9 too large."""
    reason = reason_of(one("evaluate_graph", {"graph": graph(inp("a", text))}))
    assert never not in reason and "Write" not in reason
    assert "case-sensitive" in reason


def test_a_millijoule_is_a_unit_now():
    answer = answer_of(one("evaluate_graph", {"graph": graph(inp("e", "5.875 mJ"), op("j", "convert", "e", unit="J"))}))
    assert answer["result"]["value"] == "0.005875 J"


def test_two_currencies_reach_the_agent_as_a_refusal_naming_both():
    answer = answer_of(one("evaluate_graph", {"graph": graph(inp("a", "987.50 USD"), inp("b", "120 EUR"), op("s", "add", "a", "b"))}))
    assert answer["status"] == "refused" and answer["refused"]["units"] == ["USD", "EUR"]
    assert "no exchange rates" in answer["refused"]["reason"]


def test_a_bare_c_reaches_the_agent_pointing_at_degc():
    reason = reason_of(one("evaluate_graph", {"graph": graph(inp("t", "25 C"))}))
    assert reason.startswith("Malformed call. graph.nodes[0].value:")
    assert '"degC"' in reason and '"coulomb"' in reason


def test_an_expression_typed_as_a_value_reaches_the_agent_as_one():
    reason = reason_of(one("evaluate_graph", {"graph": graph(inp("a", "3 + * 4"))}))
    assert "looks like an expression" in reason and "graph of nodes" in reason


def test_every_answer_says_its_values_are_exact_for_these_inputs():
    answer = answer_of(one("evaluate_graph", {"graph": graph(inp("a", "0.1"), inp("b", "0.2"), op("s", "add", "a", "b"))}))
    assert answer["exactness"].startswith("Exact for these inputs")
    added = answer_of(one("add_node", {"node": inp("a", "1/3")}))
    assert added["exactness"] == answer["exactness"]
    recorded = answer_of(one("record_computation", {"graph": graph(inp("a", "1/3", "t")), "name": "third"}))
    assert recorded["exactness"] == answer["exactness"]


def test_division_by_zero_reaches_the_agent_naming_the_node():
    r = one("evaluate_graph", {"graph": graph(inp("a", "3 V"), inp("i", "0 mA"), op("r", "div", "a", "i"))})
    answer = answer_of(r)
    assert answer["status"] == "refused"
    assert answer["refused"]["node"] == "r" and answer["refused"]["kind"] == "division_by_zero"
    assert "division by zero" in answer["refused"]["reason"]


@pytest.mark.parametrize("bad, words", [
    (graph(op("a", "neg", "b"), op("b", "neg", "a")), "cycle: a -> b -> a"),
    (graph(inp("a", "1"), op("b", "add", "a", "zz")), '"zz" is not the id of any node'),
    (graph(inp("a", "1"), inp("b", "2"), op("u", "union", "a", "b")), "'union' is not an operator"),
    ({"nodes": "not a list"}, "a graph's nodes are a list"),
])
def test_a_bad_graph_reaches_the_agent_as_a_malformed_call_naming_the_field(bad, words):
    reason = reason_of(one("evaluate_graph", {"graph": bad}))
    assert reason.startswith("Malformed call."), reason
    assert words in reason, reason


def test_arguments_of_the_wrong_type_still_say_why():
    reason = reason_of(one("evaluate_graph", {"graph": "2 + 2"}))
    assert "graph" in reason and len(reason) > 20, reason


# ---------------------------------------------------------------- whole graph, or node by node


async def _node_by_node(nodes):
    seen = []
    async with session() as s:
        g = None
        for node in nodes:
            args = {"node": node} if g is None else {"node": node, "graph": g}
            answer = answer_of(await s.call_tool("add_node", args))
            assert answer["status"] == "ok", answer
            assert answer["added"]["node"] == node["id"]
            seen.append(answer["added"]["value"])  # the intermediate value, inspected as it is built
            g = answer["graph"]
        whole = answer_of(await s.call_tool("evaluate_graph", {"graph": {"nodes": nodes}}))
    return seen, g, answer, whole


def test_a_graph_built_node_by_node_is_the_same_graph_and_gives_the_same_result():
    nodes = FIBER["nodes"]
    seen, built, last, whole = anyio.run(_node_by_node, nodes)
    assert seen == ["2 mm", "1.4 mm", "0.6 mm", "0.5 mm", "true"]
    assert built == {"nodes": nodes}, "the graph add_node grew is the graph sent whole"
    assert whole["status"] == "ok"
    assert whole["values"] == last["values"], "every node's value is the same either way"
    assert whole["result"] == {"node": "fits", "value": "true"}
    assert last["added"] == {"node": "fits", "value": "true"}


def test_a_node_that_would_be_refused_is_not_added():
    g = {"nodes": [inp("a", "2 mm"), inp("b", "3 g")]}
    answer = answer_of(one("add_node", {"graph": g, "node": op("s", "add", "a", "b")}))
    assert answer["status"] == "refused"
    assert answer["graph"] == g
    assert "not added" in answer["note"]


def test_add_node_names_the_new_node_when_it_is_malformed():
    reason = reason_of(one("add_node", {"graph": {"nodes": [inp("a", "1")]}, "node": op("s", "add", "a", "nope")}))
    assert reason.startswith("Malformed call. node.args[1]:"), reason


# ---------------------------------------------------------------- the record, through the client


def test_record_computation_returns_the_record_as_an_embedded_file():
    r = one("record_computation", {"graph": FIBER, "name": "fiber-bend-margin", "supports": {"design_node": "dec:fiber-route"}})
    answer = answer_of(r)
    assert [c.type for c in r.content] == ["text", "resource"]
    res = r.content[1].resource
    assert str(res.uri) == "calcfile:///fiber-bend-margin.calc.json"
    assert res.mime_type == "application/json"
    record = json.loads(res.text)
    assert record["result"] == {"node": "fits", "value": "true"}
    assert record["supports"] == {"design_node": "dec:fiber-route"}
    assert answer["record"]["content_hash"] == record["content_hash"]
    import hashlib

    assert answer["record"]["sha256"] == hashlib.sha256(res.text.encode("utf-8")).hexdigest()
    rerun = answer_of(one("rerun_record", {"record": record}))
    assert rerun["reproduces"] is True


def test_a_refused_computation_gives_no_record():
    r = one("record_computation", {"graph": graph(inp("a", "1 mm", "x"), inp("b", "1 g", "y"), op("s", "add", "a", "b")), "name": "bad"})
    assert [c.type for c in r.content] == ["text"]
    assert answer_of(r)["status"] == "refused"


def test_a_record_missing_a_source_reaches_the_agent_with_its_reason():
    reason = reason_of(one("record_computation", {"graph": graph(inp("a", "1 mm", None)), "name": "n"}))
    assert "source" in reason and "'a'" in reason


# ---------------------------------------------------------------- the rounded class, over the client (and in the image)


ROUNDED = graph(
    inp("var", "0.053 mm^2", "sample variance"),
    op("sd", "sqrt", "var"),
    inp("p", "0.975", "two-sided 95 %"),
    inp("dof", "4", "n - 1"),
    op("t", "t_quantile", "p", "dof"),
    op("half", "mul", "t", "sd"),
    inp("limit", "0.7 mm", "requirement"),
    op("within", "lt", "half", "limit"),
    inp("angle", "37.5 deg", "drawing"),
    op("rad", "convert", "angle", unit="rad"),
    op("s", "sin", "angle"),
    {"id": "pi", "op": "pi"},
    result="within",
)


def test_rounded_values_reach_the_agent_labelled_and_a_decided_comparison_is_answered():
    answer = json.loads(text_of(one("evaluate_graph", {"graph": ROUNDED})))
    assert answer["status"] == "ok" and answer["result"] == {"node": "within", "value": "true"}
    by = {v["node"]: v for v in answer["values"]}
    assert by["sd"]["value"] == "0.230217288664426764419484158642 mm"
    assert by["sd"]["rounded"] == {"digits": 30, "correctly_rounded": True, "error_at_most": "5e-31 mm", "from": ["sd"]}
    assert by["t"]["value"] == "2.77644510519779435780310484675"
    assert by["rad"]["value"] == "0.654498469497873591346384038183 rad"
    assert by["pi"]["value"] == "3.14159265358979323846264338328"
    assert by["half"]["rounded"]["correctly_rounded"] is False and by["half"]["rounded"]["from"] == ["t", "sd"]
    assert not any("exact" in v for v in answer["values"] if "rounded" in v)


def test_a_record_with_rounded_values_is_made_and_re_runs_over_the_client():
    made, = anyio.run(calls, [("record_computation", {"graph": ROUNDED, "name": "ci-half-width"})])
    rec = json.loads(made.content[1].resource.text)
    assert rec["schema_version"] == 3 and rec["produced_by"]["python_flint"]
    assert {v["node"] for v in rec["values"] if "rounded" in v} == {"sd", "t", "half", "rad", "s", "pi"}
    again, = anyio.run(calls, [("rerun_record", {"record": made.content[1].resource.text})])
    assert json.loads(text_of(again))["reproduces"] is True


def test_an_undecidable_comparison_reaches_the_agent_as_a_refusal():
    g = graph(inp("x", "2"), op("s", "sqrt", "x"), op("sq", "mul", "s", "s"), op("r", "eq", "sq", "x"))
    answer = json.loads(text_of(one("evaluate_graph", {"graph": g})))
    assert answer["status"] == "refused" and answer["refused"]["kind"] == "undecidable"
    assert "does not guess" in answer["refused"]["reason"]
