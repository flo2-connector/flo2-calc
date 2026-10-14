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

ITS REFERENCE FILES (flo2-calc 0.8.1). SKILL.md holds the rules and stays
under 15,000 bytes (tests/test_manifests.py), so that flo2 can serve it whole
in one reply (its budget is 30,000 characters with its own wrapper); each
operator's arguments, examples and edge cases are in references/*.md beside
it, which SKILL.md names and an agent reads only when a step points to one
(the Agent Skills spec's progressive disclosure). Each is served as a resource too, at the same path
under skill://flo2-calc/support-a-decision-with-math/, so a plain-command
client reaches everything a plugin install does.

Nothing here copies their text: each is read from its file.
"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources
from pathlib import Path

NAME = "support-a-decision-with-math"
BASE_URI = f"skill://flo2-calc/{NAME}/"
RESOURCE_URI = f"{BASE_URI}SKILL.md"
MIME_TYPE = "text/markdown"
REFERENCES = "references"


def _candidates() -> list[Path]:
    packaged = resources.files("flo2_calc").joinpath("skills", NAME)  # an installed wheel
    source = Path(__file__).resolve().parents[2] / "skills" / NAME  # a checkout, or an editable install
    return [Path(str(packaged)), source]


@cache
def folder() -> Path:
    """The skill's folder: SKILL.md and its references/."""
    for path in _candidates():
        if (path / "SKILL.md").is_file():
            return path
    raise FileNotFoundError(f"the served skill {NAME}/SKILL.md is not installed with flo2-calc")


@cache
def text() -> str:
    """The skill's file, exactly."""
    return (folder() / "SKILL.md").read_text(encoding="utf-8")


@cache
def references() -> tuple[str, ...]:
    """Each reference file's path in the skill's folder (`references/<name>.md`), in order."""
    found = sorted((folder() / REFERENCES).glob("*.md"))
    return tuple(f"{REFERENCES}/{path.name}" for path in found)


def reference_text(path: str) -> str:
    """A reference file, exactly; `path` is one of references()."""
    if path not in references():
        raise FileNotFoundError(f"{NAME} has no reference file {path}")
    return (folder() / path).read_text(encoding="utf-8")


def front_matter() -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text(), re.S)
    return dict(re.findall(r"^([a-z]+): (.+)$", m.group(1), re.M)) if m else {}


def body() -> str:
    """The skill without its front matter: the prompt's text."""
    m = re.match(r"^---\n.*?\n---\n", text(), re.S)
    return text()[m.end():].lstrip("\n") if m else text()
