# Records: saving, re-checking, completing one past the limits, and re-deriving one

A reference file of the skill `support-a-decision-with-math`, for its steps 8, 10, 11 and 12. The rules (make the
record, link it, never slip under a limit, re-derive rather than edit) are in `SKILL.md`.

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
  256 x 256 grid's FFT fits), 1,000,000 arrangements in one randomization test, Shapley values of at most 12
  factors, primes proven up to 200 digits and a factorization's hard part up to 40 digits.
- The refusal names the limit (a deadline, `max_digits`, `max_reply_bytes`, `max_array_bytes`, `max_arrangements`
  for a randomization test, `max_shapley_factors` for a Shapley table, `max_prime_digits` for a primality proof,
  `max_factor_digits` for a factorization, or `max_exact_elements` for an integer range), its value, the node
  reached and how large the numbers grew.
- The not-yet-computed record holds the graph, the inputs with their sources and the limit it passed, but no
  result.
- To complete it, pass it as `record` to `record_computation` on a flo2-calc with more room, such as one started
  with a higher `--max-digits` or `--deadline`. The completed record has the same name, graph and inputs, now
  with the result. It is exactly the record a direct computation would give. Link it in place of the
  not-yet-computed one.
- `rerun_record` on a not-yet-computed record says it has no result yet, and whether this flo2-calc has the room to
  complete it.

## A kept record re-derived when an input changes (step 12)

- Use it when a number a kept record took has changed: a re-measured wall area, a revised footprint, a design
  quantity the record's input is bound to (`inputs_bound`). It evaluates the record's own graph with the new
  values, so the formula stays the one that was checked.
- Each change is `{"input": "A", "value": "1350 ft^2", "source": "re-measured wall"}`. A bound input keeps its
  binding when its source is `{"design_quantity": "<id>"}` again.
- A new value in another unit of the same kind is taken and converted exactly (`"3 m"` for `"9 ft"`). One of
  another kind is refused, naming what arrived: an area for a length, a temperature for a change of temperature, a
  plain number for a quantity. A name that is not one of the record's inputs is an error that lists them.
- The reply's `moved` gives each result old -> new, `unchanged` the results that did not move, and `values` every
  other node that moved. Quote the moved results to the person in their terms ("the wall now loses 4,974 Btu/h, up
  from 4,421").
- The new record keeps the same name and `supports`, and its `history` names the record it came from by its content
  hash, with every change it went through. `rerun_record` re-runs it like any record.
- No new record is made when the record you passed was changed after it was made, does not re-run here, is of
  schema version 1 to 6 (made under older rules: make it again with `record_computation`), or when the changed
  graph is refused (a division by zero, say). The record you passed stands; say why.
- To change the formula itself, not an input, compose the graph again with `record_computation`.
