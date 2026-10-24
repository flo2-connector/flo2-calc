"""A reply carries its outcome whole and fits the host's answer budget (flo2-calc 0.11.0).

dec:a-reply-carries-its-outcome-whole-and-fits-a-host-set-answer-budget in design 0bee0c00b35845f6, Anthony's
ruling of 2026-10-24 on fact:root-cause-a-calc-reply-is-sized-by-the-graph-not-by-the-reader-2026-10-24.

WHAT FAILED. In the Shop sample trial (2026-10-24, flo2.io, flo2-calc 0.10.0) five record_computation replies came
to 36,041 to 215,186 characters. A chat reads about 30,000, so flo2's door withheld each one whole, the result
with it, and the chat read its own results by searching the kept files. Each reply carried every node's value, a
second copy of what the record it returned already held. Its formula and working views were capped by line
count, never by size, and its only reply limit was the 2 MiB runaway guard sized for the record. The rocket
equation trial (2026-10-23, 38,342 characters) had met the same thing.

THE RULE, pinned here as a class rather than as those three graphs:
  - every reply carries its OUTCOME whole: the status or the refusal, the result(s) with their labels, the
    exactness, the record's facts, `next`;
  - everything else (the formula and working views, other nodes' values) fills what the host's answer budget
    leaves, and a `withheld` block names what was left out and where it is;
  - record_computation never repeats the values its record holds;
  - a result too large on its own is shown by its shape, its sha256 and its first and last elements, and the
    record holds it whole;
  - the sentences saying how a float64 bound was found are said once per reply, not once per value;
  - the record's format does not change (schema version 10).

The five graphs in tests/data/answer-budget/ are the trial's own, anonymized for a public repository: Phase B's
three distance checks (placement, row-edge, well-and-septic) and Phase C's two largest, its winter heat and its
electricity, which were withheld on evaluate_graph as well. Every source is replaced, an id that named a person is
renamed, and each latitude and longitude is moved by a fixed offset. Their shape, their node count and the size of
what they answer are unchanged: 263, 98, 168, 234 and 100 nodes, about 263,000, 98,000, 67,000, 44,000 and 36,000
characters a reply at flo2-calc 0.10.0.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import jsonschema
import pytest
from conftest import answer_of, graph, inp, op, session, text_of, under_image

from flo2_calc import limits as L
from flo2_calc import record as R

DATA = Path(__file__).parent / "data" / "answer-budget"
FIXTURES = ("placement", "row-edge", "well-and-septic", "winter-heat", "electricity")

# flo2.io's answer budget (its image's FLO2_CALC_MAX_ANSWER_CHARS), and its other limits as the image sets them.
FLO2_IO_ANSWER_CHARS = 24_000
FLO2_IO_ENV = {
    "FLO2_CALC_DEADLINE": "20", "FLO2_CALC_MAX_DIGITS": "2000", "FLO2_CALC_MAX_REPLY_BYTES": "2097152",
    "FLO2_CALC_MAX_ARRAY_BYTES": "16777216", "FLO2_CALC_MAX_EXACT_ELEMENTS": "4096",
    "FLO2_CALC_MAX_ARRANGEMENTS": "1000000", "FLO2_CALC_MAX_SHAPLEY_FACTORS": "12",
    "FLO2_CALC_MAX_PRIME_DIGITS": "200", "FLO2_CALC_MAX_FACTOR_DIGITS": "40",
    "FLO2_CALC_MAX_ANSWER_CHARS": str(FLO2_IO_ANSWER_CHARS),
}


def fixture(name: str) -> dict:
    return json.loads((DATA / f"{name}.graph.json").read_text(encoding="utf-8"))


async def _calls(steps, env):
    out = []
    async with session(env=None if under_image() else env) as s:
        for tool, args in steps:
            out.append(await s.call_tool(tool, args))
    return out


def calls(steps, env=FLO2_IO_ENV):
    """Run (tool, arguments) steps in one session under flo2.io's limits (the image's own, under the image)."""
    return anyio.run(_calls, steps, env)


def resolved(answer: dict) -> dict:
    """The answer with every float64 label's `how` read back from the sentences said once."""
    said = answer.get("how_bounds_were_found")

    def back(v):
        if isinstance(v, dict):
            out = {k: back(x) for k, x in v.items()}
            f = out.get("float64")
            if isinstance(f, dict) and said is not None and all(isinstance(i, int) for i in f.get("how", [])):
                out["float64"] = {**f, "how": [said[i] for i in f["how"]]}
            return out
        if isinstance(v, list):
            return [back(x) for x in v]
        return v

    return back(answer)


# ---------------------------------------------------------------- the setting


def test_the_answer_budget_is_a_host_set_limit_with_flo2_ios_value_in_its_profile():
    assert L.SETTINGS["max_answer_chars"] == ("--max-answer-chars", "FLO2_CALC_MAX_ANSWER_CHARS")
    assert L.LAPTOP.max_answer_chars == 30_000, "reflow2's reply budget, the one chat clients are known to take"
    assert L.FLO2_IO.max_answer_chars == FLO2_IO_ANSWER_CHARS
    assert L.from_settings(None, None, None, max_answer_chars="12000").max_answer_chars == 12_000
    with pytest.raises(ValueError) as caught:
        L.from_settings(None, None, None, max_answer_chars="100")
    assert "--max-answer-chars (or FLO2_CALC_MAX_ANSWER_CHARS)" in str(caught.value)
    # It is the host's, never the record's: a not-yet-computed record's limits_in_force is schema 10's, unchanged.
    assert "max_answer_chars" not in L.FLO2_IO.describe()


# ---------------------------------------------------------------- the trial's three graphs


@pytest.mark.parametrize("name", FIXTURES)
def test_the_trials_graphs_are_answered_within_the_budget_with_their_results_whole(name):
    g = fixture(name)
    evaluated, made = calls([
        ("evaluate_graph", {"graph": g}),
        ("record_computation", {"graph": g, "name": f"fixture-{name}", "supports": "a test"}),
    ])
    for r in (evaluated, made):
        assert len(text_of(r)) <= FLO2_IO_ANSWER_CHARS, f"{name}: {len(text_of(r)):,} characters"
        assert answer_of(r)["status"] == "ok"
    record = json.loads(made.content[1].resource.text)
    a = resolved(answer_of(made))
    # The outcome, whole: every result with its label, as the record holds it, and the record's facts.
    assert a["results"] == record["results"], "every result, whole, with its label"
    assert a["record"]["content_hash"] == record["content_hash"] and a["record"]["file"] == f"fixture-{name}.calc.json"
    assert a["exactness"] and a["next"]
    assert resolved(answer_of(evaluated))["results"] == record["results"]


@pytest.mark.parametrize("name", FIXTURES)
def test_record_computation_never_repeats_the_values_its_record_holds(name):
    (made,) = calls([("record_computation", {"graph": fixture(name), "name": f"fixture-{name}", "supports": "a test"})])
    a = answer_of(made)
    assert "values" not in a
    held = a["withheld"]["values"]
    assert held["left_out"] == len(fixture(name)["nodes"]) and "record" in held["where"]


def test_what_a_reply_leaves_out_is_named_and_counted():
    g = fixture("placement")
    (r,) = calls([("evaluate_graph", {"graph": g})])
    a = answer_of(r)
    held = a["withheld"]
    assert held["budget_chars"] == FLO2_IO_ANSWER_CHARS
    shown = len(a.get("values") or [])
    assert shown + held["values"]["left_out"] == len(g["nodes"]), "every value is shown or counted as left out"
    assert held["values"]["where"], "and the reply says where the rest is"


@pytest.mark.parametrize("name", FIXTURES)
def test_a_kept_record_re_runs_within_the_budget(name):
    (made,) = calls([("record_computation", {"graph": fixture(name), "name": f"fixture-{name}", "supports": "a test"})])
    (again,) = calls([("rerun_record", {"record": made.content[1].resource.text})])
    assert len(text_of(again)) <= FLO2_IO_ANSWER_CHARS, f"{name}: {len(text_of(again)):,} characters"
    a = answer_of(again)
    assert a["reproduces"] is True
    assert resolved(a)["results"] == json.loads(made.content[1].resource.text)["results"]


def test_how_a_bound_was_found_is_said_once_and_reads_back_whole():
    (r,) = calls([("evaluate_graph", {"graph": fixture("placement")})])
    a = answer_of(r)
    said = a["how_bounds_were_found"]
    assert len(said) == len(set(said)), "each sentence once"
    labels = [v["float64"] for v in a["results"] if "float64" in v]
    assert labels and all(all(isinstance(i, int) and 0 <= i < len(said) for i in f["how"]) for f in labels)


def test_the_record_format_is_unchanged():
    (made,) = calls([("record_computation", {"graph": fixture("row-edge"), "name": "fixture-row-edge", "supports": "a test"})])
    record = json.loads(made.content[1].resource.text)
    assert record["schema_version"] == 10
    jsonschema.Draft202012Validator(R.schema()).validate(record)
    assert all("float64" not in v or all(isinstance(h, str) for h in v["float64"]["how"]) for v in record["values"]), (
        "the record says every sentence in full, as schema 10 does"
    )


# ---------------------------------------------------------------- a result too large on its own


BIG = 600
TOO_LARGE = graph(
    inp("x", {"array": [f"{i}.000000000{i:03d}" for i in range(BIG)], "unit": "mm"}, "a long series"),
    inp("k", "3"),
    op("y", "mul", "x", "k"),
    result="y",
)


@pytest.mark.skipif(under_image(), reason="the image's own budget is flo2.io's; this sets a smaller one")
def test_a_result_too_large_on_its_own_is_shown_by_its_shape_sha256_and_first_and_last_elements():
    env = {**FLO2_IO_ENV, "FLO2_CALC_MAX_ANSWER_CHARS": "4000"}
    made, evaluated = calls([
        ("record_computation", {"graph": TOO_LARGE, "name": "long-series", "supports": "a test"}),
        ("evaluate_graph", {"graph": TOO_LARGE}),
    ], env)
    record = json.loads(made.content[1].resource.text)
    whole = record["result"]["array"]
    assert len(whole["values"]) == BIG, "the record holds it whole"
    for r in (made, evaluated):
        assert len(text_of(r)) <= 4000, f"{len(text_of(r)):,} characters"
        a = answer_of(r)
        shown = a["result"]["array"]
        assert shown["shape"] == [BIG] and shown["sha256"] == whole["sha256"] and shown["unit"] == "mm"
        assert "values" not in shown
        assert shown["first"] == whole["values"][: len(shown["first"])] and shown["first"]
        assert shown["last"] == whole["values"][-len(shown["last"]):] and shown["last"]
        assert a["withheld"]["results"][0]["node"] == "y"
    assert "record" in answer_of(made)["withheld"]["results"][0]["where"]
