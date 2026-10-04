"""flo2-calc on its own, with nothing else present.

The owner's constraint, 2026-10-04 (req:sister-mcp): "flo2-calc is stand-alone
as is flo2-ifc and reflow2. It shouldn't require other flo2 sub-systems in
order function." So this starts the installed server by itself: a clean
environment (no FLO2_*, no MCP configuration, a fresh HOME), a fresh working
folder, and --root naming the one folder it may write in. It goes through
evaluate, record, write under the root, and re-run (from the file and from the
content), and checks the edges of the root: a path outside it, a link out of
it, an existing different file, and a server started with no root at all.

ver:standalone-round-trip in design 0bee0c00b35845f6.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from conftest import answer_of, graph, inp, installed_command, op, reason_of, under_image
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import flo2_calc

pytestmark = pytest.mark.skipif(under_image(), reason="a local run: the image is hosted with no folder to write in")

BATTERY = graph(
    inp("capacity", "2400 mAh", "cell datasheet"),
    inp("draw", "180 mA", {"design_node": "con:led-current"}),
    op("hours", "div", "capacity", "draw"),
    op("in_h", "convert", "hours", unit="h"),
    inp("wanted", "12 h", "lit through one night"),
    op("enough", "ge", "in_h", "wanted"),
)


def clean_env(home: Path) -> dict[str, str]:
    """Only what a process needs to start: no FLO2_*, nothing about flo2 or reflow2."""
    return {"PATH": os.path.dirname(sys.executable) + os.pathsep + "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8"}


async def alone(steps, *, root: Path | None, work: Path, extra: tuple[str, ...] = ()):
    args = (["--root", str(root)] if root is not None else []) + list(extra)
    params = StdioServerParameters(command=installed_command(), args=args, env=clean_env(work / "home"), cwd=str(work))
    out = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        for tool, arguments in steps:
            out.append(await s.call_tool(tool, arguments))
    return out


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "home").mkdir()
    (tmp_path / "records").mkdir()
    return tmp_path


def test_evaluate_record_write_and_rerun_with_nothing_else_present(work: Path):
    root = work / "records"
    evaluated, recorded = anyio.run(
        lambda: alone(
            [
                ("evaluate_graph", {"graph": BATTERY}),
                ("record_computation", {"graph": BATTERY, "name": "night-light", "supports": {"design_node": "dec:battery-choice"},
                                        "output_path": "decisions/night-light.calc.json"}),
            ],
            root=root,
            work=work,
        )
    )
    assert answer_of(evaluated)["result"] == {"node": "enough", "value": "true"}
    answer = answer_of(recorded)
    written = root / "decisions" / "night-light.calc.json"
    assert answer["record"]["saved"] == {"path": str(written), "written": True}
    embedded = recorded.content[1].resource.text
    assert written.read_text(encoding="utf-8") == embedded, "the file on disk is the file in the reply, byte for byte"

    from_file, from_content = anyio.run(
        lambda: alone(
            [("rerun_record", {"path": "decisions/night-light.calc.json"}), ("rerun_record", {"record": embedded})],
            root=root,
            work=work,
        )
    )
    for rerun in (answer_of(from_file), answer_of(from_content)):
        assert rerun["reproduces"] is True, rerun
        assert rerun["result"] == {"node": "enough", "value": "true"}

    # Nothing was written anywhere but the record, in the root.
    assert sorted(p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()) == [
        "records/decisions/night-light.calc.json"
    ]


def test_the_same_record_again_is_not_rewritten_and_a_different_file_is_never_overwritten(work: Path):
    root = work / "records"
    first, again, other = anyio.run(
        lambda: alone(
            [
                ("record_computation", {"graph": BATTERY, "name": "n", "output_path": "n.calc.json"}),
                ("record_computation", {"graph": BATTERY, "name": "n", "output_path": "n.calc.json"}),
                ("record_computation", {"graph": graph(inp("x", "1 mm", "t")), "name": "n", "output_path": "n.calc.json"}),
            ],
            root=root,
            work=work,
        )
    )
    assert answer_of(first)["record"]["saved"]["written"] is True
    assert answer_of(again)["record"]["saved"]["written"] is False
    reason = reason_of(other)
    assert "already exists" in reason and "never written over" in reason
    assert json.loads((root / "n.calc.json").read_text())["result"]["node"] == "enough"


@pytest.mark.parametrize("path, words", [
    ("../outside.calc.json", "outside the folder"),
    ("/tmp/elsewhere.calc.json", "outside the folder"),
    ("record.json", 'ends in ".calc.json"'),
    ("escape/out.calc.json", "through a link"),
])
def test_a_record_is_written_only_inside_the_root(work: Path, path: str, words: str):
    root = work / "records"
    (root / "escape").symlink_to(work / "home")
    [result] = anyio.run(
        lambda: alone([("record_computation", {"graph": BATTERY, "name": "n", "output_path": path})], root=root, work=work)
    )
    reason = reason_of(result)
    assert words in reason, reason
    assert not list((work / "home").iterdir()), "nothing was written through the link"
    assert not (work / "outside.calc.json").exists()


def test_with_no_root_writing_and_reading_files_are_refused_with_a_clear_reason(work: Path):
    wrote, read, evaluated = anyio.run(
        lambda: alone(
            [
                ("record_computation", {"graph": BATTERY, "name": "n", "output_path": "n.calc.json"}),
                ("rerun_record", {"path": "n.calc.json"}),
                ("record_computation", {"graph": BATTERY, "name": "n"}),
            ],
            root=None,
            work=work,
        )
    )
    for result, field in ((wrote, "output_path"), (read, "path")):
        reason = reason_of(result)
        assert reason.startswith(f"Malformed call. {field}:"), reason
        assert "started with no folder" in reason and "--root" in reason
    assert answer_of(evaluated)["status"] == "ok", "with no root, the record still comes back inside the reply"
    assert not any(p.is_file() for p in work.rglob("*"))


GROWING = graph(
    inp("ratio", "1234567/1000000", {"design_node": "con:gain-per-stage"}),
    op("r2", "mul", "ratio", "ratio"),
    op("r4", "mul", "r2", "r2"),
    op("r8", "mul", "r4", "r4"),
    op("r16", "mul", "r8", "r8"),
    op("r32", "mul", "r16", "r16"),
    inp("limit", "1e6", "requirement"),
    op("under", "lt", "r32", "limit"),
)


def test_a_pending_record_saved_on_a_small_machine_is_completed_in_place_on_a_larger_one(work: Path):
    """The whole of option (c), standalone: the small machine (--max-digits 100)
    saves a not-yet-computed record under its root; the larger one (the
    defaults) completes it to the same path, which replaces the pending file
    and nothing else; the completed file is the direct computation's, byte for
    byte, and re-runs from its path."""
    root = work / "records"
    path = "decisions/stage-gain.calc.json"
    [made] = anyio.run(
        lambda: alone([("record_computation", {"graph": GROWING, "name": "stage-gain", "output_path": path})],
                      root=root, work=work, extra=("--max-digits", "100"))
    )
    answer = answer_of(made)
    assert answer["status"] == "refused" and answer["record"]["status"] == "not_computed"
    assert answer["record"]["saved"]["written"] is True
    pending_text = (root / path).read_text(encoding="utf-8")
    assert json.loads(pending_text)["status"] == "not_computed"

    completed, again, direct, rerun = anyio.run(
        lambda: alone(
            [
                ("record_computation", {"record": pending_text, "output_path": path}),
                ("record_computation", {"record": pending_text, "output_path": path}),
                ("record_computation", {"graph": GROWING, "name": "stage-gain"}),
                ("rerun_record", {"path": path}),
            ],
            root=root,
            work=work,
        )
    )
    done = answer_of(completed)
    assert done["status"] == "ok" and done["record"]["saved"]["written"] is True
    assert "replaced" in done["record"]["saved"]
    on_disk = (root / path).read_text(encoding="utf-8")
    assert on_disk == completed.content[1].resource.text == direct.content[1].resource.text
    assert answer_of(again)["record"]["saved"]["written"] is False, "completing it again gives the same file, left alone"
    assert answer_of(rerun)["reproduces"] is True
    # Once computed, the file is never written over, not even by a not-yet-computed record of it.
    [small_again] = anyio.run(
        lambda: alone([("record_computation", {"graph": GROWING, "name": "stage-gain", "output_path": path})],
                      root=root, work=work, extra=("--max-digits", "100"))
    )
    reason = reason_of(small_again)
    assert "already exists" in reason and "never written over" in reason
    assert (root / path).read_text(encoding="utf-8") == on_disk
    assert sorted(p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()) == [f"records/{path}"]


def test_a_pending_record_is_never_replaced_by_a_different_calculation(work: Path):
    root = work / "records"
    [first] = anyio.run(lambda: alone([("record_computation", {"graph": GROWING, "name": "n", "output_path": "n.calc.json"})],
                                      root=root, work=work, extra=("--max-digits", "100")))
    assert answer_of(first)["record"]["status"] == "not_computed"
    [other] = anyio.run(lambda: alone([("record_computation", {"graph": BATTERY, "name": "n", "output_path": "n.calc.json"})],
                                      root=root, work=work))
    assert "already exists" in reason_of(other)
    assert json.loads((root / "n.calc.json").read_text())["status"] == "not_computed"


def test_the_package_imports_nothing_of_flo2_reflow2_or_another_helper():
    """Nothing in it may import, call or assume flo2, reflow2 or flo2-cad/ifc."""
    allowed = {
        "__future__", "argparse", "ast", "dataclasses", "decimal", "fractions", "functools", "hashlib", "importlib",
        "json", "math", "os", "pathlib", "re", "sys", "tempfile", "threading", "time", "typing",
        "flo2_calc", "mcp", "pydantic", "pint", "jsonschema", "flint", "numpy", "io",
    }
    package = Path(flo2_calc.__file__).parent
    for source in sorted(package.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] in allowed, f"{source.name} imports {name}"
