"""The plugin, in both formats, is valid and names one server the same way;
and the served skill is a well-formed Agent Skill.

- Agent Plugins: plugin.json and mcp.json at the root, validated against the
  1.0.0 schemas vendored in tests/schemas/ (see tests/schemas/SOURCE.txt).
- Claude Code: .claude-plugin/plugin.json and .mcp.json, which carry no
  `type` and no `$schema`, the way flo2-cad's and flo2-ifc's do.
- Both start flo2-calc with --root ".", the folder the agent works in, so a
  record can be saved beside the work it supports (README, "Saving records").
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parent.parent
SCHEMAS = Path(__file__).resolve().parent / "schemas"
SERVER = "flo2-calc"
COMMAND = "uvx"
ARGS = ["--from", "git+https://github.com/flo2-connector/flo2-calc", "flo2-calc", "--root", "."]
SKILL = REPO / "skills" / "support-a-decision-with-math" / "SKILL.md"


def load(rel: str) -> dict:
    return json.loads((REPO / rel).read_text())


@pytest.mark.parametrize("manifest, schema", [("plugin.json", "plugin.schema.json"), ("mcp.json", "mcp.schema.json")])
def test_agent_plugins_manifest_is_valid(manifest, schema):
    schema_doc = json.loads((SCHEMAS / schema).read_text())
    doc = load(manifest)
    assert doc["$schema"] == schema_doc["$id"], "the manifest declares the schema version vendored here"
    jsonschema.Draft202012Validator.check_schema(schema_doc)
    jsonschema.Draft202012Validator(schema_doc).validate(doc)


def test_both_formats_name_the_same_server_command_and_args():
    agent = load("mcp.json")["mcpServers"]
    claude = load(".mcp.json")["mcpServers"]
    assert list(agent) == [SERVER]
    assert list(claude) == [SERVER]
    assert agent[SERVER]["type"] == "stdio"
    for servers in (agent, claude):
        assert servers[SERVER]["command"] == COMMAND
        assert servers[SERVER]["args"] == ARGS


def test_claude_format_carries_no_type_or_schema():
    claude = load(".mcp.json")
    assert "$schema" not in claude
    assert "type" not in claude["mcpServers"][SERVER]
    assert "$schema" not in load(".claude-plugin/plugin.json")


def test_both_plugin_manifests_say_the_same_thing():
    agent = load("plugin.json")
    claude = load(".claude-plugin/plugin.json")
    agent.pop("$schema")
    assert agent == claude
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    from flo2_calc import __version__

    assert agent["name"] == project["name"]
    assert agent["version"] == project["version"] == __version__
    assert agent["author"] == {"name": "Anthony Sligar"}
    assert agent["homepage"] == agent["repository"] == "https://github.com/flo2-connector/flo2-calc"
    assert agent["license"] == project["license"] == "Apache-2.0"
    assert (REPO / "LICENSE").read_text().lstrip().startswith("Apache License\n")


def test_the_uvx_entry_point_is_the_console_script():
    scripts = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts[ARGS[2]] == "flo2_calc:main"


def test_the_skill_is_a_well_formed_agent_skill():
    text = SKILL.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "the skill starts with YAML front matter"
    fields = dict(re.findall(r"^([a-z]+): (.+)$", m.group(1), re.M))
    assert fields["name"] == SKILL.parent.name, "an Agent Skill's name is its folder's name"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"]) and len(fields["name"]) <= 64
    assert 1 <= len(fields["description"]) <= 1024
    for tool in ("evaluate_graph", "add_node", "record_computation", "rerun_record"):
        assert tool in text, f"the skill teaches {tool}"
    body = text[m.end():]
    assert body.index("Standalone") < body.index("On flo2.io"), "standalone use first, hosted use second"


def test_the_readme_puts_standalone_use_before_hosted_use():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert readme.index("## Standalone") < readme.index("## Hosted on flo2.io")
