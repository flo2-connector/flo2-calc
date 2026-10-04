---
name: support-a-decision-with-math
description: Do the math behind a design decision with flo2-calc instead of in your head, and keep it with the decision. Use when a decision, a trade or a limit rests on a number or a yes/no that has to be computed - a margin, a fit, a budget, a run time, a unit conversion, a comparison against a limit - especially one with units. It covers composing the computation, units, refusals, making the computation record, saving it, linking it to the decision, and checking it later.
compatibility: Needs the flo2-calc MCP server (evaluate_graph, add_node, record_computation, rerun_record). Nothing else has to be running. Linking a record to a design uses the design tool's own tools (reflow2), when there is one.
---

# Support a decision with math

A decision that rests on a number should carry the computation that produced it, so the person and later agents can
open it and check it. flo2-calc does that computation exactly, with units, and hands back a record of it. Do the
arithmetic there, not in your head: a model's arithmetic is a guess that looks like an answer.

## When to use it

Use flo2-calc when a decision, a trade or a limit turns on something computed:

- **a margin or a fit:** does the fiber's bend radius fit the cavity, with 0.5 mm to spare?
- **a budget or a run time:** how many hours does a 2400 mAh cell give at 180 mA?
- **a comparison against a limit:** is the part's mass under the 12 g budget?
- **a conversion** a reader will rely on: 0.25 in in mm;
- **a yes/no built from several conditions:** it fits AND it lasts the night AND it is under budget.

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
3. **Evaluate it.**
   - `evaluate_graph` takes the whole graph in one call. It returns the result and every node's value.
   - `add_node` builds the graph one node at a time, when you want to see each value as you go. Pass back the
     `graph` it returns. The result is the same either way.
4. **Read a refusal and fix the cause; never work around it.**
   - A `"status": "refused"` reply names the node, the operation and why. For example, `add cannot combine mm and g`
     means the computation is wrong, not the calculator. Tell the person what did not add up.
   - A "Malformed call" error names the field to fix: an unknown unit, a missing node, a cycle.
   - A near-miss unit says what to write instead (`MM` gives "write mm").
5. **Make the record** with `record_computation` once the computation is right. Give it a `name` such as
   `fiber-bend-margin`, and `supports`: the decision it backs, as `{"design_node": "dec:..."}` or in words.
   - It returns the result and the record as a file: `calcfile:///<name>.calc.json`.
   - To save the record beside the work, add `output_path` (for example `decisions/fiber-bend-margin.calc.json`). The
     path is inside the folder flo2-calc was started in. It never writes outside that folder, and never over a
     different file.
6. **Link the record to the decision, and quote the result there.** In a reflow2 design, register the file as an
   Artifact that documents the decision, with its sha256 as the checksum, and put the result into the decision's
   text: "margin 0.6 mm, needed 0.5 mm: fits (fiber-bend-margin.calc.json)". flo2-calc never writes to the design.
   Linking is your step, done with the design tool's own tools.
7. **Check it later** with `rerun_record`. Pass the record itself, or its `path` when it was saved.
   - `reproduces: true` means the record is intact and its graph still gives every value it holds.
   - Anything else names each difference. Say so before relying on the number.

## On flo2.io (a helper beside the person's design)

When flo2-calc is reached through flo2's `use_helper_tool`, the steps are the same, with three differences:

- There is no folder to write in, so leave `output_path` out. flo2 keeps the record that `record_computation` returns
  as a file in the person's design, every version, and hands you its name and a link. Give the person the link.
- Link that kept file to the decision with the design tools (`use_design_tool`), as in step 6.
- To re-check a record, pass its content to `rerun_record`.

## Talking about it

Say what was computed in the person's terms: "the fiber needs 1.4 mm to bend, the cavity gives 2 mm, so there is
0.6 mm to spare against the 0.5 mm you wanted". Do not say "graph" or "node" to them. When a value is rounded, the
reply also gives its exact fraction. Quote the rounded value to the person, and keep the exact one in the record.
