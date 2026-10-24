"""A reply held to its reader's budget: the outcome whole, the rest as far as the budget goes, and the rest named.

dec:a-reply-carries-its-outcome-whole-and-fits-a-host-set-answer-budget (design 0bee0c00b35845f6, Anthony's ruling
of 2026-10-24) on fact:root-cause-a-calc-reply-is-sized-by-the-graph-not-by-the-reader-2026-10-24.

WHY. Until 0.11.0 a reply was sized by the graph, not by whoever reads it.
  - It carried every node's value whole. record_computation's reply carried them as a second copy beside the
    record that already holds them.
  - Its formula and working views were capped by line count, not by size.
  - Its only bound was the host's max_reply_bytes, a runaway guard sized so that a record always fits (2 MiB on
    flo2.io).
A chat reads about 30,000 characters. In the Shop sample trial (2026-10-24) five record_computation replies came to
36,041 to 215,186 characters, and flo2's door withheld each one whole, the result with it. Phase C's heat and
electricity graphs were withheld on evaluate_graph too.

THE RULE (`fit`). The answer budget is the host's (limits.max_answer_chars: --max-answer-chars,
FLO2_CALC_MAX_ANSWER_CHARS; 30,000 characters on a laptop, 24,000 in flo2.io's image). It is measured on the text
block exactly as it is sent.
  1. THE OUTCOME COMES WHOLE. That is everything but the formula and working views and the nodes' values: the
     status or the refusal, the result(s) with their labels, `exactness`, the record's facts, `next`, a re-run's
     verdict.
  2. The rest fills what the outcome leaves, in this order: the formula, the working, the values. Each comes whole
     if it fits, else as many entries from its start as fit. A `withheld` block names what was left out of each
     (how many shown, how many left out, the first and last left out) and where it is (`where`).
  3. Only when the outcome alone is over the budget is a result itself cut. A result too large on its own is shown
     by its shape, its sha256 and its first and last elements (`first`, `last`). Its whole is in the record, and
     `withheld.results` names it. The same is done, last of all, to any text longer than LONG_TEXT inside a result
     (an exact fraction of thousands of digits).
  4. HOW A FLOAT64 BOUND WAS FOUND IS SAID ONCE. A float64 label's `how` is a list of sentences, and the same few
     sentences recur on every value that rests on the same steps: 76,132 of one trial reply's 213,408 characters.
     In a reply each `how` is a list of numbers that index `how_bounds_were_found`, which says each sentence once.
     The record still says every sentence in full: its format does not change (schema 10).

record_computation's own answer never repeats the record's `values`. server.py leaves them out and names them in
`withheld`, and this module keeps that entry.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

FILL = ("formula", "working", "values")  # what fills what the outcome leaves, in this order
RESULT_KEYS = ("result", "results", "added")  # the outcome's values: cut only when the outcome alone is over
HOW = "how_bounds_were_found"
WITHHELD = "withheld"
SHOWN_ELEMENTS = 3  # a result too large on its own: its first and last this many elements
LONG_TEXT = 400  # a text inside a result longer than this is cut last, with its length and sha256


def text(answer: dict[str, Any]) -> str:
    """The text block, as server._text sends it."""
    return json.dumps(answer, ensure_ascii=False, indent=1)


def say_how_once(answer: dict[str, Any]) -> dict[str, Any]:
    """`answer` with every float64 label's `how` sentences said once, in `how_bounds_were_found`, and each label's
    `how` the list of their places there. Sentences already said once (a list of numbers) are read back first, so
    this can be applied again after a cut and says only the sentences that are still used."""
    said = answer.get(HOW)
    plain = _how_read_back(answer, said) if isinstance(said, list) else answer
    plain = {k: v for k, v in plain.items() if k != HOW}
    index: dict[str, int] = {}

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            out = {k: walk(x) for k, x in v.items()}
            f = out.get("float64")
            if isinstance(f, dict) and isinstance(f.get("how"), list) and all(isinstance(h, str) for h in f["how"]):
                out["float64"] = {**f, "how": [index.setdefault(h, len(index)) for h in f["how"]]}
            return out
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    out = walk(plain)
    if index:
        out[HOW] = list(index)
    return out


def _how_read_back(answer: dict[str, Any], said: list[str]) -> dict[str, Any]:
    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            out = {k: walk(x) for k, x in v.items()}
            f = out.get("float64")
            if isinstance(f, dict) and isinstance(f.get("how"), list) and all(isinstance(h, int) for h in f["how"]):
                out["float64"] = {**f, "how": [said[i] for i in f["how"]]}
            return out
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(answer)


def fit(answer: dict[str, Any], budget: int, where: str) -> dict[str, Any]:
    """`answer` held to `budget` characters of text, by the rule above. `where` says where whatever is left out
    can be read in full (the record this reply returns, the record passed in, or record_computation's)."""
    a = say_how_once(answer)
    if WITHHELD not in a and len(text(a)) <= budget:
        return a
    withheld: dict[str, Any] = {"budget_chars": budget, **(a.get(WITHHELD) or {})}
    parts = {k: a[k] for k in FILL if isinstance(a.get(k), list)}
    order = [k for k in a if k not in (WITHHELD, HOW)]
    outcome = {k: a[k] for k in order if k not in parts}

    def assemble(shown: dict[str, list[Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in order:
            if k in parts:
                if k in shown:
                    out[k] = shown[k]
            else:
                out[k] = outcome[k]
        out[WITHHELD] = withheld
        return say_how_once({**out, HOW: a.get(HOW)} if HOW in a else out)

    for k in parts:  # counted as left out until shown, so what fills first leaves room for naming the rest
        withheld[k] = _left_out(parts[k], 0, where)
    if len(text(assemble({}))) > budget:
        _cut_results(outcome, withheld, where, lambda: len(text(assemble({}))) <= budget)

    shown: dict[str, list[Any]] = {}
    for k in FILL:
        if k not in parts:
            continue
        items = parts[k]
        whole = {**shown, k: items}
        held = withheld.pop(k)
        if len(text(assemble(whole))) <= budget:
            shown[k] = items
            continue
        withheld[k] = held
        lo, hi = 0, len(items)  # the most entries from its start that fit: lo fits, hi + 1 does not
        while lo < hi:
            mid = (lo + hi + 1) // 2
            withheld[k] = _left_out(items, mid, where)
            if len(text(assemble({**shown, k: items[:mid]}))) <= budget:
                lo = mid
            else:
                hi = mid - 1
        withheld[k] = _left_out(items, lo, where)
        if lo:
            shown[k] = items[:lo]
    out = assemble(shown)
    # A later part's entry can name a longer first node than the one counted while an earlier part filled: give
    # back an entry at a time from the last part shown in part, until the whole fits.
    while len(text(out)) > budget:
        trimmed = [k for k in FILL if k in shown and isinstance(withheld.get(k), dict)]
        if not trimmed:
            break
        k = trimmed[-1]
        shown[k] = shown[k][:-1]
        withheld[k] = _left_out(parts[k], len(shown[k]), where)
        if not shown[k]:
            del shown[k]
        out = assemble(shown)
    if len(text(out)) > budget:  # only the outcome is left, and it is still over: cut it further
        _cut_results(outcome, withheld, where, lambda: len(text(assemble(shown))) <= budget)
        out = assemble(shown)
    return out


def _left_out(items: list[Any], shown: int, where: str) -> dict[str, Any]:
    rest = items[shown:]
    out: dict[str, Any] = {"shown": shown, "left_out": len(rest)}
    names = [i.get("node") for i in rest if isinstance(i, dict) and isinstance(i.get("node"), str)]
    if names:
        out["first_left_out"], out["last_left_out"] = names[0], names[-1]
    out["where"] = where
    return out


def _cut_results(outcome: dict[str, Any], withheld: dict[str, Any], where: str, fits: Any) -> None:
    """Cut the outcome's results, largest first, until `fits()`: an array to its shape, sha256, first and last
    elements; then, last of all, a very long text to its ends, its length and its sha256."""
    values: list[dict[str, Any]] = []
    for key in RESULT_KEYS:
        v = outcome.get(key)
        if isinstance(v, dict):
            values.append(v)
        elif isinstance(v, list):
            values += [x for x in v if isinstance(x, dict)]
    cut: list[dict[str, Any]] = []

    def note(entry: dict[str, Any]) -> None:
        cut.append(entry)
        withheld["results"] = cut  # counted in what fits from the first cut on

    by_size = sorted(values, key=lambda v: -len(json.dumps(v, ensure_ascii=False)))
    for v in by_size:
        if fits():
            break
        arr = v.get("array")
        if isinstance(arr, dict) and isinstance(arr.get("values"), list) and len(arr["values"]) > 2 * SHOWN_ELEMENTS:
            elements = arr["values"]
            v["array"] = {
                **{k: x for k, x in arr.items() if k != "values"},
                "first": elements[:SHOWN_ELEMENTS],
                "last": elements[-SHOWN_ELEMENTS:],
            }
            note({
                "node": v.get("node"),
                "shown": f"its shape, its sha256 and its first and last {SHOWN_ELEMENTS} of {len(elements):,} elements",
                "where": where,
            })
    for v in by_size:
        if fits():
            break
        long = [k for k, x in v.items() if isinstance(x, str) and len(x) > LONG_TEXT]
        for k in long:
            s = v[k]
            v[k] = f"{s[:40]}...{s[-40:]}"
            note({
                "node": v.get("node"),
                "shown": f"the first and last 40 of the {len(s):,} characters of its {k!r} "
                f"(sha256 {hashlib.sha256(s.encode('utf-8')).hexdigest()})",
                "where": where,
            })
    many = outcome.get("results")
    if not fits() and isinstance(many, list) and len(many) > 1:
        # Last of all, more results than any reply holds: as many from the start as fit, the rest named.
        whole = list(many)
        lo, hi = 0, len(whole)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            outcome["results"] = whole[:mid]
            withheld["results_left_out"] = _left_out(whole, mid, where)
            if fits():
                lo = mid
            else:
                hi = mid - 1
        outcome["results"] = whole[:lo]
        withheld["results_left_out"] = _left_out(whole, lo, where)
