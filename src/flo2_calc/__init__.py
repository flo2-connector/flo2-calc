"""flo2-calc: exact math and logic for the decisions in a design, over MCP.

An agent composes a computation graph (inputs as leaves, operators as nodes),
flo2-calc evaluates it with exact rational arithmetic and units, and can hand
back a computation record: a file the decision it supports can cite, and that
anyone can re-run to the same result.

It stands alone. Nothing here imports, calls or assumes flo2, reflow2 or any
other helper: it runs as a plugin, a uvx command or a container, by itself.
"""

from __future__ import annotations

__version__ = "0.1.0"


def main(argv: list[str] | None = None) -> None:
    """The `flo2-calc` command: an MCP server over stdio."""
    from flo2_calc.cli import main as cli_main

    cli_main(argv)
