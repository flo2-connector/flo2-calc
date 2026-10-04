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
reads each text block as JSON and keeps each resource as a file.

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
from flo2_calc import record as R
from flo2_calc.errors import CallError
from flo2_calc.evaluator import OPS, evaluate, evaluation_json, read_graph, read_nodes

INSTRUCTIONS = (
    "flo2-calc does exact math and logic for the decisions in a design, so a decision can carry the computation "
    "that supports it instead of a number the model worked out in its head. Compose a graph of named nodes: inputs "
    '("value": "1.4 mm", with a "source") and operations ("op": "sub", "args": ["a", "b"]). Arithmetic is exact '
    "(no binary floats), units are carried and checked, and units that measure different things are refused, "
    "never stripped. evaluate_graph takes a whole graph; add_node builds one node at a time; record_computation "
    "returns a computation record, a .calc.json file to link to the decision it supports; rerun_record checks that "
    "a record still reproduces. flo2-calc stands alone: it never calls reflow2 or anything else. Linking a record "
    "to a design is the agent's job, with the design tool's own tools."
)

GRAPH_HELP = (
    'The computation graph: {"nodes": [...], "result": "<id>"} ("result" defaults to the last node). An input '
    'node is {"id": "bend", "value": "1.4 mm", "source": "fiber datasheet"}: the value is text, a number with its '
    'unit as reflow2 spells it (mm, g, V, mA, ...), a plain number ("0.1", "1/3", or a JSON integer), or true/false; '
    'the source is free text or {"design_node": "con:..."} naming a node in a reflow2 design (recorded, never '
    'resolved). An operation node is {"id": "margin", "op": "sub", "args": ["cavity", "bend"]}; "convert" also '
    'takes "unit". Operators: '
    + "; ".join(f"{k} ({v[3]})" for k, v in OPS.items())
    + ". Units: one '/', '*' between units, '^n' for powers, e.g. \"mm^2\", \"m/s^2\", \"kg/(m*s^2)\"."
)

Graph = Annotated[dict[str, Any], Field(description=GRAPH_HELP)]


def _reply(payload: dict[str, Any], files: tuple[tuple[str, str], ...] = ()) -> CallToolResult:
    content: list[Any] = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=1))]
    for name, text in files:
        content.append(
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(uri=f"{R.URI_PREFIX}{name}", mime_type="application/json", text=text),
            )
        )
    return CallToolResult(content=content, is_error=False)


def _guarded(fn: Callable[..., CallToolResult]) -> Callable[..., CallToolResult]:
    """Every failure leaves as a ToolError whose text the agent can read."""

    @functools.wraps(fn)
    def call(*args: Any, **kwargs: Any) -> CallToolResult:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except CallError as e:
            raise ToolError(f"Malformed call. {e.path}: {e.problem}") from e
        except Exception as e:  # noqa: BLE001 - a bug, said as one rather than hidden
            raise ToolError(
                f"flo2-calc failed unexpectedly ({type(e).__name__}: {e}). This is a fault in flo2-calc, not in "
                "the call; nothing was computed or written."
            ) from e

    return call


def build_server(root: Path | None = None) -> MCPServer:
    """The server. `root` is the one folder it may write records in and read
    them from (None: no files at all, as when hosted)."""
    server = MCPServer(name="flo2-calc", version=__version__, instructions=INSTRUCTIONS)
    reading = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    @server.tool(
        name="evaluate_graph",
        title="Evaluate a computation graph",
        annotations=reading,
        description=(
            "Evaluate a whole computation graph in one call, exactly, with units. Returns the result and every "
            "node's value in the order evaluated. A computation that cannot be done (units that measure different "
            'things, division by zero, a number where true/false is needed) comes back as status "refused", naming '
            "the node, the operation and why, with no result. A graph that cannot be read is an error naming the field."
        ),
    )
    @_guarded
    def evaluate_graph(graph: Graph) -> CallToolResult:
        return _reply(evaluation_json(evaluate(read_graph(graph))))

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
        items = [(n, f"graph.nodes[{i}]") for i, n in enumerate(before)] + [(node, "node")]
        grown = read_nodes(items)
        ev = evaluate(grown)
        answer = evaluation_json(ev)
        if ev.ok:
            answer = {
                "status": "ok",
                "added": {"node": grown.result, **{k: v for k, v in answer["result"].items() if k != "node"}},
                "values": answer["values"],
                "graph": grown.to_json(),
            }
        else:
            answer["graph"] = {"nodes": [n for n in before]}
            answer["note"] = "The node was not added; the graph is as you sent it."
        return _reply(answer)

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
            "elsewhere and never over a different file. A refused computation gives no record."
        ),
    )
    @_guarded
    def record_computation(
        graph: Graph,
        name: Annotated[str, Field(description='The record\'s name, e.g. "fiber-bend-margin"; its file is <name>.calc.json.')],
        supports: Annotated[
            str | dict[str, str] | None,
            Field(description='Optional: what this computation supports, free text or {"design_node": "dec:..."} (recorded, never resolved).'),
        ] = None,
        output_path: Annotated[
            str | None,
            Field(description="Optional, local runs only: where to also write the file, a path ending in .calc.json inside the folder flo2-calc was started with (--root)."),
        ] = None,
    ) -> CallToolResult:
        name = R.check_name(name)
        supports_ = R.check_supports(supports)
        if output_path is not None:
            R.place(root, output_path, "output_path")  # refuse before computing, not after
        ev = evaluate(read_graph(graph))
        if not ev.ok:
            answer = evaluation_json(ev)
            answer["note"] = "No record was made: a record holds only a computation that answered."
            return _reply(answer)
        rec = R.build(ev, name, supports_)
        data = R.file_bytes(rec)
        file_name = f"{name}{R.SUFFIX}"
        answer = {
            "status": "ok",
            "result": rec["result"],
            "record": {
                "file": file_name,
                "uri": f"{R.URI_PREFIX}{file_name}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "content_hash": rec["content_hash"],
            },
            "values": rec["values"],
            "next": "Link this record to the decision it supports in the design (an Artifact that documents the "
            "decision), and quote its result there. rerun_record checks it any time later.",
        }
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
            "with. Every difference is named. A record that does not reproduce is a normal answer, not an error."
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
        if path is not None:
            loaded = R.load(R.read_file(root, path, "path"), "path")
        else:
            loaded = R.load(record, "record")
        return _reply(R.rerun(loaded))

    return server


TOOLS = ("evaluate_graph", "add_node", "record_computation", "rerun_record")
READ_ONLY = {"evaluate_graph": True, "add_node": True, "record_computation": False, "rerun_record": True}
