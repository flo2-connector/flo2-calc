# Changelog

flo2-calc's changes, newest first. Versions before 0.12.0 are described in the README, where each feature names the
version that added it, and in the commit history.

## 0.15.0 (2026-10-27)

A clamp keeps its one-sided bound, a function over an exact array stays exact where every element is, and an
intermediate array no longer crowds a reply. Three findings of 2026-10-27 in design `0bee0c00b35845f6`, each measured on
0.14.0: `fact:a-clamp-at-zero-on-a-float64-array-keeps-a-two-sided-error-so-sqrt-refuses-the-edge-2026-10-27` (a
defect), `fact:an-array-function-is-float64-where-the-same-scalar-is-exact-2026-10-27` and
`fact:a-reply-fills-its-budget-with-intermediate-values-in-graph-order-so-one-array-crowds-out-the-rest-2026-10-27`.

What a caller sees:

- **`sqrt(max(x, 0))` answers at the edge.** `max`, `min` and `abs` (element-wise, the greatest and least of an
  array, and on a single rounded value) are now the interval their arguments' bounds give, written from the end the
  operation guarantees: `max(x, 0)` is never below 0 and `min(x, 0)` never above it, bound included. Until now
  `max(raw, 0 mm^2)` at an element where `raw` was 0 within 3.4e-16 came back `0.0` within 3.4e-16, and `sqrt` refused
  it as undecidable. That element now reads about `1.7e-16` within `1.7e-16` (it is in [0, 3.3e-16]), and its root
  about `9.1e-9` within `9.1e-9` (its true value 0 inside). Where the argument picked holds both ends (it is surely
  the larger), its value and its own bound come back unchanged, which can be tighter than before (0.14.0 gave every
  element the widest argument's bound). `sqrt(max(sin(pi rad), 0))` and `sqrt(abs(sin(pi rad)))` answer too.
- **A function over an exact array is exact where every element has an exact value.** `sqrt([1/4, 9/4])` now comes
  back exact `[1/2, 3/2]` (it was float64 `["0.5", "1.5"]` with bound 0), and `cos([0, 90] deg)` exact `[1, 0]` (it
  was float64, `2.29e-24` within `4.9e-24` for the second): the same cases a single value is exact in, for `sqrt`,
  `exp`, `ln`, `log10`, the trigonometry and its inverses, `atan2`, a non-whole `pow`, deg-rad, the decibel
  conversions, `normal_cdf`, `normal_sf`, `normal_quantile` and `chi2_sf`. Such a result has no `float64` label, and
  what follows from it stays exact too. If any element has no exact value, or the array is past the host's
  `max_exact_elements`, the whole array is float64 as before. A domain is still refused element by element. The
  attempt costs at most about 0.1 s at flo2.io's 4,096 elements (every element exact but the last; measured below).
- **An intermediate array is summarized in a reply.** In `values`, an array of more than 16 elements that is not a
  result is shown by its `shape`, `sha256` (the record's digest of every element) and its `first` and `last` three
  elements; its element list is the only field dropped. `withheld.values_summarized` names each one (`nodes`) and
  says where every element is (`where`: the record `record_computation` keeps, or an `element` node for one). A
  0.14.0 reply to a graph with a 1,023-element `integer_range` spent 7,272 characters on it and withheld the six
  values after it; it now shows all ten values in 11,102 characters. A result is never summarized, and the record
  still holds every value.
- **Record schema version 13**: version 12's shape, made under the two rules above, which can change the values a
  graph gives. A record of version 12 or older re-runs under the rules it was made with
  (`tests/data/array-rules.v12.calc.json`, made by 0.14.0 with every path they change, reproduces byte for byte).
  `rederive_record` of such a record compares old and new values both computed under today's rules and says so in
  `compared`, so `moved` names only what the change moved. Every new record is version 13.
- The served `references/arrays.md` and the server's instructions say all three; SKILL.md is unchanged.
- For flo2: no tool, class, argument or limit changes, so the door's allow-list and the image's profile are unchanged;
  copy `references/arrays.md` again.
- Measured (`tools/measure.py`, which gains the 4,096-element exact-function step): 61 calls, peak 108.6 MiB under
  the 128 MiB cap (0.14.0: 100.6; runs differ by a few MiB), every runaway call stopped with its limit, the container
  alive after. The step takes 1.71 s on the image's one CPU, recorded and re-run 4.30 s; the exact attempt itself
  adds at most about 0.09 s at 4,096 elements against flo2.io's 20 s deadline.

## 0.14.0 (2026-10-27)

A kept record is re-derived when an input changes, and says what moved. (`req:a-calc-record-keeps-its-formula-and-is-re-derived-when-an-input-changes`,
accepted by Anthony on 2026-10-27, under `dec:calc-keeps-live-formulas-and-solves-for-a-variable-proved-on-a-test-case-first`
and `dec:solving-ships-as-a-separate-helper-image-so-calc-stays-lean-and-exact`.)

- A new tool, `rederive_record` (classed write): give a kept record and new values for one or more of its inputs,
  each `{"input", "value", "source"}`. It evaluates the record's own graph with them, under the same exact or
  bounded arithmetic, and returns the new record (same name, `calcfile:///<name>.calc.json`) and what moved: each
  result old -> new or unchanged, and every other node whose value changed. The wall heat loss case:
  `A` 1,200 -> 1,350 ft^2 moves `Q` 84000/19 -> 94500/19 Btu/h, exactly.
- A new value must measure what the input it replaces measured (any unit of that kind: `"3 m"` for `"9 ft"`);
  otherwise it is refused naming what arrived. A name that is not one of the record's inputs is a malformed call
  that lists them. A record changed after it was made, one that does not re-run here, one of schema version 1 to 6
  (made under the rules before `delta_K`), or a changed graph that does not answer gives no new record, with the
  reason.
- Record schema version 12 adds `history`: one entry per re-derivation, naming the record it came from by its
  content hash, each input changed and each result moved or unchanged. Versions 1 to 11 still re-run, and their
  schemas are unchanged; `tests/data/wall-heat-loss.v11.calc.json` was made by 0.13.0. Every new record is written
  as version 12. `rerun_record` re-runs a re-derived record to the same content.
- A reply fills the host's answer budget with the other nodes that moved before the formula and working views
  (`answer.fit`'s `fill` order).
- No new dependency (the proof of concept of 2026-10-27 found live formulas need no symbolic algebra). Formula text is
  not accepted: a record's graph is already its formula. Solving for a variable is a separate helper, later.
- The skill gains step 12 (when an input changes, re-derive; never edit a record), with its detail in
  `references/records.md`; one units sentence moved from SKILL.md to `references/units.md` to keep SKILL.md under
  15,000 bytes. The server's instructions name the new tool.
- For flo2: the door's allow-list gains `rederive_record` (write); README, "What flo2 needs to host it".

## 0.13.0 (2026-10-25)

An input names the design quantity it holds the value of; a copied value reads as unbound. (reflow2's
`req:a-changed-quantity-names-every-kept-computation-that-used-it`, option (c) of
`dec:idea-reflow2-becomes-the-web-of-rules-for-a-buildings-ifc-model`, accepted by Anthony on 2026-10-24.)

- The case: the Shop sample's household changed from four to five. The food calc's input `persons` cited the
  requirement as `{"design_node": ...}` but held its own copy of "4", so nothing could say the record was owed a
  re-run (reflow2's `fact:root-cause-a-changed-requirement-does-not-flow-because-the-accepted-web-of-rules-was-never-built-2026-10-25`).
- An input's `source` may now be `{"design_quantity": "<id>"}`, with `"design"` for another design: the value it
  holds is that design quantity's. The record keeps the id. Like a design node, it is recorded and never resolved
  (`req:sister-mcp`).
- Copying a value with no design quantity stays legal. `record_computation`'s reply now carries `inputs_bound`:
  each bound input with its design quantity and the value it holds, and the unbound inputs by id. A design that
  keeps the record can name each bound input as one of the record's inputs, so a change to the quantity marks the
  record owed.
- Only an input's value can be a design quantity's. A unit's source (`with_unit`) naming one is refused, and so is
  a source naming both a design node and a design quantity.
- Record schema version 11 allows the new source. Versions 1 to 10 still re-run, and their schemas are unchanged.
  Every new record is written as version 11.

## 0.12.0 (2026-10-24)

A reply shows a readable decimal beside each exact array result; the kept record stays exact.
(`dec:a-reply-shows-a-readable-decimal-beside-an-exact-array-result`, design `0bee0c00b35845f6`, Anthony's ruling
of 2026-10-24.)

- An exact array writes an element whose decimal does not end as its fraction. The Shop sample trial's monthly net
  energy came back as twelve of them, the first `-4869729231506843861/1575262621733750` kWh.
- Beside each exact array result with such an element, every reply (all four tools) now shows `readable`: the
  elements the reply shows, each fraction rounded half-even to 6 significant digits and each decimal as written. A
  `rendering` label says it is a rendering. That first month now also reads `-3091.38`.
- It mirrors what is shown of the array: every value with a grid's rows kept; or its first, least and greatest; or,
  cut to fit, its first and last.
- It fits the host's answer budget. When the outcome alone is over the budget, a rendering goes before any exact
  value is cut, and `withheld.results` names it. It comes back beside the ends of a result cut to them.
- The record is unchanged. It holds the exact values only, in record schema version 10. The four tools, their
  classes and their arguments are unchanged.
- No new value carries a rendering where its text is already a decimal: a single exact value (already written
  rounded with its `exact` fraction), a rounded value, a float64 array, or an exact array whose elements all end.
