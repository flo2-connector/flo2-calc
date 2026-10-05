"""Arrays over a real MCP client session: the installed server, or (CI's image job) the image confined as
flo2's sandbox confines a helper, with flo2.io's limits (FLO2_CALC_SERVER).

ver:arrays-over-mcp in design 0bee0c00b35845f6. The worked examples of the skill and README are asked here
as an agent asks them: a regression in a few nodes instead of eighty, a 256 x 256 grid's discretised
integral and 2-D FFT inside flo2.io's limits, a record with arrays made and re-run, and the array budget
stopping a call with its reason.
"""

from __future__ import annotations

import json

import anyio
import pytest
from conftest import answer_of, graph, inp, op, reason_of, session, under_image

T = ["0", "2", "4", "6", "8", "10"]
Y = ["0.0000", "0.0291", "0.0574", "0.0868", "0.1152", "0.1447"]

REGRESSION = graph(
    inp("t", {"array": T, "unit": "s"}, "frame times"),
    inp("y", {"array": Y, "unit": "deg"}, "along-track angle, frames 1 to 6"),
    op("slope", "fit_slope", "t", "y"),
    op("slope_se", "fit_slope_se", "t", "y"),
    op("intercept", "fit_intercept", "t", "y"),
    op("residual_se", "fit_residual_se", "t", "y"),
    result="slope",
)

N = 256
GRID = graph(
    inp("lo", "-4 mm", "aperture half-width"), inp("hi", "4 mm", "aperture half-width"), inp("n", str(N), "samples per axis"),
    op("x", "linspace", "lo", "hi", "n"), op("y0", "linspace", "lo", "hi", "n"), op("y", "column", "y0"),
    op("x2", "mul", "x", "x"), op("y2", "mul", "y", "y"), op("r2", "add", "x2", "y2"),
    inp("w", "2 mm^2", "beam width squared"), op("q", "div", "r2", "w"), op("mq", "neg", "q"), op("field", "exp", "mq"),
    op("total", "sum", "field"),
    op("spectrum", "fft2", "field"), op("power", "abs", "spectrum"), op("peak", "max", "power"),
    result="peak",
)


async def calls(steps, *extra):
    out = []
    async with session(*extra) as s:
        for tool, args in steps:
            out.append(await s.call_tool(tool, args))
    return out


def test_a_regression_is_a_few_nodes_with_an_exact_slope_and_correctly_rounded_standard_errors():
    (r,) = anyio.run(calls, [("evaluate_graph", {"graph": REGRESSION})])
    a = answer_of(r)
    assert a["status"] == "ok"
    assert a["result"] == {"node": "slope", "value": "0.0144457142857142857142857142857 deg/s", "exact": "316/21875 deg/s"}
    by = {v["node"]: v for v in a["values"]}
    assert by["slope_se"]["rounded"]["correctly_rounded"] is True and by["slope_se"]["value"].startswith("0.0000374982992811619636")
    assert by["intercept"]["exact"] == "-1/35000 deg"
    assert by["t"]["array"]["values"] == T and by["t"]["array"]["unit"] == "s"


def test_a_256_by_256_grid_integral_and_2d_fft_answer_inside_the_hosts_limits():
    (r,) = anyio.run(calls, [("evaluate_graph", {"graph": GRID})])
    a = answer_of(r)
    assert a["status"] == "ok", a.get("refused")
    by = {v["node"]: v for v in a["values"]}
    assert by["field"]["array"]["shape"] == [N, N] and by["field"]["array"]["kind"] == "float64"
    assert "values" not in by["field"]["array"] and by["field"]["array"]["sha256"].startswith("sha256:")
    assert by["spectrum"]["array"]["kind"] == "complex"
    assert any("Higham" in h and "Theorem 24.2" in h for h in by["spectrum"]["float64"]["how"])
    total = by["total"]
    assert total["value"].endswith(" mm^2") is False and "float64" in total  # a sum of a plain field is plain
    assert a["result"]["float64"]["from"] and float(a["result"]["value"]) == pytest.approx(float(total["value"]), rel=1e-12)
    assert "float64" in a["exactness"]


def test_a_record_with_arrays_is_made_and_re_runs_over_the_client():
    made, = anyio.run(calls, [("record_computation", {"graph": REGRESSION, "name": "streak-rate", "supports": "dec:test"})])
    a = answer_of(made)
    assert a["status"] == "ok" and a["record"]["status"] == "computed"
    rec = json.loads(made.content[1].resource.text)
    assert rec["schema_version"] == 7 and rec["graph"]["nodes"][1]["value"] == {"array": Y, "unit": "deg"}
    (again,) = anyio.run(calls, [("rerun_record", {"record": rec})])
    assert answer_of(again)["reproduces"] is True


def test_an_array_past_the_hosts_budget_is_stopped_with_its_reason_and_the_server_answers_next():
    big = graph(inp("a", "0"), inp("b", "1"), inp("n", "4000"), op("x", "linspace", "a", "b", "n"), op("c", "column", "x"),
                op("g", "mul", "c", "x"))
    r, after = anyio.run(calls, [("evaluate_graph", {"graph": big}), ("evaluate_graph", {"graph": REGRESSION})], "--max-array-bytes", "1048576")
    a = answer_of(r)
    assert a["status"] == "refused" and a["refused"]["kind"] == "exceeds_limits"
    assert a["refused"]["limit"]["name"] == "max_array_bytes" and a["refused"]["node"] == "g"
    assert answer_of(after)["status"] == "ok"


def test_a_file_array_is_refused_with_no_folder_and_read_under_root(tmp_path):
    g = graph(inp("y", {"file": "y.csv", "unit": "deg"}, "measurements"), op("m", "mean", "y"))
    (r,) = anyio.run(calls, [("evaluate_graph", {"graph": g})])
    reason = reason_of(r)
    assert reason.startswith("Malformed call. graph.nodes[0].value.file:") and "inline" in reason
    if under_image():
        pytest.skip("the image is run with no --root, as flo2 runs it")
    (tmp_path / "y.csv").write_text("\n".join(Y) + "\n")
    (r,) = anyio.run(calls, [("evaluate_graph", {"graph": g})], "--root", str(tmp_path))
    assert answer_of(r)["result"]["value"] == "0.0722 deg"


def test_a_malformed_array_reaches_the_agent_naming_its_field():
    (r,) = anyio.run(calls, [("evaluate_graph", {"graph": graph(inp("x", {"array": ["1 mm", "2"]}))})])
    reason = reason_of(r)
    assert reason.startswith("Malformed call. graph.nodes[0].value.array[0]:") and "one unit" in reason.lower()
