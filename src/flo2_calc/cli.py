"""The `flo2-calc` command: an MCP server over stdio, and nothing else.

    flo2-calc [--root DIR] [--deadline SECONDS] [--max-digits N] [--max-reply-bytes N]
    flo2-calc --version

--root (or FLO2_CALC_ROOT) names the ONE folder flo2-calc may write records
into and read them from, for local use: a plugin, a uvx command, a laptop.
Without it flo2-calc touches no file at all, which is how it runs hosted on
flo2.io (a read-only container with no network), where every record comes
back inside the reply instead. `--version` imports neither the MCP SDK nor
pint, so it answers at once in any sandbox.

The LIMITS (limits.py) are set the same way, each by a flag or its variable:
--deadline (FLO2_CALC_DEADLINE), --max-digits (FLO2_CALC_MAX_DIGITS) and
--max-reply-bytes (FLO2_CALC_MAX_REPLY_BYTES). Unset, they are the laptop
defaults; the image sets flo2.io's lower profile. A setting flo2-calc cannot
use stops it at start-up with the reason, never silently replaced.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from flo2_calc import __version__
from flo2_calc import limits as L


def resolve_root(raw: str | None) -> Path | None:
    """The folder records may be written in, resolved, or None. Exits with a
    reason when it is not a usable folder."""
    if raw is None or raw.strip() == "":
        return None
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"flo2-calc: --root {raw!r} is not a folder that exists.")
    if root == Path(root.anchor):
        sys.exit("flo2-calc: --root may not be the filesystem's root; name the folder records belong in.")
    return root


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="flo2-calc",
        description=(
            "flo2-calc: exact math and logic for the decisions in a design, as an MCP server over stdio. "
            "It stands alone: no flo2, reflow2 or other server needs to be running."
        ),
    )
    parser.add_argument("--version", action="version", version=f"flo2-calc {__version__}")
    parser.add_argument(
        "--root",
        default=os.environ.get("FLO2_CALC_ROOT"),
        help=(
            "the one folder record files may be written in and read from (default: $FLO2_CALC_ROOT; "
            "unset means no files at all, and records come back only inside replies)"
        ),
    )
    defaults = L.LAPTOP
    parser.add_argument(
        "--deadline",
        default=os.environ.get("FLO2_CALC_DEADLINE"),
        help=(
            f"seconds one call may run before it is stopped with its reason (default: $FLO2_CALC_DEADLINE, else "
            f"{L.seconds_text(defaults.deadline_ms)[:-2]}; flo2.io's sandbox: {L.seconds_text(L.FLO2_IO.deadline_ms)[:-2]})"
        ),
    )
    parser.add_argument(
        "--max-digits",
        default=os.environ.get("FLO2_CALC_MAX_DIGITS"),
        help=(
            f"the most digits any exact numerator or denominator may have (default: $FLO2_CALC_MAX_DIGITS, else "
            f"{defaults.max_digits}; flo2.io's sandbox: {L.FLO2_IO.max_digits})"
        ),
    )
    parser.add_argument(
        "--max-reply-bytes",
        default=os.environ.get("FLO2_CALC_MAX_REPLY_BYTES"),
        help=(
            f"the most bytes a reply may hold, its record included (default: $FLO2_CALC_MAX_REPLY_BYTES, else "
            f"{defaults.max_reply_bytes}; flo2.io's sandbox: {L.FLO2_IO.max_reply_bytes})"
        ),
    )
    args = parser.parse_args(argv)
    root = resolve_root(args.root)
    try:
        limits = L.from_settings(args.deadline, args.max_digits, args.max_reply_bytes)
    except ValueError as e:
        sys.exit(f"flo2-calc: {e}")

    from flo2_calc.server import build_server

    build_server(root, limits).run()
