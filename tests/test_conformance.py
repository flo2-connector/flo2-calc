"""flo2's helper contract, asked the way flo2 asks it.

Modelled on flo2's services/edge-gateway/test/child-conformance.test.ts and
docs/child-mcp-contract.md (version 1), the MUST tier for any helper. flo2's
plug speaks raw JSON-RPC over the helper's stdio, one message per line, so
this test does too, with no MCP client library in between:

  1. --version answers, and says what the server is;
  2. initialize answers the revision flo2 asks for (2025-11-25), offers tools,
     and names the server;
  3. tools/list is exactly the four lower_snake_case tools, each with an input
     schema and a read-only hint matching its class (flo2's door classes each
     tool read or write, and holds the two to each other);
  4. one call that answers;
  5. one failing call whose reason reaches the caller (isError, and more than
     the SDK's bare "Error executing tool <name>");
  and nothing reaches stdout but JSON-RPC messages.

ver:mcp-conformance in design 0bee0c00b35845f6. CI's image job runs this same
file against the image, confined as flo2's sandbox confines a helper
(FLO2_CALC_SERVER).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile

import pytest
from conftest import server_command

from flo2_calc import __version__
from flo2_calc.server import READ_ONLY, TOOLS

FLO2_REVISION = "2025-11-25"  # TOOL_SERVER_PROTOCOL_VERSION in flo2's tool-servers.ts


class Plug:
    """One helper process, spoken to as flo2's plug speaks to it."""

    def __init__(self) -> None:
        self.stderr = tempfile.TemporaryFile(mode="w+")
        self.proc = subprocess.Popen(
            server_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1
        )
        self.next_id = 0
        self.lines: list[str] = []

    def send(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        while True:
            assert self.proc.stdout is not None
            line = self.proc.stdout.readline()
            assert line, f"the server closed stdout; stderr: {self.said()}"
            self.lines.append(line)
            reply = json.loads(line)  # anything on stdout that is not JSON-RPC fails here
            if reply.get("id") == msg["id"]:
                return reply

    def said(self) -> str:
        self.stderr.seek(0)
        return self.stderr.read()

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.stderr.close()


@pytest.fixture(scope="module")
def plug():
    p = Plug()
    hello = p.send("initialize", {"protocolVersion": FLO2_REVISION, "capabilities": {}, "clientInfo": {"name": "flo2-conformance", "version": "1"}})
    p.send("notifications/initialized", notify=True)
    p.hello = hello  # type: ignore[attr-defined]
    yield p
    p.close()


def test_version_answers_and_names_the_server():
    out = subprocess.run([*server_command(), "--version"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"flo2-calc {__version__}"


def test_initialize_answers_flo2s_revision_offers_tools_and_names_itself(plug):
    result = plug.hello["result"]
    assert result["protocolVersion"] == FLO2_REVISION
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "flo2-calc"
    assert result["serverInfo"]["version"] == __version__
    assert "flo2-calc" in result.get("instructions", "")


def test_tools_list_is_exactly_the_four_tools_each_classed(plug):
    tools = plug.send("tools/list", {})["result"]["tools"]
    names = [t["name"] for t in tools]
    assert sorted(names) == sorted(TOOLS)
    for t in tools:
        assert re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", t["name"]), f"{t['name']} is lower_snake_case"
        assert isinstance(t.get("inputSchema"), dict) and t["inputSchema"].get("type") == "object", t["name"]
        assert t.get("description"), t["name"]
        assert t["annotations"]["readOnlyHint"] is READ_ONLY[t["name"]], f"{t['name']}'s read/write class"


def test_one_call_that_answers(plug):
    reply = plug.send("tools/call", {"name": "evaluate_graph", "arguments": {"graph": {"nodes": [
        {"id": "a", "value": "0.1"}, {"id": "b", "value": "0.2"}, {"id": "s", "op": "add", "args": ["a", "b"]}]}}})
    result = reply["result"]
    assert result.get("isError") in (None, False)
    answer = json.loads(result["content"][0]["text"])
    assert answer["result"] == {"node": "s", "value": "0.3"}


def test_a_file_comes_back_inside_the_reply_as_flo2_keeps_it(plug):
    reply = plug.send("tools/call", {"name": "record_computation", "arguments": {"name": "conformance", "graph": {"nodes": [
        {"id": "a", "value": "2 mm", "source": "test"}]}}})
    blocks = reply["result"]["content"]
    assert [b["type"] for b in blocks] == ["text", "resource"]
    res = blocks[1]["resource"]
    assert re.fullmatch(r"calcfile:///[A-Za-z0-9._-]{1,128}", res["uri"])  # flo2's file-name rule
    assert res["mimeType"] == "application/json"
    assert json.loads(res["text"])["record_format"] == "flo2-calc computation record"


def test_one_failing_call_whose_reason_reaches_the_caller(plug):
    reply = plug.send("tools/call", {"name": "evaluate_graph", "arguments": {"graph": {"nodes": [{"id": "a", "value": "2 furlong"}]}}})
    result = reply["result"]
    assert result["isError"] is True
    said = " ".join(b.get("text", "") for b in result["content"])
    told = re.sub(r"^Error executing tool [A-Za-z0-9_]+(?::\s*|\s*$)", "", said).strip()  # as flo2's door reads it
    assert told, "a reason, not a bare preamble"
    assert re.search(r"graph\.nodes\[0\]\.value: \"furlong\" is not a unit", told), told


def test_nothing_but_json_rpc_reaches_stdout(plug):
    assert plug.lines, "the session said something"
    for line in plug.lines:
        assert json.loads(line).get("jsonrpc") == "2.0"
