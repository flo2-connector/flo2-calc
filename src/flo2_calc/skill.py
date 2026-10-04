"""The skill an agent USING flo2-calc reads, served over MCP itself.

dec:round-2-fixes, fix 7. skills/support-a-decision-with-math/SKILL.md at the
repository's root is the ONE copy: the plugin formats read it there, and the
wheel carries that same file as flo2_calc/skills/ (pyproject.toml maps the
folder in). The server offers it two ways, so that a client that starts
flo2-calc as a plain command, with no plugin, still gets its rules (when to
route a domain formula elsewhere, never typing a constant, never changing a
prefix, never deciding what a rounded value cannot):

  - an MCP PROMPT named support-a-decision-with-math: the skill's body, with
    its front matter's description as the prompt's description;
  - an MCP RESOURCE, RESOURCE_URI, text/markdown: the file as it is.

Nothing here copies its text: both are read from the file.
"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources
from pathlib import Path

NAME = "support-a-decision-with-math"
RESOURCE_URI = f"skill://flo2-calc/{NAME}/SKILL.md"
MIME_TYPE = "text/markdown"


def _candidates() -> list[Path]:
    packaged = resources.files("flo2_calc").joinpath("skills", NAME, "SKILL.md")  # an installed wheel
    source = Path(__file__).resolve().parents[2] / "skills" / NAME / "SKILL.md"  # a checkout, or an editable install
    return [Path(str(packaged)), source]


@cache
def text() -> str:
    """The skill's file, exactly."""
    for path in _candidates():
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"the served skill {NAME}/SKILL.md is not installed with flo2-calc")


def front_matter() -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text(), re.S)
    return dict(re.findall(r"^([a-z]+): (.+)$", m.group(1), re.M)) if m else {}


def body() -> str:
    """The skill without its front matter: the prompt's text."""
    m = re.match(r"^---\n.*?\n---\n", text(), re.S)
    return text()[m.end():].lstrip("\n") if m else text()
