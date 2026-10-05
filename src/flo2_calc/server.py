"""flo2-calc's MCP tools, on the official MCP python-sdk 2.x (MCPServer).

FOUR TOOLS, lower_snake_case (flo2's helper contract, point 5):

  evaluate_graph       read-only   a whole graph in one call: its result and every node's value
  add_node             read-only   the graph so far plus one node: that node's value, and the grown graph
  record_computation   writes      evaluate, and return the computation record as a file
  rerun_record         read-only   re-run a record and say whether it reproduces

"Writes" is the class flo2's door reads: record_computation makes a file to
keep (the door keeps it as a new version in the person's design), and, run
locally with --root, it may write that file to disk. The other three change
nothing anywhere.

REPLIES. One text block of JSON, then, for record_computation, the record as
an embedded resource `calcfile:///<name>.calc.json` (application/json). flo2
reads each text block as JSON and keeps each resource as a file. A reply with
a result carries "exactness": the result is exact for these inputs, as
written, and no more accurate than they are (numbers.EXACT_FOR_THESE_INPUTS),
except any value labelled "rounded", which is not exact
(numbers.EXACT_BUT_ROUNDED). Every reply shows the computation back
(formula.py): "formula", its equations, and "working", its numbered steps,
each in plain text with LaTeX beside it; a record holds every step.

THE SKILL, SERVED (skill.py). Beside the four tools, the server offers
skills/support-a-decision-with-math/SKILL.md as an MCP prompt of that name and
as a resource, so a client that starts flo2-calc as a plain command gets the
same guidance a plugin install does. Prompts and resources are not tools:
flo2's door, which holds exactly the four tools, is unchanged by them.

LIMITS (limits.py). Every call runs under the host's limits, set at start-up:
a deadline, a digits budget for exact numbers, and a reply budget. Passing one
is a NORMAL reply, status "refused" with kind "exceeds_limits", naming the
limit, its value, the node reached and how large the numbers had grown. When
record_computation is stopped that way, the record still comes back, as a
NOT-YET-COMPUTED record (status "not_computed": the graph, the inputs, the
limit it passed, no result), and record_computation on a flo2-calc with more
room completes it: it takes that record in place of a graph. The four tools,
their names and their read/write classes are unchanged by this: flo2's door
holds exactly these four.

ERRORS (contract point 4; dec:unit-mismatch-rejects). A computation that
cannot be done is a NORMAL reply: {"status": "refused", "refused": {node, op,
kind, reason, units}}, with no result and no record. isError is reserved for
a malformed call, and is raised as ToolError, because the SDK passes on a
ToolError's text and hides every other exception's: an agent told only "Error
executing tool evaluate_graph" has nothing to correct. Even an unexpected
failure is turned into a ToolError that says so.
"""

from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents, ToolAnnotations
from pydantic import Field

from flo2_calc import __version__
from flo2_calc import limits as L
from flo2_calc import record as R
from flo2_calc import skill as SK
from flo2_calc.units import VOCABULARY as U_VOCABULARY
from flo2_calc.errors import CallError, LimitExceeded
from flo2_calc.evaluator import (
    OPS,
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

INSTRUCTIONS = (
    "flo2-calc does exact math and logic for the decisions in a design, so a decision can carry the computation "
    "that supports it instead of a number the model worked out in its head. Compose a graph of named nodes: inputs "
    '("value": "1.4 mm", with a "source") and operations ("op": "sub", "args": ["a", "b"]). Arithmetic is exact '
    "for the inputs as written (no binary floats; a typed 3.14159 is taken as that decimal, not as pi), units are "
    "carried and checked, and units that measure different things are refused, never stripped. pi, e, roots, exp, "
    "ln, log10, non-whole powers, trigonometry (sin to atan2, in deg or rad), deg-rad conversion, decibel "
    "conversions and the normal, chi-square and Student-t distributions give ROUNDED values: correctly rounded to 30 "
    'significant digits (or a node\'s "digits"), labelled "rounded" with "error_at_most", never called exact, and '
    "exact wherever the result is rational. A comparison, ceil, floor or round of a rounded value is answered only "
    "when its error bound decides it. dB is its own kind of value: a dB-to-ratio conversion must be told \"power\" "
    "or \"amplitude\". ARRAYS (vectors and grids, one unit each, written {\"array\": [...], \"unit\": \"mm\"}) work "
    "element by element with every operator, with numpy's broadcasting; they reduce (sum, mean, min, max, count_true, "
    "any, all, with an axis for a grid), give statistics over data (variance and sd, sample or population, named; a "
    "least-squares fit with standard errors) and the FFT. An exact array stays exact through rational operations; an "
    "FFT, a function over an array, or a large array is float64, labelled \"float64\" with a rigorous "
    "\"error_at_most\" and how it was found. Every reply shows the computation back as a formula and as numbered "
    "steps (plain text, with LaTeX beside it), so you can check it is the computation you meant. evaluate_graph takes "
    "a whole graph; add_node builds one node at a time; record_computation returns a computation record, a .calc.json "
    "file to link to the decision it supports; rerun_record checks that a record still reproduces. flo2-calc "
    "calculates and you reason: it never decides which equation applies, and a domain's own formulas (ring sizes, "
    "metal weight, a building's areas) belong to the helper that owns the domain. READ THE SKILL before using it: the "
    f"prompt \"{SK.NAME}\", or the resource {SK.RESOURCE_URI}. flo2-calc stands alone: it never calls reflow2 or "
    "anything else. Linking a record to a design is the agent's job, with the design tool's own tools."
)

GRAPH_HELP = (
    'The computation graph: {"nodes": [...], "result": "<id>"} ("result" defaults to the last node; a list of ids '
    'reports each of them by name, as "results"). An input '
    'node is {"id": "bend", "value": "1.4 mm", "source": "fiber datasheet"}: the value is text, a number with its '
    'unit as reflow2 spells it (mm, g, V, mA, ...), a plain number ("0.1", "1/3", or a JSON integer), or true/false. '
    'A value is one number: build arithmetic as operation nodes, never inside a value. Temperatures are K, degC or '
    'degF ("25 degC"), and a change of temperature is delta_degC or delta_degF; a bare C or F is refused (write '
    'coulomb or farad for those). Money is an ISO 4217 code ("12.50 USD"); currencies are never converted except by '
    'a rate you give as an input with its source ("0.92 EUR/USD"). A gain or loss is in dB ("6 dB", "0.2 dB/m"), '
    'and a power level in dBm or dBW ("-30 dBm"); convert turns a level into mW or W and back. '
    'The source is free text or {"design_node": "con:..."} naming a node in a reflow2 design (recorded, never '
    'resolved). An operation node is {"id": "margin", "op": "sub", "args": ["cavity", "bend"]}; "convert" also '
    'takes "unit", as do asin, acos, atan and atan2 ("deg" or "rad", the unit of the angle they give), phase (the '
    'same, for the angle of a complex value), magnitude (the unit to take a quantity\'s number in) and with_unit (the '
    'unit it states, with a "source" saying where that unit comes from). db_to_ratio and ratio_to_db need "kind": '
    '"power" or "amplitude", never defaulted. A rounded operator may take "digits" (1 to 1000 significant digits; 30 '
    'when left out). ceil, floor and round may take "places" (decimal places; 0 when left out), and round a "mode". '
    'A rounded value comes back with "rounded": {"digits", "correctly_rounded", "error_at_most", "from"}, never with '
    '"exact". An ARRAY input is {"id": "t", "value": {"array": ["0", "2", "4.5"], "unit": "s"}, "source": "..."}: one '
    'or two dimensions (a list of rows for a grid), ONE unit for the whole array, each element a number as text or '
    'all true/false; or, run locally, {"file": "data/x.csv", "unit": "mm"} inside the folder flo2-calc was started '
    'with (the record keeps the file\'s sha256). Every operator works element by element on arrays (shapes equal, or '
    'a single value, a row against a grid, a column against a row); sum, product, mean, min, max, count_true, any and '
    'all take one array and an optional "axis" (0: each column, 1: each row); abs of an FFT\'s complex values is '
    'their modulus. An array comes back as {"array": {"shape", "kind", "unit", "sha256", "values"}} (values only up '
    'to 1,024 elements); a float64 value carries "float64": {"error_at_most", "how", "from"}. Operators: '
    + "; ".join(f"{k} ({v[3]})" for k, v in OPS.items())
    + ". Units: one '/', '*' between units, '^n' for powers, e.g. \"mm^2\", \"m/s^2\", \"kg/(m*s^2)\". Units "
    "flo2-calc knows: " + ", ".join(sorted(U_VOCABULARY, key=str.lower)) + "."
)

Graph = Annotated[dict[str, Any], Field(description=GRAPH_HELP)]


def _shown_pending(g: Any) -> dict[str, Any]:
    """The formula and working of a graph not computed: equations, no values."""
    from flo2_calc.evaluator import Evaluation

    return shown_json(shown_back(Evaluation(g, L.Guard()), None), WORKING_REST_RECORD)


def _text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _reply(payload: dict[str, Any], files: tuple[tuple[str, str], ...] = (), guard: L.Guard | None = None) -> CallToolResult:
    """The reply. With a guard, it is first held to the host's reply budget: a
    reply too large to send becomes a refusal saying so (exceeds_limits)."""
    text = _text(payload)
    if guard is not None:
        size = len(text.encode("utf-8")) + sum(len(t.encode("utf-8")) for _, t in files)
        try:
            guard.check_reply(size)
        except LimitExceeded as e:
            return _reply(_stopped_answer(e.refusal))
    content: list[Any] = [TextContent(type="text", text=text)]
    for name, body in files:
        content.append(
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(uri=f"{R.URI_PREFIX}{name}", mime_type="application/json", text=body),
            )
        )
    return CallToolResult(content=content, is_error=False)


def _stopped_answer(refusal: dict[str, Any]) -> dict[str, Any]:
    return {"status": "refused", "refused": refusal, "result": None, "values": None, "next": STOPPED_NEXT}


def _guarded(fn: Callable[..., CallToolResult]) -> Callable[..., CallToolResult]:
    """Every failure leaves as a ToolError whose text the agent can read; a
    limit passed leaves as a normal reply that says which."""

    @functools.wraps(fn)
    def call(*args: Any, **kwargs: Any) -> CallToolResult:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except LimitExceeded as e:
            return _reply(_stopped_answer(e.refusal))
        except CallError as e:
            raise ToolError(f"Malformed call. {e.path}: {e.problem}") from e
        except Exception as e:  # noqa: BLE001 - a bug, said as one rather than hidden
            raise ToolError(
                f"flo2-calc failed unexpectedly ({type(e).__name__}: {e}). This is a fault in flo2-calc, not in "
                "the call; nothing was computed or written."
            ) from e

    return call


def build_server(root: Path | None = None, limits: L.Limits = L.LAPTOP) -> MCPServer:
    """The server. `root` is the one folder it may write records in and read
    them from (None: no files at all, as when hosted). `limits` are the host's
    limits for every call (limits.py)."""
    L.allow_int_text(limits.max_digits)
    server = MCPServer(
        name="flo2-calc",
        version=__version__,
        instructions=INSTRUCTIONS
        + f" This flo2-calc's limits: {limits.in_words()}. A calculation past one is stopped with its reason "
        "(status refused, kind exceeds_limits), never cut short, and record_computation then returns a "
        "not-yet-computed record that flo2-calc on a machine with more room completes.",
    )
    reading = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    @server.prompt(name=SK.NAME, title="Support a decision with math", description=SK.front_matter().get("description"))
    def served_skill() -> str:
        """The skill's body, read from its one file."""
        return SK.body()

    @server.resource(SK.RESOURCE_URI, name=SK.NAME, title="The skill: support a decision with math", mime_type=SK.MIME_TYPE,
                     description="How and when to use flo2-calc: skills/support-a-decision-with-math/SKILL.md, as it is.")
    def served_skill_file() -> str:
        return SK.text()

    @server.tool(
        name="evaluate_graph",
        title="Evaluate a computation graph",
        annotations=reading,
        description=(
            "Evaluate a whole computation graph in one call, exactly for the inputs as written, with units. Returns "
            "the result and every node's value in the order evaluated, and says what exact means (\"exactness\"). A "
            "value from pi, e, a root, exp, a logarithm, trigonometry or a distribution is labelled \"rounded\", with "
            "its digits and error bound, and is not exact. A computation that cannot be done (units that measure "
            "different things, division by zero, a number where true/false is needed, a comparison a rounded value's "
            'error bound cannot decide) comes back as status "refused", naming '
            "the node, the operation and why, with no result. A graph that cannot be read is an error naming the field."
        ),
    )
    @_guarded
    def evaluate_graph(graph: Graph) -> CallToolResult:
        guard = L.Guard(limits)
        return _reply(evaluation_json(evaluate(read_graph(graph, data_root=root, exact_limit=limits.max_exact_elements), guard)), guard=guard)

    @server.tool(
        name="add_node",
        title="Add one node and see its value",
        annotations=reading,
        description=(
            "Build a graph one node at a time, inspecting each value as you go. Pass the graph so far (as the last "
            "add_node returned it; leave it out for the first node) and one new node. Returns the new node's value, "
            "every value so far, and the grown graph to pass next time. Nothing is kept between calls: the graph you "
            "pass is the whole state, so the graph built this way is the same graph, and gives the same result, as "
            "sending it whole to evaluate_graph. A node that would be refused is not added: the graph comes back "
            "unchanged with the reason."
        ),
    )
    @_guarded
    def add_node(
        node: Annotated[dict[str, Any], Field(description="The one node to add: an input or an operation, as in evaluate_graph.")],
        graph: Annotated[
            dict[str, Any] | None,
            Field(description='The graph so far, {"nodes": [...]}, as the last add_node returned it. Leave out for the first node.'),
        ] = None,
    ) -> CallToolResult:
        before: list[Any] = []
        if graph is not None:
            if not isinstance(graph, dict) or set(graph) - {"nodes", "result"} or not isinstance(graph.get("nodes"), list):
                raise CallError("graph", 'the graph so far is {"nodes": [...]}, as the last add_node returned it.')
            before = graph["nodes"]
        guard = L.Guard(limits)
        items = [(n, f"graph.nodes[{i}]") for i, n in enumerate(before)] + [(node, "node")]
        grown = read_nodes(items, data_root=root, exact_limit=limits.max_exact_elements)
        ev = evaluate(grown, guard)
        answer = evaluation_json(ev)
        if answer["status"] == "ok":
            answer = {
                "status": "ok",
                "added": {"node": grown.result, **{k: v for k, v in answer["result"].items() if k != "node"}},
                "values": answer["values"],
                "formula": answer["formula"],
                "working": answer["working"],
                "graph": grown.to_json(),
                "exactness": answer["exactness"],
            }
        else:
            answer["graph"] = {"nodes": [n for n in before]}
            answer["note"] = "The node was not added; the graph is as you sent it."
        return _reply(answer, guard=guard)

    @server.tool(
        name="record_computation",
        title="Evaluate and return the computation record",
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False),
        description=(
            "Evaluate a graph and return its computation record: a .calc.json file (an embedded resource, "
            "calcfile:///<name>.calc.json) holding the graph, each input with its unit and source, every value, the "
            "result, flo2-calc's version and a content hash. Link that file to the decision it supports, with the "
            "design tool's own tools. Every input needs a source. The same graph always gives the same file. Run "
            "locally, output_path also writes it inside the folder flo2-calc was started with (--root), never "
            "elsewhere and never over a different file. A refused computation gives no record. A calculation that "
            "passes this host's limits (a deadline, a digits budget, a reply budget) still gives a record, marked "
            'status "not_computed": the graph, the inputs and the limit it passed, with no result. To complete '
            "one, pass it as `record` (instead of `graph` and `name`) to record_computation on a flo2-calc with more "
            "room: it returns the computed record, the same one a direct computation of that graph gives."
        ),
    )
    @_guarded
    def record_computation(
        graph: Annotated[
            dict[str, Any] | None,
            Field(description=GRAPH_HELP + " Leave it out when completing a not-yet-computed `record`."),
        ] = None,
        name: Annotated[
            str | None,
            Field(description='The record\'s name, e.g. "fiber-bend-margin"; its file is <name>.calc.json. Needed with a graph; a completed record keeps its own.'),
        ] = None,
        supports: Annotated[
            str | dict[str, str] | None,
            Field(description='Optional: what this computation supports, free text or {"design_node": "dec:..."} (recorded, never resolved).'),
        ] = None,
        output_path: Annotated[
            str | None,
            Field(description="Optional, local runs only: where to also write the file, a path ending in .calc.json inside the folder flo2-calc was started with (--root)."),
        ] = None,
        record: Annotated[
            dict[str, Any] | str | None,
            Field(description='Instead of a graph: a not-yet-computed record (status "not_computed", the object or its JSON text) to complete here.'),
        ] = None,
    ) -> CallToolResult:
        guard = L.Guard(limits)
        if record is not None:
            if graph is not None:
                raise CallError("graph", "pass a graph to compute, or a not-yet-computed `record` to complete, not both.")
            pending = R.load(record, "record", guard)
            if R.status_of(pending) != R.NOT_COMPUTED:
                raise CallError(
                    "record.status",
                    "record_computation completes a not-yet-computed record (status \"not_computed\"); this one is "
                    "already computed. Check it with rerun_record.",
                )
            for given, key in ((name, "name"), (supports, "supports")):
                if given is not None and given != pending.get(key):
                    raise CallError(key, f"a not-yet-computed record is completed with its own {key}; leave {key} out, or give the record's.")
            hash_ok = pending["content_hash"] == R.content_hash(pending)
            problems = R.pending_problems(pending, root)
            if not hash_ok or problems:
                why = (["its content hash does not match its content"] if not hash_ok else []) + (
                    [f"{len(problems)} field(s) do not follow from its graph"] if problems else []
                )
                return _reply(
                    {
                        "status": "refused",
                        "refused": {
                            "node": None,
                            "op": None,
                            "kind": "record_changed",
                            "reason": "This not-yet-computed record was changed after it was made ("
                            + "; and ".join(why)
                            + "), so it was not completed: a completed record must be the calculation that was "
                            "stopped. Make it again from its graph, or complete the record as it was made.",
                            "differences": problems,
                        },
                        "result": None,
                    },
                    guard=guard,
                )
            name_, supports_ = pending["name"], pending.get("supports")
            g = read_graph(pending["graph"], "record.graph", root, limits.max_exact_elements)
        else:
            if graph is None:
                raise CallError("graph", "pass the graph to compute (or, to complete one, a not-yet-computed `record`).")
            if name is None:
                raise CallError("name", 'give the record a name, e.g. "fiber-bend-margin"; its file is <name>.calc.json.')
            name_ = R.check_name(name)
            supports_ = R.check_supports(supports)
            g = read_graph(graph, data_root=root, exact_limit=limits.max_exact_elements)
        if output_path is not None:
            R.place(root, output_path, "output_path")  # refuse before computing, not after
        R.check_sources(g)
        ev = evaluate(g, guard)
        if not ev.ok and not ev.stopped:
            answer = evaluation_json(ev)
            answer["note"] = "No record was made: a record holds only a computation that answered."
            return _reply(answer, guard=guard)
        file_name = f"{name_}{R.SUFFIX}"
        if ev.ok:
            try:
                rec = R.build(ev, name_, supports_)
                data = R.file_bytes(rec)
                answer = {
                    "status": "ok",
                    **({"results": rec["results"]} if "results" in rec else {"result": rec["result"]}),
                    "record": _record_facts(rec, data, file_name),
                    "values": rec["values"],
                    **shown_json(shown_back(ev, rec["values"]), WORKING_REST_RECORD),
                    "exactness": exactness(ev),
                    "next": "Link this record to the decision it supports in the design (an Artifact that documents "
                    "the decision), and quote its result there. rerun_record checks it any time later.",
                }
                guard.check_reply(len(_text(answer).encode("utf-8")) + len(data))
                if output_path is not None:
                    answer["record"]["saved"] = R.write(root, output_path, data)
                return _reply(answer, ((file_name, data.decode("utf-8")),))
            except LimitExceeded as e:
                stop = e.refusal
        else:
            stop = ev.refusal
        return _pending_reply(g, name_, supports_, stop, file_name, output_path)

    def _record_facts(rec: dict[str, Any], data: bytes, file_name: str) -> dict[str, Any]:
        return {
            "status": rec["status"],
            "file": file_name,
            "uri": f"{R.URI_PREFIX}{file_name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "content_hash": rec["content_hash"],
        }

    def _pending_reply(g: Any, name_: str, supports_: Any, stop: dict[str, Any], file_name: str, output_path: str | None) -> CallToolResult:
        """A calculation stopped at a limit: the refusal, and the not-yet-computed record."""
        pending = R.build_pending(g, name_, supports_, stop, limits)
        data = R.file_bytes(pending)
        answer: dict[str, Any] = {
            "status": "refused",
            "refused": stop,
            "result": None,
            **_shown_pending(g),
            "record": _record_facts(pending, data, file_name),
            "next": "The record came back NOT YET COMPUTED: it holds the graph, the inputs with their sources and the "
            f"limit it passed, and no result. It needs {R.needs_of(pending['stopped'])}. Keep it with the decision, "
            "and complete it on a machine with more room: pass it as `record` to record_computation on a flo2-calc "
            "started with a higher limit. The completed record is the one a direct computation gives.",
        }
        if len(data) + len(_text(answer).encode("utf-8")) > limits.max_reply_bytes:
            answer["record"] = None
            answer["next"] = (
                f"Even the not-yet-computed record ({len(data):,} bytes) is larger than this host's reply budget "
                f"({limits.max_reply_bytes:,} bytes), so it was not returned. Run this graph with a flo2-calc that "
                "has more room."
            )
            return _reply(answer)
        if output_path is not None:
            answer["record"]["saved"] = R.write(root, output_path, data)
        return _reply(answer, ((file_name, data.decode("utf-8")),))

    @server.tool(
        name="rerun_record",
        title="Re-run a computation record",
        annotations=reading,
        description=(
            "Re-run a computation record and say whether it reproduces: its content hash must match its content, "
            "and its graph must give exactly the values it holds. Pass the record itself (`record`, the object or "
            "its JSON text) or, run locally, `path` to a .calc.json file inside the folder flo2-calc was started "
            "with. Every difference is named. A record that does not reproduce is a normal answer, not an error. "
            'A not-yet-computed record (status "not_computed") has no result yet: the answer checks its seal and '
            "says what it needs to be completed (record_computation completes it). A record that passes this "
            "host's limits while being re-run is neither confirmed nor contradicted, and the answer says which limit."
        ),
    )
    @_guarded
    def rerun_record(
        record: Annotated[
            dict[str, Any] | str | None,
            Field(description="The record: the JSON object, or its text."),
        ] = None,
        path: Annotated[
            str | None,
            Field(description="Or, local runs only: a .calc.json file inside the folder flo2-calc was started with (--root)."),
        ] = None,
    ) -> CallToolResult:
        if (record is None) == (path is None):
            raise CallError("record", "pass exactly one: `record` (the record itself) or `path` (its file).")
        guard = L.Guard(limits)
        if path is not None:
            loaded = R.load(R.read_file(root, path, guard, "path"), "path", guard)
        else:
            loaded = R.load(record, "record", guard)
        return _reply(R.rerun(loaded, guard, root), guard=guard)

    return server


TOOLS = ("evaluate_graph", "add_node", "record_computation", "rerun_record")
READ_ONLY = {"evaluate_graph": True, "add_node": True, "record_computation": False, "rerun_record": True}
