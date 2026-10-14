---
name: support-a-decision-with-math
description: Do the math behind a design decision with flo2-calc instead of in your head, and keep it with the decision. Use when a decision, a trade or a limit rests on a number or a yes/no that has to be computed - a margin, a fit, a budget, a run time, a unit conversion, a comparison with a limit, a root, a logarithm, a gain in dB, an angle, a p-value or a percentile (normal, lognormal, gamma, beta), a count or a binomial probability, an estimate updated from a published prior, an on/off trial's randomization test, Shapley credit among factors, an empirical formula whose formula and constants the person or a cited document gave, or a computation over data or a grid (a mean, a standard deviation, a fitted slope, an FFT) - especially one with units. It covers composing the computation, units, arrays, rounded and float64 results, where an empirical formula's constants must come from (never your memory), refusals, the working shown back, the computation record, saving it, linking it to the decision, and checking it later.
compatibility: Needs the flo2-calc MCP server (evaluate_graph, add_node, record_computation, rerun_record), which also serves this skill as the MCP prompt support-a-decision-with-math and the resource skill://flo2-calc/support-a-decision-with-math/SKILL.md. Nothing else has to be running. Linking a record to a design uses the design tool's own tools (reflow2), when there is one.
---

# Support a decision with math

A decision that rests on a number should carry the computation that produced it, so the person and later agents can
open it and check it. flo2-calc does that computation exactly, with units, and hands back a record of it. Do the
arithmetic there, not in your head: a model's arithmetic is a guess that looks like an answer.

"Exactly" means **exact for these inputs**: every value follows exactly from the inputs as you wrote them, and is no
more accurate than they are. If you type 3.14159265 for pi, flo2-calc takes that decimal as the number, so the
result is exact for your decimal, not for pi. Say so when you quote it.

## When to use it

Use flo2-calc when a decision, a trade or a limit turns on something computed: a margin or a fit, a budget or a run
time, a comparison against a limit, a conversion a reader will rely on, a yes/no built from several conditions, a
root, a logarithm, an angle or a statistic, data or a grid, a count or a vote, or a person's own data against what is
known. An example of each: `references/when-to-use.md`.

You reason; flo2-calc calculates. Choosing which equation applies, whether an approximation holds, or which events
to combine is yours (and the person's). flo2-calc does the calculation it is given and never decides that for you.

Do not use it for a domain's own formulas, such as metal weight from volume, ring sizes, a building's areas, or an
electronics standard's sizing rule (a PCB trace's width for a current). The helper that owns the domain computes
those (flo2-cad, flo2-ifc), and you bring its number into flo2-calc as an input, with that helper as its source.

### An empirical formula's constants come from the person or a document, never from your memory

An empirical relation or a standard's formula (a datasheet's curve fit, a code's coefficient, a standard's sizing
rule) is only as good as its constants, and flo2-calc cannot tell where a number came from. So:

- **Compute one only when the formula and every constant in it were given**: by the person, in the question, or in a
  document you can name with its edition and clause. Each constant is an input whose `source` says where it was
  given: `"given by the person"`, `"given in the question"`, or the document, edition and clause.
- **When a result under a named formula or standard is asked for without them, do not recall them**, even when you
  are sure you know them. Ask the person for the formula and its constants (with their units), or name the document
  and edition you would take them from and have the person confirm them before you calculate. Or send it to the helper
  that owns that domain.
- A recalled constant that happens to be right is still the failure: the next one recalled wrong would be computed
  just as confidently, and recorded as if it were checked.

## Standalone (a plugin, or a server on this machine)

1. **Write the computation as a graph.** Each node has an `id`.
   - An input has a `value` and a `source`: `{"id": "bend", "value": "1.4 mm", "source": "fiber datasheet"}`.
   - An operation has an `op` and its `args`: `{"id": "margin", "op": "sub", "args": ["cavity", "bend"]}`.
   - When an input is one of the design's own quantities, make its source the node that holds it:
     `"source": {"design_node": "con:cavity-depth"}`. That is how a later change to that quantity can be traced to
     this computation. Otherwise say where the number came from in a few words: a datasheet, a measurement, or
     "assumed".
2. **Write every number as text with its unit**, spelled as the design spells units: `"1.4 mm"`, `"3.3 V"`,
   `"20 mA"`, `"12 g"`. Write a plain number as text too (`"0.1"`, `"1/3"`), because a JSON `0.1` is refused: it
   arrives as a binary float.
   - A value is **one** number. Never type arithmetic inside it (`"3 + 4"`, `"2^10"`): make each operation a node.
   - Temperatures, money, gallons, troy weight and decibels are spelled as `references/units.md` says.
3. **Evaluate it** with `evaluate_graph` (the whole graph in one call) or `add_node` (one node at a time, when you
   want to see each value as you go; pass back the `graph` it returns). The result is the same either way. What a
   reply holds: `references/operators.md`.
   - When the answer has several parts, name them all: `"result": ["margin", "fits"]`.
   - **Read the `formula` and the `working` it shows back, and check they are the computation you meant.** Your
     translation of the problem into a graph is the weak point, and this is where you catch a wrong one.
4. **Use the built-in operators for anything that is not exact; never type a constant or a result in.** Each
   family's arguments, examples and edge cases: `references/operators.md`.
   - **Constants, roots, logarithms, powers:** `pi`, `e`, `sqrt`, `exp`, `ln`, `log10`, `pow`. Do not type pi to
     30 digits as an input.
   - **Trigonometry:** `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`. **Rounding:** `ceil`, `floor`, `round`.
   - **Distributions:** normal, chi-square, Student-t, lognormal, gamma, beta. Which distribution a population
     follows, and its parameters, come from the person or the publication that fits it: say which, as the inputs'
     sources.
   - **Decibels:** `db_to_ratio`, `ratio_to_db`, each with `"kind"` power or amplitude. You must say which; flo2-calc
     never picks one. Never type a dB value as a plain number, and never type the 10 or 20 of a decibel formula
     yourself.
   - **Counting:** `count_true`, `k_of_n`, `to_number`. Never add true/false values, and never tally them yourself.
   - **Combinatorics and the binomial:** `choose`, `factorial`, `binomial_pmf`, `_cdf`, `_sf`. Whether the trials
     are independent with one p is your judgement; say so.
   - **An empirical formula's units:** `magnitude`, `with_unit`. Never multiply by a typed `"1 mm^2"` to get a unit
     back, and never fill in a constant the person did not give.
5. **Give data as an array, not as one node per number:** `{"array": [...], "unit": "..."}`, one unit for the
   whole array. Every operator works element by element; reductions, the straight-line fit, the FFT, grids, data
   files and the `"float64"` label are in `references/arrays.md`.
   - `length` counts an array's elements (`"axis"` for a grid's columns or rows). Use it for n, never a typed count:
     `sqrt(n)` and degrees of freedom then rest on the data, not on your counting.
   - Statistics over data are named, with no default: `variance_sample` or `variance_population`, `sd_sample` or
     `sd_population`. Choose the one the question means (n - 1 for a sample, n for a whole population).
6. **Update an estimate, test a trial, share credit: say what only you and the person know.** flo2-calc never
   defaults any of it. Arguments and examples: `references/operators.md`.
   - **Bayesian updating** (`posterior_normal_*`, `posterior_beta_*`). Every input the prior rests on needs a
     `source` naming that population (the study, survey or reference range, and its year or edition); flo2-calc
     refuses a prior without one. Whether that population is a fair prior for this person, and whether the readings
     are independent with that sd, is your judgement with the person: say it.
   - **A randomization test** (`randomization_test`). Ask how the on periods were chosen, and give its `"scheme"`,
     `"statistic"` and `"alternative"`. If the on periods were not chosen at random, a randomization test does not
     apply: say so instead of computing one.
   - **Shapley values** (`shapley_values`). If a combination was never tried, flo2-calc refuses, naming it: ask the
     person for its outcome; never estimate it yourself.
7. **Read a refusal and fix the cause; never work around it.**
   - A `"status": "refused"` reply names the node, the operation and why. For example, `add cannot combine mm and g`
     means the computation is wrong, not the calculator. Tell the person what did not add up.
   - A "Malformed call" error names the field to fix: an unknown unit, a missing node, a cycle.
   - An expression typed as a value is refused. If it is called **malformed** (`"3 + * 4"`), do not repair it or guess
     what it meant: ask the person what was intended, then build that as nodes.
   - If it is called **ambiguous** (`"6/2(1+2)"`, an implied multiplication), the refusal gives both readings. Never
     pick one: ask which was meant, or build each reading as nodes and give both values, saying which is which.
   - An unknown unit that pint reads (`"mile"`) is named for what it is, with the units of that kind flo2-calc knows.
     Nothing is substituted: give the value in one of those units, from a source that states it, never a conversion
     factor you recall.
   - A near-miss unit may say what to write instead (`khz` gives `Write "kHz"`). When flo2-calc gives no hint, write
     the unit you mean yourself. Never change its prefix to get past the refusal.
   - `"kind": "undecidable"` means a rounded value's error bound straddles the answer: `sqrt(2) * sqrt(2) = 2` cannot be
     told. Ask for more `digits`, or compute it another way (compare the exact squares instead). Never decide it
     yourself.
   - `out_of_domain`, `undefined`: `references/operators.md`; `shape_mismatch`: `references/arrays.md`.
8. **Make the record** with `record_computation` once the computation is right. Give it a `name` such as
   `fiber-bend-margin`, and `supports`: the decision it backs, as `{"design_node": "dec:..."}` or in words. It
   returns the result and the record as a file: `calcfile:///<name>.calc.json` (saving it to disk:
   `references/records.md`).
9. **Link the record to the decision, and quote the result there.** In a reflow2 design, register the file as an
   Artifact that documents the decision, with its sha256 as the checksum, and put the result into the decision's
   text: "margin 0.6 mm, needed 0.5 mm: fits (fiber-bend-margin.calc.json)". flo2-calc never writes to the design.
   Linking is your step, done with the design tool's own tools.
10. **Check it later** with `rerun_record`. Pass the record itself, or its `path` when it was saved.
   - `reproduces: true` means the record is intact and its graph still gives every value it holds.
   - `reproduces: "within_bound"` (an FFT re-run on another processor): `references/records.md`.
   - Anything else names each difference. Say so before relying on the number.
11. **When a calculation passes the host's limits**, the reply is `"status": "refused"` with
   `"kind": "exceeds_limits"`. It is the machine's limit, not a fault in the math. Never shrink the inputs, round
   them or split the computation to slip under it.
   - From `record_computation` the record still comes back, marked `"status": "not_computed"`. Keep it and link it
     to the decision as you would any record. Tell the person the number is not computed yet, and what it needs (the
     reply's `next` says). Completing it on a flo2-calc with more room: `references/records.md`.

## On flo2.io (a helper beside the person's design)

When flo2-calc is reached through flo2's `use_helper_tool`, the steps are the same, with three differences:

- There is no folder to write in, so leave `output_path` out. flo2 keeps the record that `record_computation` returns
  as a file in the person's design, every version, and hands you its name and a link. Give the person the link.
- Link that kept file to the decision with the design tools (`use_design_tool`), as in step 9.
- To re-check a record, pass its content to `rerun_record`.
- flo2.io's limits are lower than a laptop's (`references/records.md`). Arrays come inline there: no data files. A
  calculation past them comes back as a not-yet-computed record, kept in the design like any other. The person, or
  an agent on their machine, completes it there with the standalone flo2-calc (step 11). Then link the completed
  record to the decision in its place.

## Talking about it

Say what was computed in the person's terms: "the fiber needs 1.4 mm to bend, the cavity gives 2 mm, so there is
0.6 mm to spare against the 0.5 mm you wanted". Do not say "graph" or "node" to them.

- An exact value whose decimal does not end is written rounded with its exact fraction beside it (`"exact": "40/9 h"`):
  the exact value for these inputs. Quote the rounded text to the person; the record keeps the exact one. Never call a
  result exact beyond its inputs: a result from a measured value is exact for that value, and no more accurate than it
  is. Use the `pi` and `e` operators rather than typing their digits.
- A value labelled `"rounded"` is not exact, and the reply's `exactness` says so. Say so too, with its precision: "the
  standard deviation is 0.2302 mm (rounded; correct to 30 digits)". Quote no more digits than the person needs, and
  never call it exact. Every digit it was asked for is written, trailing zeros included.
- A value labelled `"float64"` was computed in double precision. Say so with its bound: "the peak of the spectrum is
  16.0 V (float64, within 3e-13 V)". Quote no more digits than its bound supports.

## Where the details live

Each `references/` file named above is in this skill's folder: read one when a step points to it. flo2-calc also
serves each as an MCP resource, `skill://flo2-calc/support-a-decision-with-math/references/<file>`.
