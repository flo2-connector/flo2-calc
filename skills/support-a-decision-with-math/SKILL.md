---
name: support-a-decision-with-math
description: Do the math behind a design decision with flo2-calc instead of in your head, and keep it with the decision. Use when a decision, a trade or a limit rests on a number or a yes/no that has to be computed - a margin, a fit, a budget, a run time, a unit conversion, a comparison against a limit, a root, a logarithm, a gain in dB or a power in dBm, an angle, a p-value or a critical value, a count of true conditions or a k-of-n vote, an empirical formula with stated units - especially one with units. It covers composing the computation, units, rounded results, refusals, checking the formula and working it shows back, making the computation record, saving it, linking it to the decision, and checking it later.
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

Use flo2-calc when a decision, a trade or a limit turns on something computed:

- **a margin or a fit:** does the fiber's bend radius fit the cavity, with 0.5 mm to spare?
- **a budget or a run time:** how many hours does a 2400 mAh cell give at 180 mA?
- **a comparison against a limit:** is the part's mass under the 12 g budget?
- **a conversion** a reader will rely on: 0.25 in in mm;
- **a yes/no built from several conditions:** it fits AND it lasts the night AND it is under budget;
- **a root, a logarithm, an angle or a statistic:** a standard deviation, a loss in dB, a great-circle angle, a normal
  tail probability, a chi-square p-value, a Student-t critical value;
- **a count or a vote:** how many of eight conditions hold, whether two of three sensors agree.

You reason; flo2-calc calculates. Choosing which equation applies, whether an approximation holds, or which events
to combine is yours (and the person's). flo2-calc does the calculation it is given and never decides that for you.

Do not use it for a domain's own formulas, such as metal weight from volume, ring sizes, or a building's areas. The
helper that owns the domain computes those (flo2-cad, flo2-ifc), and you bring its number into flo2-calc as an input,
with that helper as its source.

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
   - **Temperatures:** `"25 degC"`, `"77 degF"` or `"298.15 K"`. A change of temperature is `"5 delta_degC"`, or a
     degree inside a compound unit (`"2.5 degC/W"`). Never write a bare `C` or `F`: flo2-calc refuses them, because
     they could be coulombs or farads. Write `coulomb` or `farad` when you mean those.
   - **Money:** the ISO 4217 code, `"987.50 USD"`. flo2-calc holds no exchange rates, so it refuses to add USD to
     EUR. To convert, give the rate as an input with its date and source,
     `{"id": "rate", "value": "0.92 EUR/USD", "source": "ECB reference rate, 2026-10-02"}`, and multiply by it.
   - **Gallons:** `gal_us` or `gal_imp`. A bare `gal` is refused, because it is two different units.
   - **Decibels:** a gain or loss is `"6 dB"` (`"0.2 dB/m"` per length); a power level is `"-30 dBm"` or `"10 dBW"`.
     Never type a dB value as a plain number, and never type the 10 or 20 of a decibel formula yourself (step 4).
3. **Evaluate it.**
   - `evaluate_graph` takes the whole graph in one call. It returns the result and every node's value.
   - `add_node` builds the graph one node at a time, when you want to see each value as you go. Pass back the
     `graph` it returns. The result is the same either way.
   - When the answer has several parts (a verdict and its margin, an interval's two ends, a count and its rows),
     name them all: `"result": ["margin", "fits"]`. They come back by name, as `results`.
   - **Read the `formula` and the `working` it shows back, and check they are the computation you meant.** The formula
     is the equation (`t = C / I = 450/13 h`); the working is every step, numbered, with its value and label. Your
     translation of the problem into a graph is the weak point, and this is where you catch a wrong one. Both come in
     plain text and in LaTeX.
4. **Use the built-in operators for anything that is not exact; never type a constant or a result in.**
   - `{"id": "pi", "op": "pi"}` and `{"id": "e", "op": "e"}` are the constants. Do not type pi to 30 digits as an input.
   - `sqrt`, `exp`, `ln`, `log10`, and `pow` with a non-whole exponent (`"1/3"`, `"0.44"`).
   - `sin`, `cos`, `tan` take an angle WITH its unit (`"37.5 deg"`). `asin`, `acos`, `atan`, `atan2` need
     `"unit": "deg"` or `"rad"` for the angle they give. `convert` turns deg into rad.
   - `normal_cdf`, `normal_sf` (the upper tail), `normal_quantile`, `chi2_sf` (a p-value), `t_quantile` (a critical
     value). The normal ones take `[x]`, or `[x, mean, sd]` in one unit.
   - `ceil`, `floor`, `round` (with `"places"`; `round`'s `"mode"` is `half_even` unless you say otherwise).
   - **dB to a ratio and back:** `db_to_ratio` and `ratio_to_db`, each with `"kind": "power"` (10 log10) or
     `"amplitude"` (20 log10). You must say which; flo2-calc never picks one. A power level converts with `convert`:
     `"10 dBm"` to `"mW"`, or a power in `mW` to `"dBm"`. A level plus a gain in dB is a level; two levels never add.
   - **Counting:** `count_true` counts the true values; `k_of_n` with args `[k, b1, b2, ...]` is true when at least k
     are. Never add true/false values, and never tally them yourself.
   - **An empirical formula with stated units** (IPC-2221, a datasheet's fit): take each input's number in the unit
     the formula states with `magnitude` (`{"op": "magnitude", "args": ["I"], "unit": "A"}`), compute on the plain
     numbers, then put the stated unit on the result with `with_unit` and say where it comes from:
     `{"op": "with_unit", "args": ["A"], "unit": "mil^2", "source": "IPC-2221: A in mil^2"}`. Never multiply by a typed
     `"1 mil^2"` to get a unit back.
   - Their results come back labelled `"rounded"`: correctly rounded to 30 significant digits (ask for more with
     `"digits"`, up to 1000), with `error_at_most`, and never with an `exact` fraction. Anything computed from a rounded
     value is labelled rounded too, with its bound. Where the result is rational it stays exact (`sqrt(9/4)` is `1.5`).
5. **Read a refusal and fix the cause; never work around it.**
   - A `"status": "refused"` reply names the node, the operation and why. For example, `add cannot combine mm and g`
     means the computation is wrong, not the calculator. Tell the person what did not add up.
   - A "Malformed call" error names the field to fix: an unknown unit, a missing node, a cycle.
   - An expression typed as a value is refused. If it is called **malformed** (`"3 + * 4"`), do not repair it or guess
     what it meant: ask the person what was intended, then build that as nodes.
   - A near-miss unit may say what to write instead (`khz` gives `Write "kHz"`). Units are case-sensitive, and a
     prefix's case is its size: `mJ` is a millijoule and `MJ` a megajoule. When flo2-calc gives no hint, write the
     unit you mean yourself. Never change its prefix to get past the refusal.
   - `"kind": "undecidable"` means a rounded value's error bound straddles the answer: `sqrt(2) * sqrt(2) = 2` cannot be
     told. Ask for more `digits`, or compute it another way (compare the exact squares instead). Never decide it
     yourself.
   - `"kind": "out_of_domain"` or `"undefined"`: the argument is outside what the function takes (`sqrt(-1)`, a
     probability of 1, `tan(90 deg)`). The computation, not the calculator, needs fixing.
6. **Make the record** with `record_computation` once the computation is right. Give it a `name` such as
   `fiber-bend-margin`, and `supports`: the decision it backs, as `{"design_node": "dec:..."}` or in words.
   - It returns the result and the record as a file: `calcfile:///<name>.calc.json`.
   - To save the record beside the work, add `output_path` (for example `decisions/fiber-bend-margin.calc.json`). The
     path is inside the folder flo2-calc was started in. It never writes outside that folder, and never over a
     different file.
7. **Link the record to the decision, and quote the result there.** In a reflow2 design, register the file as an
   Artifact that documents the decision, with its sha256 as the checksum, and put the result into the decision's
   text: "margin 0.6 mm, needed 0.5 mm: fits (fiber-bend-margin.calc.json)". flo2-calc never writes to the design.
   Linking is your step, done with the design tool's own tools.
8. **Check it later** with `rerun_record`. Pass the record itself, or its `path` when it was saved.
   - `reproduces: true` means the record is intact and its graph still gives every value it holds.
   - Anything else names each difference. Say so before relying on the number.
9. **When a calculation passes the host's limits**, the reply is `"status": "refused"` with
   `"kind": "exceeds_limits"`.
   - The refusal names the limit (a deadline, `max_digits` or `max_reply_bytes`), its value, the node reached and how
     large the numbers grew. It is the machine's limit, not a fault in the math. Never shrink the inputs, round them
     or split the computation to slip under it.
   - From `record_computation` the record still comes back, marked `"status": "not_computed"`. It holds the graph,
     the inputs with their sources and the limit it passed, but no result. Keep it and link it to the decision as you
     would any record. Tell the person the number is not computed yet, and what it needs (the reply's `next` says).
   - To complete it, pass it as `record` to `record_computation` on a flo2-calc with more room, such as one started
     with a higher `--max-digits` or `--deadline`. The completed record has the same name, graph and inputs, now
     with the result. It is exactly the record a direct computation would give. Link it in place of the
     not-yet-computed one.
   - `rerun_record` on a not-yet-computed record says it has no result yet, and whether this flo2-calc has the room to
     complete it.

## On flo2.io (a helper beside the person's design)

When flo2-calc is reached through flo2's `use_helper_tool`, the steps are the same, with three differences:

- There is no folder to write in, so leave `output_path` out. flo2 keeps the record that `record_computation` returns
  as a file in the person's design, every version, and hands you its name and a link. Give the person the link.
- Link that kept file to the decision with the design tools (`use_design_tool`), as in step 6.
- To re-check a record, pass its content to `rerun_record`.
- flo2.io's limits are lower than a laptop's: 20 s a call, 2,000 digits, 2 MiB a reply. A calculation past them
  comes back as a not-yet-computed record, kept in the design like any other. The person, or an agent on their
  machine, completes it there with the standalone flo2-calc (step 9). Then link the completed record to the decision
  in its place.

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
- A computed value may come back in a simpler unit than it was computed in (`mAh/mA` shown as `h`); `simplified_from`
  says so. The value is the same. A whole number is written in full.
- Show the person the formula when it helps them check the reasoning: "run time t = C / I = 450 mAh / 13 mA, about
  34.6 h". The LaTeX form renders where their client renders math.
