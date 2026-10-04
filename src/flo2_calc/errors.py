"""The two ways flo2-calc says no, kept apart on purpose.

flo2's helper contract (and flo2-cad before it) fixes the split:

- A **malformed call** is the ONE case that replies `isError: true`. The call
  cannot be read: a graph with no nodes, an unknown operator, a reference to a
  node that does not exist, a cycle, a value that is not a number, a unit
  spelling flo2-calc does not know, an output path outside the root. It is a
  `CallError`, and it names the field path so the agent can fix exactly that.
- A **refused computation** is a NORMAL reply. The graph was read, but a node
  cannot be computed: units that measure different things, a division by zero,
  a logic operator handed a number. It is a `Refusal`, and the reply says which
  node, which operation and why, and gives no result.

- A **limit passed** is a refused computation too, of its own kind
  (`exceeds_limits`): the graph was read and could be computed, but not within
  the limits this host set at start-up (a deadline per call, a budget for the
  digits of any exact number and for the reply). It is a `LimitExceeded`, and
  it is a NORMAL reply naming the limit, its value, the node reached and how
  large the numbers had grown (limits.py). It is never a crash.

The MCP python-sdk 2.x passes on the text of a `ToolError` and hides the text
of every other exception, so the server turns a `CallError` into a `ToolError`
(server.py). A `Refusal` or a `LimitExceeded` never becomes an error at all.
"""

from __future__ import annotations

from typing import Any


class CallError(Exception):
    """A malformed call, naming the field path it is about."""

    def __init__(self, path: str, problem: str) -> None:
        super().__init__(f"{path}: {problem}")
        self.path = path
        self.problem = problem


class Refusal(Exception):
    """A computation that cannot be done. Carried in a normal reply."""

    def __init__(self, reason: str, *, kind: str, units: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind
        self.units = units


class LimitExceeded(Exception):
    """A host-set limit passed. Carried in a normal reply, as a refusal of kind
    "exceeds_limits": `refusal` is that refusal, already complete (limits.Guard
    writes it, because only the guard knows the limits, the node reached and the
    sizes the numbers had grown to)."""

    def __init__(self, refusal: dict[str, Any]) -> None:
        super().__init__(refusal["reason"])
        self.refusal = refusal

    @property
    def limit(self) -> str:
        return self.refusal["limit"]["name"]


def at(path: str, key: str | int) -> str:
    """Join a field path the way messages print it: `graph.nodes[2].args[0]`."""
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key
