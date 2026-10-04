"""The computation record: what a decision cites, and what anyone can re-run.

A record is one JSON object (schemas/calc-record-2.schema.json; a version 1
record, schemas/calc-record-1.schema.json, still re-runs):

    record_format   "flo2-calc computation record"
    schema_version  2
    status          "computed", or "not_computed" (below)
    name            the record's name; its file is <name>.calc.json
    supports        optional: what it supports, free text or {"design_node", "design"?}
    arithmetic      what exactness means here (numbers.ARITHMETIC_NOTE)
    graph           the graph exactly as read, every value as text
    inputs          each input: id, value (with its unit), unit, source
    values          every node's value, in the order evaluated
    result          {"node", "value"} (and "exact" when the value is rounded)
    produced_by     {"flo2_calc": version, "pint": version}
    content_hash    "sha256:<hex>" over the canonical JSON of all of the above

NOT YET COMPUTED (cap:a-not-yet-computed-record-is-completed-on-a-larger-machine).
When a recorded calculation passes a limit of the host it runs on (limits.py),
the record still comes back, with status "not_computed": the graph, the inputs
with their units and sources, `stopped` (the limit it passed, where, why, how
far it got) and `limits_in_force`, and NO values and NO result. flo2-calc on a
machine with more room completes it: record_computation takes it in place of a
graph, checks its seal, and evaluates its graph. The completed record is the
record a direct computation of that graph gives, byte for byte: completing
adds nothing about where it was first tried.

DETERMINISTIC. There is no timestamp and no machine name, and the file is
written with sorted keys, so the same graph (and name, and supports) gives a
byte-identical file wherever it is made. When it was made is the business of
whatever keeps it: flo2 keeps every version, git keeps every commit.

A COMPUTED RECORD CARRIES NO HOST LIMITS, so it stays deterministic.

THE HASH IS A SEAL, NOT A SIGNATURE. It catches a record edited by hand or
damaged in transit. It cannot stop someone from editing a record and then
recomputing the hash; re-running the graph is what catches a result that does
not follow from its inputs, and rerun_record does both.

STANDALONE (req:sister-mcp). Nothing here reaches flo2 or reflow2. A
`{"design_node": ...}` source is recorded as data and never resolved: linking
the record to the decision it supports is the agent's job, with reflow2's own
tools. Run locally, a record can also be written as a file, but only inside
the folder the server was started with (--root), and never over a different
file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from flo2_calc import __version__
from flo2_calc import limits as L
from flo2_calc import units as U
from flo2_calc.errors import CallError, LimitExceeded
from flo2_calc.evaluator import (
    Evaluation,
    Graph,
    InputNode,
    Quantity,
    evaluate,
    read_graph,
    value_json,
    values_json,
)
from flo2_calc.numbers import ARITHMETIC_NOTE

RECORD_FORMAT = "flo2-calc computation record"
SCHEMA_VERSION = 2
SCHEMA_FILES = {1: "calc-record-1.schema.json", 2: "calc-record-2.schema.json"}
COMPUTED = "computed"
NOT_COMPUTED = "not_computed"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SUFFIX = ".calc.json"
URI_PREFIX = "calcfile:///"


@cache
def schema(version: int = SCHEMA_VERSION) -> dict[str, Any]:
    text = resources.files("flo2_calc").joinpath("schemas", SCHEMA_FILES[version]).read_text(encoding="utf-8")
    return json.loads(text)


def status_of(record: dict[str, Any]) -> str:
    """A version 1 record has no status: it is always a computed one."""
    return record.get("status", COMPUTED)


def canonical(obj: Any) -> bytes:
    """The bytes a content hash is taken over: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "content_hash"}
    return "sha256:" + hashlib.sha256(canonical(body)).hexdigest()


def file_bytes(record: dict[str, Any]) -> bytes:
    """The record as its file holds it: sorted keys, indented, one newline."""
    return (json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def check_name(name: Any, path: str = "name") -> str:
    if not isinstance(name, str) or not NAME.match(name) or ".." in name:
        raise CallError(
            path,
            "a record's name is 1 to 100 letters, digits, dots, dashes and underscores, starting with a letter or "
            'digit, e.g. "fiber-bend-margin"; its file is <name>.calc.json.',
        )
    if name.endswith(SUFFIX):
        raise CallError(path, f'give the name without "{SUFFIX}"; flo2-calc adds it.')
    return name


def check_supports(supports: Any, path: str = "supports") -> str | dict[str, str] | None:
    if supports is None:
        return None
    if isinstance(supports, str):
        if not supports.strip() or len(supports) > 2000:
            raise CallError(path, "supports is free text of 1 to 2000 characters, or {\"design_node\": \"<id>\"}.")
        return supports
    if isinstance(supports, dict):
        unknown = [k for k in supports if k not in ("design_node", "design")]
        dn = supports.get("design_node")
        if unknown or not isinstance(dn, str) or not re.fullmatch(r"\S{1,200}", dn):
            raise CallError(path, 'supports names a design node as {"design_node": "<id>"} (and "design": "<design id>" for another design).')
        out = {"design_node": dn}
        if "design" in supports:
            d = supports["design"]
            if not isinstance(d, str) or not re.fullmatch(r"\S{1,200}", d):
                raise CallError(f"{path}.design", "name the design by its id, with no spaces.")
            out["design"] = d
        return out
    raise CallError(path, "supports is free text, or {\"design_node\": \"<id>\"} naming the decision in a reflow2 design.")


def check_sources(graph: Graph) -> None:
    """Every input must say where it came from: a decision rests on its inputs,
    and an input with no source is one nobody can check later. Checked before
    anything is computed."""
    missing = [n.id for n in graph.nodes if isinstance(n, InputNode) and n.source is None]
    if missing:
        raise CallError(
            "graph.nodes",
            f"a record needs every input's source, and {', '.join(repr(m) for m in missing)} "
            'has none. Give each a "source": free text (a datasheet, a measurement, "assumed") or '
            '{"design_node": "<id>"} naming where it lives in a reflow2 design.',
        )


def inputs_of(graph: Graph) -> list[dict[str, Any]]:
    """Each input with its value, its unit and its source, in the graph's order."""
    inputs = []
    for n in graph.nodes:
        if not isinstance(n, InputNode):
            continue
        entry: dict[str, Any] = {"id": n.id, **value_json(n.value), "source": n.source}
        if isinstance(n.value, Quantity):
            entry["unit"] = U.format_unit(n.value.unit)
        inputs.append(entry)
    return inputs


def _head(status: str, name: str, graph: Graph, supports: str | dict[str, str] | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_format": RECORD_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "name": name,
        "arithmetic": ARITHMETIC_NOTE,
        "graph": graph.to_json(),
        "inputs": inputs_of(graph),
    }
    if supports is not None:
        record["supports"] = supports
    return record


def build(evaluation: Evaluation, name: str, supports: str | dict[str, str] | None) -> dict[str, Any]:
    """The record of an evaluation that answered. Writing its values out is
    counted against the call's deadline and reply budget (LimitExceeded)."""
    assert evaluation.ok
    graph = evaluation.graph
    check_sources(graph)
    record = _head(COMPUTED, name, graph, supports)
    record["values"] = values_json(evaluation)
    record["result"] = {"node": graph.result, **value_json(evaluation.values[graph.result])}
    record["produced_by"] = {"flo2_calc": __version__, "pint": U.pint_version()}
    record["content_hash"] = content_hash(record)
    return record


def build_pending(graph: Graph, name: str, supports: str | dict[str, str] | None, refusal: dict[str, Any], limits: L.Limits) -> dict[str, Any]:
    """The NOT-YET-COMPUTED record of a calculation stopped at a limit: the
    graph, the inputs, the limit it passed and the limits in force; no values,
    no result."""
    check_sources(graph)
    record = _head(NOT_COMPUTED, name, graph, supports)
    record["stopped"] = L.stopped_for_record(refusal)
    record["limits_in_force"] = limits.describe()
    record["produced_by"] = {"flo2_calc": __version__, "pint": U.pint_version()}
    record["content_hash"] = content_hash(record)
    return record


def pending_problems(record: dict[str, Any]) -> list[dict[str, Any]]:
    """What does not hold in a schema-valid not-yet-computed record, beyond its
    seal: its inputs must be the ones its graph gives, and the node it stopped
    at must be in its graph. (Its values cannot be checked: it has none.)"""
    try:
        graph = read_graph(record["graph"], "record.graph")
    except CallError as e:
        return [{"field": e.path, "recorded": "(as written)", "now": f"cannot be read: {e.problem}"}]
    out = []
    again = inputs_of(graph)
    if again != record["inputs"]:
        out.append({"field": "inputs", "recorded": record["inputs"], "from_its_graph": again})
    stopped_at = record["stopped"].get("node")
    if stopped_at is not None and stopped_at not in graph.by_id():
        out.append({"field": "stopped.node", "recorded": stopped_at, "from_its_graph": "no such node"})
    return out


# ---------------------------------------------------------------- the folder it may write in


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def place(root: Path | None, requested: Any, field: str) -> Path:
    """Where a record's file goes, or comes from: inside `root`, nowhere else.
    Raises CallError naming why not."""
    if not isinstance(requested, str) or not requested.strip():
        raise CallError(field, f'give a path ending in "{SUFFIX}", relative to the folder flo2-calc was started with.')
    if root is None:
        raise CallError(
            field,
            "this flo2-calc was started with no folder it may use for files (no --root, no FLO2_CALC_ROOT), "
            "as it is when hosted on flo2.io, where the record comes back inside the reply and flo2 keeps it. "
            f"Leave {field} out, or start flo2-calc with --root <folder>.",
        )
    if not requested.endswith(SUFFIX):
        raise CallError(field, f'a record file\'s name ends in "{SUFFIX}"; "{requested}" does not.')
    target = Path(os.path.normpath(root / requested))  # an absolute `requested` replaces root here
    if not _inside(target, root):
        raise CallError(field, f'"{requested}" is outside the folder flo2-calc may use ({root}); a record is written only inside it.')
    # The deepest part of the path that exists must resolve inside root too,
    # so a symbolic link cannot carry the file elsewhere.
    existing = target
    while not existing.exists() and existing != root:
        existing = existing.parent
    if not _inside(existing.resolve(), root):
        raise CallError(field, f'"{requested}" leads outside the folder flo2-calc may use ({root}), through a link.')
    if target.is_symlink():
        raise CallError(field, f'"{requested}" is a link; flo2-calc reads and writes only plain files.')
    return target


def _same_calculation(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(a.get(k) == b.get(k) for k in ("record_format", "name", "supports", "graph", "inputs"))


def _replaceable_pending(target: Path, new: dict[str, Any]) -> bool:
    """Whether the file at `target` is an intact not-yet-computed record of
    the same calculation as `new`: the one kind of file a record may replace."""
    try:
        if target.stat().st_size > 64 * 1024 * 1024:
            return False
        old = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(old, dict) or old.get("schema_version") != 2 or old.get("status") != NOT_COMPUTED:
        return False
    import jsonschema

    if not jsonschema.Draft202012Validator(schema(2)).is_valid(old):
        return False
    return old["content_hash"] == content_hash(old) and _same_calculation(old, new)


def write(root: Path | None, requested: Any, data: bytes, field: str = "output_path") -> dict[str, Any]:
    """Write a record's file under root. Never replaces a different file, with
    one exception: a NOT-YET-COMPUTED record of the same calculation (same
    name, supports, graph and inputs, its seal intact) is replaced by its
    completion, or by a newer not-yet-computed record of it. A computed record
    is never replaced."""
    target = place(root, requested, field)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not _inside(target.parent.resolve(), root):  # type: ignore[arg-type]
        raise CallError(field, f'"{requested}" leads outside the folder flo2-calc may use.')
    replaces = False
    if target.exists():
        if target.is_file() and target.read_bytes() == data:
            return {"path": str(target), "written": False, "note": "the file was already there, byte for byte the same"}
        if not (target.is_file() and _replaceable_pending(target, json.loads(data))):
            raise CallError(
                field,
                f'"{requested}" already exists and holds something else. A record is never written over (only a '
                "not-yet-computed record of the same calculation is replaced, by its completion); choose another "
                "path, or another name.",
            )
        replaces = True
    fd, tmp = tempfile.mkstemp(prefix=".calc-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if replaces:
            os.replace(tmp, target)
        else:
            os.link(tmp, target)  # fails if the name was taken meanwhile: still never an overwrite
    except FileExistsError:
        raise CallError(field, f'"{requested}" appeared while writing; it was not written over.') from None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    out: dict[str, Any] = {"path": str(target), "written": True}
    if replaces:
        out["replaced"] = "the not-yet-computed record of this same calculation that was there"
    return out


def read_file(root: Path | None, requested: Any, guard: L.Guard, field: str = "path") -> str:
    target = place(root, requested, field)
    if not target.is_file():
        raise CallError(field, f'there is no record file "{requested}" in the folder flo2-calc may use.')
    guard.check_reply(target.stat().st_size, f'the record file "{requested}"')
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise CallError(field, f'"{requested}" is not UTF-8 text, so it is not a record.') from None


# ---------------------------------------------------------------- re-running


def load(record: Any, field: str = "record", guard: L.Guard | None = None) -> dict[str, Any]:
    """A record from its content (an object, or its JSON text), checked
    against the schema of its version. Raises CallError naming what does not
    fit, and LimitExceeded for a record larger than this host's reply budget
    (a record this host could not have returned is not one it takes in)."""
    guard = guard if guard is not None else L.Guard()
    if isinstance(record, str):
        guard.check_reply(len(record.encode("utf-8")), "this record")
        try:
            record = json.loads(record)
        except json.JSONDecodeError as e:
            raise CallError(field, f"this is not JSON, so it is not a record: {e.msg} at line {e.lineno}, column {e.colno}.") from None
    elif isinstance(record, dict):
        guard.check_reply(len(canonical(record)), "this record")
    if not isinstance(record, dict):
        raise CallError(field, "a record is a JSON object.")
    version = record.get("schema_version")
    if record.get("record_format") == RECORD_FORMAT and isinstance(version, int) and version > SCHEMA_VERSION:
        raise CallError(
            f"{field}.schema_version",
            f"this record is schema version {version}, newer than this flo2-calc ({__version__}) reads "
            f"(up to {SCHEMA_VERSION}). Re-run it with a newer flo2-calc.",
        )
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema(1 if version == 1 else SCHEMA_VERSION))
    errors = sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path))
    if errors:
        e = errors[0]
        where = field + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in e.absolute_path)
        more = f" ({len(errors) - 1} more problem(s) after this one)" if len(errors) > 1 else ""
        raise CallError(where, f"this does not fit the computation record's schema: {e.message}{more}.")
    return record


def _differences(recorded: dict[str, Any], again: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("graph", "inputs", "result"):
        if recorded.get(key) != again.get(key):
            out.append({"field": key, "recorded": recorded.get(key), "rerun": again.get(key)})
    before = {v["node"]: v for v in recorded.get("values", [])}
    after = {v["node"]: v for v in again.get("values", [])}
    for node in list(dict.fromkeys([*before, *after])):
        if before.get(node) != after.get(node):
            out.append({"field": f"values[{node}]", "recorded": before.get(node), "rerun": after.get(node)})
    if [v["node"] for v in recorded.get("values", [])] != [v["node"] for v in again.get("values", [])] and not any(
        d["field"].startswith("values[") for d in out
    ):
        out.append({"field": "values (order)", "recorded": [v["node"] for v in recorded["values"]], "rerun": [v["node"] for v in again["values"]]})
    return out


def needs_of(stopped: dict[str, Any]) -> str:
    """What a not-yet-computed record needs, in words."""
    limit = stopped["limit"]
    name, value = limit["name"], limit["value"]
    flag, env = L.SETTINGS[name]
    if "needed_at_least" in limit:
        what = f"{name} of at least {limit['needed_at_least']:,}" + (" digits" if name == "max_digits" else " bytes")
    else:
        what = f"a {name} longer than {value}"
    return f"{what} (it was stopped at {name} = {value}; set it with {flag} or {env})"


def _room_here(stopped: dict[str, Any], limits: L.Limits) -> bool:
    """Whether this host's limit is above the one the record was stopped at."""
    limit = stopped["limit"]
    name = limit["name"]
    try:
        if name == "deadline":
            return limits.deadline_ms > L.parse_deadline(str(limit["value"]))
        here = limits.max_digits if name == "max_digits" else limits.max_reply_bytes
        return here >= int(limit.get("needed_at_least", int(limit["value"]) + 1))
    except (ValueError, TypeError):  # a value the record should not hold: say no room, never fail
        return False


def _rerun_pending(record: dict[str, Any], answer: dict[str, Any], hash_ok: bool, guard: L.Guard) -> dict[str, Any]:
    stopped = record["stopped"]
    problems = pending_problems(record)
    intact = hash_ok and not problems
    answer.update(
        status=NOT_COMPUTED,
        result=None,
        reproduces=None if intact else False,
        differences=problems,
        stopped=stopped,
        limits_in_force=record["limits_in_force"],
        needs=needs_of(stopped),
    )
    where = f' at node "{stopped["node"]}" ({stopped["op"]})' if stopped["node"] is not None and stopped["op"] else (
        f' at input "{stopped["node"]}"' if stopped["node"] is not None else " while writing its reply"
    )
    if not intact:
        why = []
        if not hash_ok:
            why.append("its content hash does not match its content")
        if problems:
            why.append(f"{len(problems)} field(s) do not follow from its graph")
        answer["verdict"] = (
            "This not-yet-computed record was changed after it was made (" + "; and ".join(why) + "). It has no "
            "result yet, and it should not be completed as it stands: make it again from its graph with "
            "record_computation."
        )
        return answer
    here = guard.limits
    answer["verdict"] = (
        "This record has not been computed yet, so it has no result to check. It is intact: its content hash "
        f"matches and its inputs are the ones its graph gives. It was stopped{where} by the limits of the "
        f"flo2-calc that made it, and needs {needs_of(stopped)}. "
        + (
            f"This flo2-calc's limits are higher ({here.in_words()}): complete it here by passing it as `record` "
            "to record_computation."
            if _room_here(stopped, here)
            else "This flo2-calc's limits are no higher, so complete it on a machine with more room: pass it as "
            "`record` to record_computation on a flo2-calc started with a higher limit."
        )
    )
    return answer


def rerun(record: dict[str, Any], guard: L.Guard | None = None) -> dict[str, Any]:
    """Re-run a schema-valid record. Always a normal answer: whether it
    reproduces, and every way it does not. A not-yet-computed record has no
    result to reproduce: the answer says so, checks its seal, and says what it
    needs. A record that passes THIS host's limits while being re-run is
    neither confirmed nor denied: the answer says which limit, and where."""
    guard = guard if guard is not None else L.Guard()
    computed_hash = content_hash(record)
    hash_ok = computed_hash == record["content_hash"]
    answer: dict[str, Any] = {
        "status": "ok",
        "name": record["name"],
        "record_status": status_of(record),
        "content_hash": {"recorded": record["content_hash"], "computed": computed_hash, "matches": hash_ok},
        "recorded_with": record["produced_by"],
        "rerun_with": {"flo2_calc": __version__, "pint": U.pint_version()},
    }
    if record["produced_by"].get("flo2_calc") != __version__:
        answer["note"] = f"recorded with flo2-calc {record['produced_by'].get('flo2_calc')}, re-run with {__version__}."
    if status_of(record) == NOT_COMPUTED:
        return _rerun_pending(record, answer, hash_ok, guard)
    differences: list[dict[str, Any]] = []
    stopped: dict[str, Any] | None = None
    try:
        graph = read_graph(record["graph"], "record.graph")
        evaluation = evaluate(graph, guard)
        if evaluation.stopped:
            stopped = evaluation.refusal
        elif not evaluation.ok:
            differences.append({"field": "result", "recorded": record["result"], "rerun": {"refused": evaluation.refusal}})
            answer["result"] = None
        else:
            again = build(evaluation, record["name"], record.get("supports"))
            differences += _differences(record, again)
            answer["result"] = again["result"]
    except CallError as e:
        differences.append({"field": e.path, "recorded": "(as written)", "rerun": f"cannot be read now: {e.problem}"})
        answer["result"] = None
    except LimitExceeded as e:
        stopped = e.refusal
    if stopped is not None and hash_ok:
        answer.update(status="refused", refused=stopped, result=None, reproduces=None, differences=[])
        answer["verdict"] = (
            "This record could not be re-run here: it passes this flo2-calc's limits (" + stopped["reason"] + ") "
            "So it is neither confirmed nor contradicted. Its content hash matches. Re-run it with a flo2-calc whose "
            f"{stopped['limit']['name']} is higher ({stopped['limit']['setting']})."
        )
        return answer
    reproduces = hash_ok and not differences
    answer["reproduces"] = reproduces
    answer["differences"] = differences
    answer.setdefault("result", None)
    if reproduces:
        answer["verdict"] = "The record re-runs to exactly the values it holds, and its content hash matches."
    else:
        why = []
        if not hash_ok:
            why.append("its content hash does not match its content, so it was changed after it was made")
        if differences:
            why.append(f"{len(differences)} recorded field(s) differ from what its graph gives now")
        answer["verdict"] = "The record does NOT reproduce: " + "; and ".join(why) + "."
    return answer
