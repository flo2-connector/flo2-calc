"""A kept record re-derived when an input changes: the same graph, new inputs, and what moved (flo2-calc 0.14.0).

req:a-calc-record-keeps-its-formula-and-is-re-derived-when-an-input-changes (design 0bee0c00b35845f6, accepted
2026-10-27), under dec:calc-keeps-live-formulas-and-solves-for-a-variable-proved-on-a-test-case-first and
dec:solving-ships-as-a-separate-helper-image-so-calc-stays-lean-and-exact.

A record already keeps its formula: its graph is every operation it evaluated, and its inputs keep each value with
its unit and its source. Since 0.13.0 a design that keeps the record can say it is OWED a re-run when a bound
quantity changes. This module does the re-run with the new value: `rederive` takes a kept, computed record and new
values for one or more of its inputs, evaluates the same graph with them under calc's own arithmetic (exact, or
rounded with a proven bound, as ever), and returns the new record and what moved. No new dependency: the proof of
concept (fact:the-symbolic-proof-of-concept-passed-...-2026-10-27) found live formulas need no symbolic algebra.

WHAT IT CHECKS FIRST, so that "old -> new" says only what the change moved:
  - the record is a computed one (a not-yet-computed record has no values to move: record_computation completes it);
  - it is of schema version 7 or later: a record of version 1 to 6 was made under the rules before delta_K and an
    older writing, so the values it holds and the ones today's rules give are not the same calculation;
  - its seal (content hash) is intact, and it re-runs here to the values it holds (rerun_record's check), so a value
    that differs after the change differs because of the change;
  - each change names one of its INPUTS, once, with a new value and a source; a computed node is not an input;
  - each new value measures what the input it replaces measured: the same dimension, a temperature for a
    temperature and a change of temperature for a change, a power level for a level, true/false for true/false, an
    array for an array. Any unit of that kind is taken (ft for m), and calc converts it exactly where it combines.

WHAT IT RETURNS. The new record is the record of the changed graph, written by this flo2-calc (schema version 12),
with the same name and `supports`, and `history`: the record's own history, if any, and one entry for this change,
naming the record it was re-derived from by its content hash, each input changed (old and new value and source),
each result that moved (old -> new) and each that did not. The history is sealed by the content hash like every
other field, and rerun_record re-runs the new record to the same content. The answer says, for every result, whether
it moved, and lists every other node whose value changed (`values`, which fills the host's answer budget after the
outcome: answer.py).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from flo2_calc import arrays as A
from flo2_calc import decibels as D
from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc import units as U
from flo2_calc.errors import CallError
from flo2_calc.evaluator import (
    InputNode,
    OpNode,
    Quantity,
    STOPPED_NEXT,
    WORKING_REST_RECORD,
    evaluate,
    evaluation_json,
    exactness,
    read_graph,
    read_nodes,
    shown_back,
    shown_json,
)

FIRST_VERSION = R.DELTA_K_FROM  # the oldest schema version re-derived: today's rules and writing
CHANGE_KEYS = ("input", "value", "source", "note")
NEXT = (
    "Keep the new record with the decision it supports, in place of the one you passed (its history names that one "
    "by its content hash), and quote the moved results there; a design that bound an input to a design quantity can "
    "now say the record is up to date. rerun_record checks it any time later."
)


def _refused(kind: str, reason: str, node: str | None = None, **more: Any) -> dict[str, Any]:
    return {"status": "refused", "refused": {"node": node, "op": None, "kind": kind, "reason": reason, **more}, "result": None}


# ---------------------------------------------------------------- what a value measures


def _measures(value: Any) -> tuple[Any, ...]:
    """What a value measures, for telling whether a new value can replace it: true/false, or a number or an array
    of a dimension, with whether it is a temperature reading or a power level (each of which has an offset, so it is
    never the same thing as a change of the same dimension)."""
    if isinstance(value, bool):
        return ("true/false",)
    if isinstance(value, A.Array):
        if value.kind == A.BOOL:
            return ("array", "true/false")
        unit = value.unit
        shape = "array"
    else:
        assert isinstance(value, Quantity)
        unit = value.unit
        shape = "number"
    reading = "temperature" if (U.scale_of(unit) or unit == U.KELVIN) else ("level" if D.level_of(unit) else None)
    return (shape, U.dimension(unit), reading)


def _describe(value: Any) -> str:
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, A.Array):
        return "an array of true/false" if value.kind == A.BOOL else f"an array of {U.describe_dimension(value.unit)}"
    return U.describe_dimension(value.unit)


def _unit_text(value: Any) -> str:
    if isinstance(value, bool) or (isinstance(value, A.Array) and value.kind == A.BOOL):
        return ""
    return U.format_unit(value.unit)


def _shown(raw: Any) -> str:
    """A value as the call or the graph wrote it, for a reason."""
    if isinstance(raw, dict):
        return "an array" if "array" in raw else ("a data file" if "file" in raw else "an object")
    return str(raw)


# ---------------------------------------------------------------- the changes


def _read_changes(changes: Any, graph_json: dict[str, Any], graph: Any, data_root: Any, exact: int | None) -> list[tuple[int, dict[str, Any], InputNode]]:
    """(the node's place in the graph, the change as given, the new input node), each checked. Raises CallError."""
    if not isinstance(changes, list) or not changes:
        raise CallError(
            "changes",
            'give one or more changes, each {"input": "<id>", "value": "<new value with its unit>", "source": "<where it '
            'came from>"}.',
        )
    nodes = graph.by_id()
    inputs = [n.id for n in graph.nodes if isinstance(n, InputNode)]
    place = {n["id"]: i for i, n in enumerate(graph_json["nodes"])}
    out: list[tuple[int, dict[str, Any], InputNode]] = []
    seen: set[str] = set()
    for k, ch in enumerate(changes):
        path = f"changes[{k}]"
        if not isinstance(ch, dict):
            raise CallError(path, 'a change is {"input": "<id>", "value": "<new value>", "source": "<where it came from>"}.')
        unknown = [key for key in ch if key not in CHANGE_KEYS]
        if unknown:
            raise CallError(f"{path}.{unknown[0]}", f"a change has only {', '.join(CHANGE_KEYS)}.")
        name = ch.get("input")
        if not isinstance(name, str) or name not in nodes:
            raise CallError(
                f"{path}.input",
                f'"{name}" is not one of this record\'s inputs. Its inputs are ' + ", ".join(inputs) + "."
                if isinstance(name, str)
                else 'name the input to change by its id, e.g. "input": "' + (inputs[0] if inputs else "x") + '".',
            )
        if isinstance(nodes[name], OpNode):
            raise CallError(
                f"{path}.input",
                f'"{name}" is computed ({nodes[name].op}), not an input: change the inputs it rests on. This record\'s '
                "inputs are " + ", ".join(inputs) + ".",
            )
        if name in seen:
            raise CallError(f"{path}.input", f'"{name}" is changed twice; give each input one new value.')
        seen.add(name)
        if "value" not in ch:
            raise CallError(f"{path}.value", f'give "{name}" its new value, with its unit, e.g. "1350 ft^2".')
        if "source" not in ch:
            raise CallError(
                f"{path}.source",
                f'say where the new value of "{name}" came from: free text, {{"design_node": "<id>"}}, or '
                '{"design_quantity": "<id>"} for the design quantity it holds. A record keeps every input\'s source.',
            )
        node = {"id": name, "value": ch["value"], "source": ch["source"]}
        note = ch["note"] if "note" in ch else graph_json["nodes"][place[name]].get("note")
        if note is not None:
            node["note"] = note
        new = read_nodes([(node, path)], data_root=data_root, exact_limit=exact).nodes[0]
        assert isinstance(new, InputNode)
        old = nodes[name]
        assert isinstance(old, InputNode)
        if new.raw == old.raw and new.source == old.source and new.note == old.note:
            raise CallError(f"{path}.value", f'"{name}" already holds {_shown(old.raw)} from that source; this change changes nothing.')
        out.append((place[name], node, new))
    return out


def _mismatch(old: InputNode, new: InputNode) -> dict[str, Any] | None:
    """The refusal when the new value measures something else than the one it replaces, saying what arrived."""
    if _measures(old.value) == _measures(new.value):
        return None
    return _refused(
        "unit_mismatch",
        f'The new value of "{old.id}", {_shown(new.raw)}, is {_describe(new.value)}, but "{old.id}" holds '
        f"{_shown(old.raw)}, {_describe(old.value)}. A new value must measure what the input it replaces measured "
        "(any unit of that kind is taken, and converted exactly), so the record's graph stays the same calculation. "
        "Nothing was computed. If the graph itself should change, compose it again with record_computation.",
        node=old.id,
        units=[_unit_text(old.value), _unit_text(new.value)],
    )


# ---------------------------------------------------------------- what moved


def _brief(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """A value, briefly: its text, its exact fraction or its bound; an array by its description and sha256."""
    if entry is None:
        return None
    out: dict[str, Any] = {"value": entry["value"]}
    if "exact" in entry:
        out["exact"] = entry["exact"]
    if "array" in entry:
        out["sha256"] = entry["array"]["sha256"]
    for label in ("rounded", "float64"):
        if label in entry:
            out[label] = {"error_at_most": entry[label]["error_at_most"]}
    return out


def _state(entry: dict[str, Any]) -> dict[str, Any]:
    """An input as the record keeps it, without its id."""
    return {k: v for k, v in entry.items() if k != "id"}


def _moves(before: list[dict[str, Any]], after: list[dict[str, Any]], results: tuple[str, ...], inputs: set[str]) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """(the results that moved, the results that did not, every other computed node that moved), in order."""
    old = {v["node"]: v for v in before}
    new = {v["node"]: v for v in after}
    moved: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for r in results:
        if old.get(r) == new.get(r):
            unchanged.append(r)
        else:
            moved.append({"node": r, "old": _brief(old.get(r)), "new": _brief(new.get(r))})
    others = [
        {"node": v["node"], "old": _brief(old.get(v["node"])), "new": _brief(v)}
        for v in after
        if v["node"] not in results and v["node"] not in inputs and old.get(v["node"]) != v
    ]
    return moved, unchanged, others


# ---------------------------------------------------------------- re-deriving


def rederive(record: dict[str, Any], changes: Any, guard: L.Guard | None = None, data_root: Any = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(the answer, the new record or None). `record` is schema-valid (record.load). A malformed change raises
    CallError; everything else is a normal answer."""
    guard = guard if guard is not None else L.Guard()
    if R.status_of(record) != R.COMPUTED:
        raise CallError(
            "record.status",
            "this record has not been computed yet (status \"not_computed\"), so it has no values to re-derive: "
            "complete it first by passing it as `record` to record_computation, then re-derive the completed record.",
        )
    version = record["schema_version"]
    if version < FIRST_VERSION:
        return _refused(
            "older_rules",
            f"This record is schema version {version}, made by flo2-calc {record['produced_by'].get('flo2_calc')} under "
            f"the rules and writing before version {FIRST_VERSION} (a change of temperature converted to K was a bare "
            "K, and formula lines carried fewer values), so today's rules would not give the values it holds, and an "
            "old -> new comparison would mix the two. It still re-runs as made (rerun_record). To re-derive it, make "
            "it again from its graph with record_computation, then re-derive that record.",
        ), None
    if record["content_hash"] != R.content_hash(record):
        return _refused(
            "record_changed",
            "This record was changed after it was made (its content hash does not match its content), so it was not "
            "re-derived: the record re-derived must be the calculation that was kept. Re-derive the record as it was "
            "made, or make it again from its graph with record_computation.",
        ), None

    exact = R.exact_limit_of(record)
    try:
        old_graph = read_graph(record["graph"], "record.graph", data_root, exact)
    except CallError as e:
        return _refused(
            "record_does_not_reproduce",
            f"This record's graph cannot be read by this flo2-calc ({e.path}: {e.problem}), so it cannot be re-derived "
            "here. rerun_record says the same. Make it again from its graph, corrected, with record_computation.",
        ), None
    changed = _read_changes(changes, record["graph"], old_graph, data_root, exact)  # a malformed change: CallError
    old_nodes = old_graph.by_id()
    for _place, _given, new in changed:
        refusal = _mismatch(old_nodes[new.id], new)  # type: ignore[arg-type]
        if refusal is not None:
            return refusal, None

    # It re-runs here to the values it holds: then whatever differs after the change, the change moved.
    check = R.rerun(record, guard, data_root)
    if check.get("status") == "refused":  # it passes this host's limits, or a data file it reads is not here
        answer = {k: check[k] for k in ("status", "refused", "result", "verdict") if k in check}
        if check["refused"].get("kind") == "exceeds_limits":
            answer["next"] = STOPPED_NEXT
        return answer, None
    if check["reproduces"] not in (True, "within_bound"):
        return _refused(
            "record_does_not_reproduce",
            "This record does not re-run here to the values it holds (" + check["verdict"] + "), so an old -> new "
            "comparison would not say what the change moved. Make it again from its graph with record_computation, "
            "then re-derive that record.",
            differences=len(check.get("differences", [])),
        ), None
    guard.reply_bytes = 0  # the check's writing is done; what follows is the new record's
    guard.array_bytes = 0

    if exact is not None and exact != guard.limits.max_exact_elements:
        guard.limits = replace(guard.limits, max_exact_elements=exact)  # the record's arithmetic, as rerun uses
    if check["reproduces"] is True:
        before = record["values"]
    else:  # an FFT's last bits differ on this processor: compare like with like, both computed here
        old_ev = evaluate(old_graph, guard)
        before = R.build(old_ev, record["name"], record.get("supports"))["values"]
        guard.reply_bytes = 0

    graph_json = {**record["graph"], "nodes": list(record["graph"]["nodes"])}
    for place, given, _new in changed:
        graph_json["nodes"][place] = given
    new_graph = read_graph(graph_json, "changes", data_root, exact)
    ev = evaluate(new_graph, guard)
    if not ev.ok:
        answer = evaluation_json(ev)
        answer.pop("values", None)
        if ev.stopped:
            answer["next"] = (
                "The changed graph passed a limit of this host (not a rule of the math): re-derive it on a flo2-calc "
                "with a higher limit, or compose the changed graph with record_computation, which returns it as a "
                "not-yet-computed record."
            )
        else:
            answer["note"] = "No record was made: the changed graph does not answer, so the record you passed stands."
        return answer, None

    old_inputs = {i["id"]: i for i in record["inputs"]}
    new_inputs = {i["id"]: i for i in R.inputs_of(new_graph)}
    change_list = [{"input": n.id, "old": _state(old_inputs[n.id]), "new": _state(new_inputs[n.id])} for _p, _g, n in changed]
    new = R.build(ev, record["name"], record.get("supports"))
    moved, unchanged, others = _moves(before, new["values"], new_graph.result_ids, set(new_inputs))
    entry = {
        "rederived_from": {
            "content_hash": record["content_hash"],
            "schema_version": version,
            "flo2_calc": record["produced_by"].get("flo2_calc"),
        },
        "changed": change_list,
        "moved": moved,
        "unchanged": unchanged,
    }
    new = R.with_history(new, [*record.get("history", []), entry])
    answer: dict[str, Any] = {
        "status": "ok",
        "name": record["name"],
        "changed": change_list,
        "moved": moved,
        "unchanged": unchanged,
        **({"results": new["results"]} if "results" in new else {"result": new["result"]}),
        "record": {"rederived_from": entry["rederived_from"]},
        "exactness": exactness(ev),
        "inputs_bound": R.inputs_bound(new),
        "next": NEXT,
        **shown_json(shown_back(ev, new["values"]), WORKING_REST_RECORD),
        "values": others,
    }
    if check["reproduces"] == "within_bound":
        answer["compared"] = (
            "the record's FFT values re-run here within their stated bounds, not byte for byte, so old -> new compares "
            "the old graph and the new one both computed here"
        )
    return answer, new

