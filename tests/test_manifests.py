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


# ---------------------------------------------------------------- an empirical formula's constants (round 3, q077)
#
# ver:an-empirical-formulas-constants-come-from-the-person-or-a-cited-document.
# Held-out q077 asked for an IPC-2221 trace width with no constants given; the
# agent recalled four from memory and computed it, following the skill's
# IPC-2221 example (written from seen q078, where the constants ARE given).
# flo2-calc cannot tell where a number came from, so the guard is what the
# agent is told, in the served skill and in the server's instructions. The rule
# is general, not IPC-2221's.

# The four constants q077's agent recalled, and IPC-2221's internal-layer k.
RECALLED = ("0.048", "0.44", "0.725", "1.378", "0.024")


def _section(text: str, start: str) -> str:
    i = text.index(start)
    j = text.find("\n## ", i + 1)
    k = text.find("\n### ", i + len(start))
    ends = [e for e in (j, k) if e != -1]
    return text[i: min(ends) if ends else len(text)]


def test_the_skill_says_where_an_empirical_formulas_constants_come_from():
    text = SKILL.read_text(encoding="utf-8")
    rule = _section(text, "### An empirical formula's constants come from the person or a document, never from your memory")
    assert "only when the formula and every constant in it were given" in rule
    assert "do not recall them" in rule and "even when" in rule and "sure" in rule
    assert "Ask the person for the formula and its constants" in rule
    assert "name the document" in rule and "edition" in rule and "confirm" in rule
    assert '"given by the person"' in rule and '"given in the question"' in rule, "q078's case still computes"
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert "never your memory" in m.group(1), "the description, which a client reads first, says it too"


def test_the_skills_example_supplies_no_constant_of_any_standard():
    text = SKILL.read_text(encoding="utf-8")
    for c in RECALLED:
        assert c not in text, f"the skill must not carry a standard's constant ({c}) for an agent to copy"
    example = text[text.index("**An empirical formula with stated units**"):]
    example = example[: example.index("**Give data as an array")]
    sources = re.findall(r'"id": "(k|b)", "value": "([^"]*)", "source": "([^"]*)"', example)
    assert {s[0] for s in sources} == {"k", "b"}
    for _id, value, source in sources:
        assert value.startswith("<") and source.startswith("given by the person"), (value, source)
    assert "IPC-2221" not in example, "the example is general, not the one round 2 wrote from q078"


def test_the_instructions_say_it_too_and_list_an_electronics_standard_among_the_domain_formulas():
    from flo2_calc.server import INSTRUCTIONS, build_server
    from flo2_calc import limits as L

    for words in ("NEVER FROM YOUR MEMORY", "COMES FROM THE PERSON OR FROM A DOCUMENT", "ask the person for them",
                  "have the person confirm before you calculate", "never recall them"):
        assert words in INSTRUCTIONS, words
    assert "IPC-2221's trace width" in INSTRUCTIONS and "ring sizes" in INSTRUCTIONS
    assert "NEVER FROM YOUR MEMORY" in build_server(None, L.LAPTOP).instructions


def test_with_unit_names_no_standard_in_its_description_or_its_refusal():
    from flo2_calc.evaluator import OPS

    assert "IPC-2221" not in OPS["with_unit"][3] and "never recalled from memory" in OPS["with_unit"][3]
