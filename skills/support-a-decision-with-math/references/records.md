# Records: saving, re-checking, and completing one past the limits

A reference file of the skill `support-a-decision-with-math`, for its steps 8, 10 and 11. The rules (make the
record, link it, never slip under a limit) are in `SKILL.md`.

## Saving a record beside the work (step 8)

To save the record beside the work, add `output_path` (for example `decisions/fiber-bend-margin.calc.json`) to
`record_computation`. The path is inside the folder flo2-calc was started in. It never writes outside that folder,
and never over a different file.

## A record re-run on another processor (step 10)

`reproduces: "within_bound"` (`outcome: "reproduced_within_bound"`) means it was re-run on another processor and an
FFT's values (and what was computed from them) moved in their last bits, each within the bound the record states;
everything else reproduced byte for byte. The number stands; say it was confirmed within its stated bound, not
identically, and quote `largest_difference` if asked.

## A calculation past the host's limits (step 11)

- flo2.io's limits are lower than a laptop's: 20 s a call, 2,000 digits, 2 MiB a reply, 16 MiB of arrays a call (a
  256 x 256 grid's FFT fits), 1,000,000 arrangements in one randomization test and Shapley values of at most 12
  factors.
- The refusal names the limit (a deadline, `max_digits`, `max_reply_bytes`, `max_array_bytes`, `max_arrangements`
  for a randomization test or `max_shapley_factors` for a Shapley table), its value, the node reached and how
  large the numbers grew.
- The not-yet-computed record holds the graph, the inputs with their sources and the limit it passed, but no
  result.
- To complete it, pass it as `record` to `record_computation` on a flo2-calc with more room, such as one started
  with a higher `--max-digits` or `--deadline`. The completed record has the same name, graph and inputs, now
  with the result. It is exactly the record a direct computation would give. Link it in place of the
  not-yet-computed one.
- `rerun_record` on a not-yet-computed record says it has no result yet, and whether this flo2-calc has the room to
  complete it.
