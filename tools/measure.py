#!/usr/bin/env python3
"""Measure the image's peak memory in flo2's sandbox shape, for the broker's cap.

    python3 tools/measure.py [--image flo2-calc:local] [--cap 256m]

Starts ONE container of the image under flo2-tool-sandbox's flags (no network,
a read-only root, a 64 MB /tmp, user 65534, no capabilities, one CPU, 64
processes, the memory cap with no swap), drives a session over stdio that is
heavier than a decision needs (a 500-node graph, records, re-runs, refusals,
a 484-node graph of rounded operators at 1,000 digits each, recorded and
re-run, and arrays: a 256 x 256 grid's discretised integral and 2-D FFT, a
250 x 250 FFT checked against Arb's rigorous DFT, exact and float64
regressions over thousands of points),
then RUNAWAY calculations that only the image's limits stop (a huge power, a
chain of squarings, the heaviest graph its digits budget allows, sent whole and
recorded), then reads the container's cgroup memory.peak before closing it.
Prints one JSON line: every runaway call must come back as a normal reply that
names its limit, and the container must still answer afterwards. Needs docker,
the image, the mcp client (pip install '.[test]'), and a cgroup v2 host that
exposes memory.peak.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def heavy_graph(n: int = 500) -> dict:
    """n nodes: a chain of exact additions (with a unit) and multiplications
    (by a plain ratio), ending in a comparison. Its fractions grow to a few
    hundred bits: heavier than any decision, and every node answers."""
    nodes: list[dict] = [
        {"id": "x0", "value": "1.5 mm", "source": "measure.py"},
        {"id": "d", "value": "1/3 mm", "source": "measure.py"},
        {"id": "c", "value": "7/5", "source": "measure.py"},
    ]
    i = 0
    while len(nodes) < n - 1:
        i += 1
        nodes.append({"id": f"x{i}", "op": "add", "args": [f"x{i - 1}", "d"]} if i % 2 else {"id": f"x{i}", "op": "mul", "args": [f"x{i - 1}", "c"]})
    nodes.append({"id": "bigger", "op": "gt", "args": [f"x{i}", "x0"]})
    return {"nodes": nodes}


def rounded_graph(n: int = 480, digits: int = 1000) -> dict:
    """n nodes of the rounded class, every one at `digits` significant digits
    (the most a node may ask for): roots, exponentials, logarithms,
    trigonometry, deg-rad conversion and every distribution. Python-flint is
    loaded and works at about 3,400 bits for each."""
    nodes: list[dict] = [
        {"id": "x", "value": "0.7", "source": "measure.py"}, {"id": "p", "value": "0.975", "source": "measure.py"},
        {"id": "k", "value": "4", "source": "measure.py"}, {"id": "a", "value": "37.5 deg", "source": "measure.py"},
    ]
    kinds = [("sqrt", ["x"], {}), ("exp", ["x"], {}), ("ln", ["x"], {}), ("sin", ["a"], {}), ("atan", ["x"], {"unit": "rad"}),
             ("convert", ["a"], {"unit": "rad"}), ("normal_quantile", ["p"], {}), ("chi2_sf", ["x", "k"], {}),
             ("t_quantile", ["p", "k"], {})]
    for i in range(n):
        op, args, extra = kinds[i % len(kinds)]
        nodes.append({"id": f"n{i}", "op": op, "args": args, "digits": digits, **extra})
    return {"nodes": nodes}


def grid_graph(n: int = 256) -> dict:
    """A Gaussian field on an n x n grid built from two axes: its discretised
    integral, its 2-D FFT, the spectrum's magnitude and peak."""
    return {"nodes": [
        {"id": "lo", "value": "-4 mm", "source": "measure.py"}, {"id": "hi", "value": "4 mm", "source": "measure.py"},
        {"id": "n", "value": str(n), "source": "measure.py"}, {"id": "w", "value": "2 mm^2", "source": "measure.py"},
        {"id": "x", "op": "linspace", "args": ["lo", "hi", "n"]}, {"id": "y0", "op": "linspace", "args": ["lo", "hi", "n"]},
        {"id": "y", "op": "column", "args": ["y0"]}, {"id": "x2", "op": "mul", "args": ["x", "x"]},
        {"id": "y2", "op": "mul", "args": ["y", "y"]}, {"id": "r2", "op": "add", "args": ["x2", "y2"]},
        {"id": "q", "op": "div", "args": ["r2", "w"]}, {"id": "mq", "op": "neg", "args": ["q"]},
        {"id": "field", "op": "exp", "args": ["mq"]}, {"id": "total", "op": "sum", "args": ["field"]},
        {"id": "spectrum", "op": "fft2", "args": ["field"]}, {"id": "power", "op": "abs", "args": ["spectrum"]},
        {"id": "peak", "op": "max", "args": ["power"]}], "result": "peak"}


def regression_graph(n: int) -> dict:
    """A straight-line fit over n points: exact up to 4,096 of them, float64 past that."""
    xs = [str(k) for k in range(n)]
    ys = [f"{3 * k + (k * 7919) % 13}/10" for k in range(n)]
    return {"nodes": [
        {"id": "x", "value": {"array": xs, "unit": "s"}, "source": "measure.py"},
        {"id": "y", "value": {"array": ys, "unit": "mm"}, "source": "measure.py"},
        {"id": "b", "op": "fit_slope", "args": ["x", "y"]}, {"id": "se", "op": "fit_slope_se", "args": ["x", "y"]},
        {"id": "sd", "op": "sd_sample", "args": ["y"]}], "result": "se"}


def runaway_graphs() -> dict[str, dict]:
    """Calculations past any sensible limit: each must be STOPPED, with its reason."""
    nines = "9" * 80
    squarings = [{"id": "x0", "value": "123456789012345678901234567890", "source": "measure.py"}]
    squarings += [{"id": f"x{i}", "op": "mul", "args": [f"x{i - 1}", f"x{i - 1}"]} for i in range(1, 31)]
    heaviest = [{"id": "x0", "value": nines, "source": "measure.py"}, {"id": "e", "value": "23", "source": "measure.py"},
                {"id": "y0", "op": "pow", "args": ["x0", "e"]}, {"id": "one", "value": "1/7", "source": "measure.py"}]
    heaviest += [{"id": f"y{i}", "op": "add", "args": [f"y{i - 1}", "one"]} for i in range(1, 497)]
    return {
        "huge_power": {"nodes": [{"id": "x", "value": nines}, {"id": "e1", "value": "250"}, {"id": "y", "op": "pow", "args": ["x", "e1"]},
                                 {"id": "e2", "value": "1000"}, {"id": "z", "op": "pow", "args": ["y", "e2"]}]},
        "squarings": {"nodes": squarings},
        "huge_exp": {"nodes": [{"id": "x", "value": "1e5"}, {"id": "y", "op": "exp", "args": ["x"]}]},
        "far_tail": {"nodes": [{"id": "x", "value": "1e6"}, {"id": "q", "op": "normal_sf", "args": ["x"]}]},
        "huge_grid": {"nodes": [{"id": "a", "value": "0"}, {"id": "b", "value": "1"}, {"id": "n", "value": "100000"},
                                {"id": "x", "op": "linspace", "args": ["a", "b", "n"]}, {"id": "c", "op": "column", "args": ["x"]},
                                {"id": "g", "op": "mul", "args": ["c", "x"]}]},
        "heaviest_allowed": {"nodes": heaviest},
    }


async def drive(command: list[str], name: str) -> dict:
    params = StdioServerParameters(command=command[0], args=command[1:])
    started = time.perf_counter()
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        calls = 0
        for _ in range(3):
            r = await s.call_tool("evaluate_graph", {"graph": heavy_graph()})
            calls += 1
            answer = json.loads(r.content[0].text)
            assert answer["status"] == "ok" and answer["result"]["value"] == "true", answer.get("refused")
            rec = await s.call_tool("record_computation", {"graph": heavy_graph(), "name": "heavy"})
            calls += 1
            record = json.loads(rec.content[1].resource.text) if len(rec.content) > 1 else None
            if record:
                await s.call_tool("rerun_record", {"record": record})
                calls += 1
            await s.call_tool("evaluate_graph", {"graph": {"nodes": [{"id": "a", "value": "2 mm"}, {"id": "b", "value": "3 g"}, {"id": "s", "op": "add", "args": ["a", "b"]}]}})
            calls += 1
        for _ in range(3):
            r = await s.call_tool("evaluate_graph", {"graph": rounded_graph()})
            calls += 1
            answer = json.loads(r.content[0].text)
            assert answer["status"] == "ok", answer.get("refused")
            rec = await s.call_tool("record_computation", {"graph": rounded_graph(), "name": "rounded"})
            calls += 1
            record = json.loads(rec.content[1].resource.text) if len(rec.content) > 1 else None
            if record:
                again = json.loads((await s.call_tool("rerun_record", {"record": record})).content[0].text)
                assert again["reproduces"] is True, again.get("differences")
                calls += 1
        array_seconds: dict[str, float] = {}
        for label, g, tool in (("grid_256", grid_graph(256), "evaluate_graph"), ("grid_256_record", grid_graph(256), "record_computation"),
                               ("grid_250_arb", grid_graph(250), "evaluate_graph"), ("fit_4000_exact", regression_graph(4000), "evaluate_graph"),
                               ("fit_20000_float64", regression_graph(20000), "evaluate_graph")):
            t0 = time.perf_counter()
            args = {"graph": g} if tool == "evaluate_graph" else {"graph": g, "name": label}
            r = await s.call_tool(tool, args)
            calls += 1
            answer = json.loads(r.content[0].text)
            assert answer["status"] == "ok", (label, answer.get("refused"))
            if tool == "record_computation":
                record = json.loads(r.content[1].resource.text)
                again = json.loads((await s.call_tool("rerun_record", {"record": record})).content[0].text)
                calls += 1
                assert again["reproduces"] is True, again.get("differences")
            array_seconds[label] = round(time.perf_counter() - t0, 2)
        seconds = time.perf_counter() - started
        runaway: dict[str, str] = {}
        for label, g in runaway_graphs().items():
            for tool, args in (("evaluate_graph", {"graph": g}), ("record_computation", {"graph": g, "name": label})):
                if tool == "record_computation" and label != "heaviest_allowed":
                    continue
                r = await s.call_tool(tool, args)
                calls += 1
                assert not r.is_error, r.content[0].text[:300]
                answer = json.loads(r.content[0].text)
                said = answer["status"]
                if said == "refused":
                    said = f"stopped at {answer['refused']['limit']['name']}" if answer["refused"]["kind"] == "exceeds_limits" else said
                    if answer.get("record"):
                        said += f", record {answer['record']['status']}"
                runaway[f"{tool}:{label}"] = said
        alive = json.loads((await s.call_tool("evaluate_graph", {"graph": {"nodes": [{"id": "a", "value": "0.1"}, {"id": "b", "value": "0.2"}, {"id": "s", "op": "add", "args": ["a", "b"]}]}})).content[0].text)
        assert alive["result"]["value"] == "0.3", "the container answered after the runaway calls"
        cid = subprocess.run(["docker", "ps", "-q", "--no-trunc", "--filter", f"name={name}"], capture_output=True, text=True).stdout.strip()
        peak_file = Path(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/memory.peak")
        peak = int(peak_file.read_text()) if cid and peak_file.exists() else None
        return {"calls": calls, "seconds": round(seconds, 2), "array_seconds": array_seconds, "runaway": runaway, "alive_after": True,
                "container": cid[:12], "peak_bytes": peak}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="flo2-calc:local")
    ap.add_argument("--cap", default="256m")
    args = ap.parse_args()
    name = f"flo2-calc-measure-{uuid.uuid4().hex[:8]}"
    command = [
        "docker", "run", "--rm", "-i", "--name", name, "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--memory", args.cap, "--memory-swap", args.cap,
        "--cpus", "1", "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534:65534", args.image,
    ]
    out = anyio.run(drive, command, name)
    out.update(image=args.image, cap=args.cap)
    if out["peak_bytes"] is not None:
        out["peak_mib"] = round(out["peak_bytes"] / 1048576, 1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
