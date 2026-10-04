#!/usr/bin/env python3
"""Measure the image's peak memory in flo2's sandbox shape, for the broker's cap.

    python3 tools/measure.py [--image flo2-calc:local] [--cap 256m]

Starts ONE container of the image under flo2-tool-sandbox's flags (no network,
a read-only root, a 64 MB /tmp, user 65534, no capabilities, one CPU, 64
processes, the memory cap with no swap), drives a session over stdio that is
heavier than a decision needs (a 500-node graph, records, re-runs, refusals),
then reads the container's cgroup memory.peak before closing it. Prints one
JSON line. Needs docker, the image, the mcp client (pip install '.[test]'),
and a cgroup v2 host that exposes memory.peak.
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
        seconds = time.perf_counter() - started
        cid = subprocess.run(["docker", "ps", "-q", "--no-trunc", "--filter", f"name={name}"], capture_output=True, text=True).stdout.strip()
        peak_file = Path(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/memory.peak")
        peak = int(peak_file.read_text()) if cid and peak_file.exists() else None
        return {"calls": calls, "seconds": round(seconds, 2), "status": "ok" if not r.is_error else "error", "container": cid[:12], "peak_bytes": peak}


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
