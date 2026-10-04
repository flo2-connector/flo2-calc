"""Shared helpers: the command that starts flo2-calc, and an MCP client session.

FLO2_CALC_SERVER, when set, is the command line to start instead of the
installed `flo2-calc` (CI's image job sets it to a `docker run` of the image,
confined as flo2's sandbox confines a helper), so the image answers the same
questions as the package.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def installed_command() -> str:
    """The console script beside this interpreter, so the tests run the
    package under test even when its venv is not on PATH."""
    beside = Path(sys.executable).parent / "flo2-calc"
    if beside.exists():
        return str(beside)
    found = shutil.which("flo2-calc")
    if found is None:
        pytest.fail("the flo2-calc command is not installed: pip install '.[test]' first")
    return found


def server_command(*extra: str) -> list[str]:
    override = shlex.split(os.environ.get("FLO2_CALC_SERVER", ""))
    return [*(override or [installed_command()]), *extra]


def under_image() -> bool:
    return bool(os.environ.get("FLO2_CALC_SERVER"))


@asynccontextmanager
async def session(*extra: str, env: dict[str, str] | None = None, cwd: str | None = None) -> AsyncIterator[ClientSession]:
    command = server_command(*extra)
    params = StdioServerParameters(command=command[0], args=command[1:], env=env, cwd=cwd)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        yield s


def text_of(result: Any) -> str:
    return "".join(getattr(b, "text", "") for b in result.content if getattr(b, "type", None) == "text")


def answer_of(result: Any) -> dict[str, Any]:
    """A reply's JSON answer; fails if the call was an error."""
    assert not result.is_error, text_of(result)
    return json.loads(result.content[0].text)


def reason_of(result: Any) -> str:
    """A failing call's reason, as flo2's door reads it: the SDK's
    'Error executing tool <name>: ' preamble taken off (model-door.ts)."""
    assert result.is_error, text_of(result)
    said = text_of(result)
    import re

    return re.sub(r"^Error executing tool [A-Za-z0-9_]+(?::\s*|\s*$)", "", said).strip()


def graph(*nodes: dict[str, Any], result: str | None = None) -> dict[str, Any]:
    g: dict[str, Any] = {"nodes": list(nodes)}
    if result is not None:
        g["result"] = result
    return g


def inp(id: str, value: Any, source: Any = "test") -> dict[str, Any]:
    n: dict[str, Any] = {"id": id, "value": value}
    if source is not None:
        n["source"] = source
    return n


def op(id: str, name: str, *args: str, **extra: Any) -> dict[str, Any]:
    return {"id": id, "op": name, "args": list(args), **extra}
