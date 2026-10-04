"""tools/dependency_currency.py, judged on fake registry data: no network.

Ported from flo2-ifc's test of the same check, less its git (fork) pin.

Each test builds a small repository in a temporary folder (a pyproject.toml,
a workflow, the two Agent Plugins manifests, and sometimes a hold) and a fake
upstream that answers PyPI and GitHub lookups from a dict.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import textwrap
import tomllib
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import dependency_currency as dc  # noqa: E402

TODAY = dt.date(2026, 10, 4)


def make_repo(tmp: Path, deps: list[str], *, holds: str = "", schema: str = "1.0.0",
              uses: tuple[str, ...] = ("actions/checkout@v7", "actions/setup-python@v7"),
              build: str = "setuptools==84.0.0", test: tuple[str, ...] = ("pytest==9.1.1",)) -> Path:
    listed = ",\n".join(f"  {json.dumps(d)}" for d in deps)
    (tmp / "pyproject.toml").write_text(textwrap.dedent(f"""\
        [build-system]
        requires = [{json.dumps(build)}]

        [project]
        name = "x"
        version = "0.1.0"
        dependencies = [
        {listed}
        ]

        [project.optional-dependencies]
        test = [{", ".join(json.dumps(t) for t in test)}]
        """))
    wf = tmp / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("jobs:\n  t:\n    steps:\n" + "".join(f"      - uses: {u}\n" for u in uses))
    for name in ("plugin", "mcp"):
        (tmp / f"{name}.json").write_text(json.dumps(
            {"$schema": f"https://agent-plugins.org/schemas/{schema}/{name}.schema.json"}))
    (tmp / dc.HOLDS).write_text(holds)
    return tmp


class Fake:
    """PyPI and GitHub, answered from dicts. A missing name raises, as a failed lookup does."""

    def __init__(self, pypi: dict | None = None, github: dict | None = None):
        self.pypi_data = {"mcp": "2.3.0", "pint": "0.26.1", "jsonschema": "4.26.0", "setuptools": "84.0.0",
                          "pytest": "9.1.1", **(pypi or {})}
        self.github_data = {"actions/checkout": (7, 0, 1), "actions/setup-python": (7, 0, 0),
                            dc.SPEC_REPO: (1, 0, 0), **(github or {})}

    def upstream(self) -> dc.Upstream:
        return dc.Upstream(pypi=self.pypi, github_latest=self.github_latest)

    def pypi(self, name):
        return {"version": self.pypi_data[name]}

    def github_latest(self, slug):
        return self.github_data[slug]


def rows(report: dict) -> dict[tuple[str, str], dict]:
    return {(r["kind"], r["name"]): r for r in report["rows"]}


def run(tmp: Path, deps: list[str], fake: Fake | None = None, **kw) -> dict:
    return dc.check(make_repo(tmp, deps, **kw), (fake or Fake()).upstream(), TODAY)


BASE = ["mcp==2.3.0", "pint==0.26.1", "jsonschema==4.26.0"]


def test_everything_current_passes(tmp_path):
    report = run(tmp_path, BASE)
    assert report["failing"] == 0, report
    r = rows(report)
    for key in [("package", "mcp"), ("package", "pint"), ("package", "jsonschema"), ("package", "setuptools"),
                ("package", "pytest"), ("action", "actions/checkout"), ("action", "actions/setup-python"),
                ("schema", "agent-plugins")]:
        assert r[key]["state"] == "current", r[key]


def test_patch_and_minor_releases_are_reported_not_failed(tmp_path):
    report = run(tmp_path, BASE, Fake(pypi={"mcp": "2.3.1", "jsonschema": "4.27.0", "pint": "0.26.2"}))
    assert report["failing"] == 0, report
    r = rows(report)
    assert r[("package", "mcp")]["state"] == "patch_owed"
    assert r[("package", "jsonschema")]["state"] == "minor_owed"
    assert r[("package", "pint")]["state"] == "patch_owed"
    assert r[("package", "jsonschema")]["latest"] == "4.27.0"


def test_a_new_major_with_no_hold_fails(tmp_path):
    report = run(tmp_path, BASE, Fake(pypi={"mcp": "3.0.0"}))
    assert report["failing"] == 1
    assert rows(report)[("package", "mcp")]["state"] == "series_owed"


def test_a_new_0x_minor_is_a_new_series_and_fails(tmp_path):
    report = run(tmp_path, BASE, Fake(pypi={"pint": "0.27.0"}))
    assert rows(report)[("package", "pint")]["state"] == "series_owed"
    assert report["failing"] == 1


HOLD = """
[[hold]]
kind = "package"
name = "mcp"
reason = "3.0 renames MCPServer again; flo2-calc moves once its tests pass on it."
look_again = {date}
"""


def test_a_hold_with_a_reason_and_a_future_date_holds(tmp_path):
    report = run(tmp_path, BASE, Fake(pypi={"mcp": "3.0.0"}), holds=HOLD.format(date="2026-11-01"))
    assert report["failing"] == 0
    row = rows(report)[("package", "mcp")]
    assert row["state"] == "held"
    assert "until 2026-11-01" in row["note"]


def test_a_hold_past_its_look_again_date_fails(tmp_path):
    report = run(tmp_path, BASE, Fake(pypi={"mcp": "3.0.0"}), holds=HOLD.format(date="2026-10-01"))
    assert rows(report)[("package", "mcp")]["state"] == "hold_expired"
    assert report["failing"] == 1


def test_a_hold_with_no_reason_fails(tmp_path):
    holds = '[[hold]]\nkind = "package"\nname = "mcp"\nlook_again = 2026-12-01\n'
    report = run(tmp_path, BASE, Fake(pypi={"mcp": "3.0.0"}), holds=holds)
    assert rows(report)[("package", "mcp")]["state"] == "hold_invalid"
    assert report["failing"] == 1


def test_a_hold_with_no_look_again_date_fails(tmp_path):
    holds = '[[hold]]\nkind = "package"\nname = "mcp"\nreason = "because"\n'
    report = run(tmp_path, BASE, Fake(pypi={"mcp": "3.0.0"}), holds=holds)
    assert rows(report)[("package", "mcp")]["state"] == "hold_invalid"


def test_a_hold_on_something_current_is_reported_as_unneeded(tmp_path):
    report = run(tmp_path, BASE, holds=HOLD.format(date="2026-11-01"))
    assert report["failing"] == 0
    assert rows(report)[("package", "mcp")]["state"] == "hold_unneeded"


def test_a_lookup_that_fails_fails_the_run(tmp_path):
    fake = Fake()
    del fake.pypi_data["jsonschema"]
    report = run(tmp_path, BASE, fake)
    row = rows(report)[("package", "jsonschema")]
    assert row["state"] == "unknown"
    assert "PyPI lookup failed" in row["note"]
    assert report["failing"] == 1


def test_a_range_is_not_a_pin_and_fails(tmp_path):
    report = run(tmp_path, [*BASE[:-1], "jsonschema>=4.26"])
    assert rows(report)[("package", "jsonschema")]["state"] == "unpinned"
    assert report["failing"] == 1


def test_the_build_backend_and_test_extra_are_checked_too(tmp_path):
    report = run(tmp_path, BASE, Fake(pypi={"setuptools": "85.0.0", "pytest": "9.2.0"}))
    r = rows(report)
    assert r[("package", "setuptools")]["state"] == "series_owed"
    assert r[("package", "pytest")]["state"] == "minor_owed"


# ---- a git pin


def test_a_git_pin_is_not_read_and_fails(tmp_path):
    report = run(tmp_path, [*BASE, "thing @ git+https://github.com/o/r@0123456789012345678901234567890123456789"])
    assert rows(report)[("package", "thing")]["state"] == "unpinned"
    assert report["failing"] == 1


# ---- actions and the Agent Plugins schema --------------------------------------


def test_an_action_a_major_behind_fails(tmp_path):
    report = run(tmp_path, BASE, uses=("actions/checkout@v6", "actions/setup-python@v7"))
    row = rows(report)[("action", "actions/checkout")]
    assert row["state"] == "series_owed"
    assert row["latest"] == "7.0.1"


def test_an_action_on_a_branch_is_reported(tmp_path):
    report = run(tmp_path, BASE, uses=("actions/checkout@main", "actions/setup-python@v7"))
    assert rows(report)[("action", "actions/checkout")]["state"] == "branch_ref"
    assert report["failing"] == 0


def test_a_newer_schema_minor_is_reported_and_a_major_fails(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    minor = run(tmp_path / "a", BASE, Fake(github={dc.SPEC_REPO: (1, 1, 0)}))
    assert rows(minor)[("schema", "agent-plugins")]["state"] == "minor_owed"
    assert minor["failing"] == 0
    major = run(tmp_path / "b", BASE, Fake(github={dc.SPEC_REPO: (2, 0, 0)}))
    assert rows(major)[("schema", "agent-plugins")]["state"] == "series_owed"
    assert major["failing"] == 1


def test_manifests_on_different_schema_versions_fail(tmp_path):
    repo = make_repo(tmp_path, BASE)
    (repo / "mcp.json").write_text(json.dumps({"$schema": "https://agent-plugins.org/schemas/1.1.0/mcp.schema.json"}))
    report = dc.check(repo, Fake(github={dc.SPEC_REPO: (1, 1, 0)}).upstream(), TODAY)
    assert {r["state"] for r in report["rows"] if r["kind"] == "schema"} == {"unknown"}


# ---- the report, and this repository's own files -------------------------------


def test_main_writes_a_dated_report_to_stdout_the_step_summary_and_json(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, BASE)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    code = dc.main(["--today", "2026-10-03", "--json", str(tmp_path / "r.json")], Fake().upstream(), repo)
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("## flo2-calc dependency currency, 2026-10-03")
    assert "**OK**" in out
    assert summary.read_text() == out
    assert json.loads((tmp_path / "r.json").read_text())["date"] == "2026-10-03"


def test_main_exits_non_zero_when_anything_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    repo = make_repo(tmp_path, BASE)
    assert dc.main(["--today", "2026-10-03"], Fake(pypi={"mcp": "3.0.0"}).upstream(), repo) == 1
    assert "**FAILED**" in capsys.readouterr().out


def test_this_repository_pins_every_dependency_exactly():
    pins = dc.declared_pins(REPO)
    assert pins, "pyproject.toml lists dependencies"
    for pin in pins:
        assert not pin.unreadable, pin
        assert pin.url is None, f"{pin.raw}: flo2-calc pins PyPI releases only"
        assert pin.exact is not None, f"{pin.raw} in {pin.where} is not pinned exactly"


def test_this_repository_passes_against_upstream_at_its_own_pins():
    """Every file the real check reads parses, and nothing fails when upstream's
    latest is exactly what is pinned."""
    pins = dc.declared_pins(REPO)
    pypi = {p.name: f"{p.exact[0]}.{p.exact[1]}.{p.exact[2]}" for p in pins if p.exact}
    github = {slug: (int(sorted(use["refs"])[0].lstrip("v")), 0, 0)
              for slug, use in dc.declared_actions(REPO).items()}
    fake = Fake(pypi=pypi, github=github)
    report = dc.check(REPO, fake.upstream(), TODAY)
    assert report["failing"] == 0, dc.markdown(report)
    holds = tomllib.loads((REPO / dc.HOLDS).read_text())
    assert holds.get("hold", []) == [], "dependency-holds.toml starts empty"
