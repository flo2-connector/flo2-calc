# The operators: arguments, examples and edge cases

A reference file of the skill `support-a-decision-with-math`, for its steps 3, 4, 6 and 7. The rules (never type a
constant or a result in; what only you and the person can say) are in `SKILL.md`; this file holds what a reply
holds, and each operator family's arguments, examples and edge cases.

## What a reply holds (step 3)

- `evaluate_graph` returns the result and every node's value.
- Several parts are, for example, a verdict and its margin, an interval's two ends, a count and its rows. They come
  back by name, as `results`.
- The formula is the equation (`t = C / I = 450/13 h`); the working is every step, numbered, with its value and
  label. Both come in plain text and in LaTeX.
- Show the person the formula when it helps them check the reasoning: "run time t = C / I = 450 mAh / 13 mA, about
  34.6 h". The LaTeX form renders where their client renders math.

## Constants, roots, powers and logarithms

- `{"id": "pi", "op": "pi"}` and `{"id": "e", "op": "e"}` are the constants.
- `sqrt`, `exp`, `ln`, `log10`, and `pow` with a non-whole exponent (`"1/3"`, `"2.5"`).
- **Powers:** `pow` with a whole exponent is exact however large the exponent, until the exact number passes the
  host's digits budget; then it is refused with how many digits it would have. Add `"digits"` to that node for its
  correctly rounded value instead: `(1 - 1e-6)^(10^6)` with `"digits": 30`.

## Trigonometry

- `sin`, `cos`, `tan` take an angle WITH its unit (`"37.5 deg"`). `asin`, `acos`, `atan`, `atan2` need
  `"unit": "deg"` or `"rad"` for the angle they give. `convert` turns deg into rad.

## Distributions

- `normal_cdf`, `normal_sf` (the upper tail), `normal_quantile`, `chi2_sf` (a p-value), `t_quantile` (a critical
  value). The normal ones take `[x]`, or `[x, mean, sd]` in one unit.
- **Skewed populations:** `lognormal_cdf`, `lognormal_sf`, `lognormal_quantile` with `[x or p, median, sigma]`
  (sigma is the sd of ln X: a published geometric mean is the median, and sigma is the `ln` of its geometric sd);
  `gamma_cdf`, `gamma_sf`, `gamma_quantile` with `[x or p, shape, scale]` (scale in x's unit; 1 / rate);
  `beta_cdf`, `beta_sf`, `beta_quantile` with `[x or p, a, b]` (all plain).

## Rounding

- `ceil`, `floor`, `round` (with `"places"`; `round`'s `"mode"` is `half_even` unless you say otherwise).

## Decibels

- **dB to a ratio and back:** `db_to_ratio` and `ratio_to_db`, each with `"kind": "power"` (10 log10) or
  `"amplitude"` (20 log10). A power level converts with `convert`: `"10 dBm"` to `"mW"`, or a power in `mW` to
  `"dBm"`. A level plus a gain in dB is a level; two levels never add.

## Counting, combinatorics and the binomial

- **Counting:** `count_true` counts the true values; `k_of_n` with args `[k, b1, b2, ...]` is true when at least k
  are; `to_number` turns true into 1 and false into 0.
- **Combinatorics and the binomial:** `choose` (`[n, k]`), `factorial` (`[n]`), and `binomial_pmf`, `binomial_cdf`,
  `binomial_sf` with args `[k, n, p]`: P(X = k), P(X <= k) and P(X > k). "At least 3 of 5" is `binomial_sf` with
  k = 2. All exact for an exact p.

## Integers

- **mod, divides, gcd:** `mod` `[a, b]` is the remainder with the sign of b (`-7 mod 3` is 2; `b` = 0 is refused);
  `divides` `[d, n]` is true when n is a whole multiple of d (0 divides only 0); `gcd` takes two or more. Each works
  element by element on an exact array.
- **Primes:** `is_prime` `[n]` is proven true or false (false below 2), element by element on an array.
  `factorize` `[n]`, n >= 2, gives a grid of rows `[p, e]`, the primes increasing: 1681 is `[[41, 2]]`; read a row
  with `element`. Past the host's limits (the digits of a primality proof, the digits of the part factoring has to
  split) each is refused, `exceeds_limits`, never answered as "probably prime" or in part.
- **A run of whole numbers:** `integer_range` `[a, b]` is a, a + 1, ..., b, both ends included. Build on it rather
  than typing the numbers or their count; `length` gives the count. "Is n^2 + n + 41 prime for n = 0 to 39?":

```json
{"nodes": [
  {"id": "a", "value": "0", "source": "the question"}, {"id": "b", "value": "39", "source": "the question"},
  {"id": "c", "value": "41", "source": "the question"},
  {"id": "n", "op": "integer_range", "args": ["a", "b"]},
  {"id": "n2", "op": "mul", "args": ["n", "n"]},
  {"id": "v", "op": "add", "args": ["n2", "n", "c"]},
  {"id": "prime", "op": "is_prime", "args": ["v"]},
  {"id": "every", "op": "all", "args": ["prime"]}],
 "result": "every"}
```

- Every argument is an exact whole plain number: a fraction, a decimal with a fraction part, a value with a unit, a
  rounded value or true/false is refused, naming it. A range is exact or not made: past the host's limit on an exact
  array it is refused, not carried in float64.

## An empirical formula with stated units

**An empirical formula with stated units** (a datasheet's fit, a standard's relation, its formula and constants
given as `SKILL.md` says): put each constant in as an input whose source says where it was given, take each input's
number in the unit the formula states with `magnitude` (`{"op": "magnitude", "args": ["I"], "unit": "A"}`), compute
on the plain numbers, then put the stated unit on the result with `with_unit` and say which document states it:

```json
{"nodes": [
  {"id": "k", "value": "<the constant, as given>", "source": "given by the person: <document, edition, clause>"},
  {"id": "b", "value": "<the exponent, as given>", "source": "given by the person: <document, edition, clause>"},
  {"id": "x", "value": "<the input> <its unit>", "source": "the design's own quantity"},
  {"id": "x_num", "op": "magnitude", "args": ["x"], "unit": "<the unit the formula takes x in>"},
  {"id": "y", "op": "with_unit", "args": ["y_num"], "unit": "<the unit the formula gives y in>",
   "source": "<document, edition, clause>: y in that unit"}]}
```

(the nodes that compute `y_num` from `x_num`, `k` and `b` are the formula as given).

## What the operators for anything that is not exact give back

Their results come back labelled `"rounded"`: correctly rounded to 30 significant digits (ask for more with
`"digits"`, up to 1000), with `error_at_most`, and never with an `exact` fraction. Every digit it was asked for is
written, trailing zeros included. Anything computed from a rounded
value is labelled rounded too, with its bound. Where the result is rational it stays exact (`sqrt(9/4)` is `1.5`).

## Bayesian updating (step 6)

**A starting estimate from a published population, updated with the person's own readings.** For a normal prior and
readings with a known sd each, `posterior_normal_mean`, `posterior_normal_variance` and `posterior_normal_sd` take
`[prior_mean, prior_sd, data, data_sd]`, the data one reading or an array of them:

```json
{"nodes": [
  {"id": "m0", "value": "<population mean> <unit>", "source": "<the publication>: mean"},
  {"id": "s0", "value": "<between-person sd> <unit>", "source": "<the publication>: sd"},
  {"id": "x", "value": {"array": ["<reading>", "<reading>"], "unit": "<unit>"}, "source": "the person's readings"},
  {"id": "s", "value": "<sd of one reading> <unit>", "source": "<the meter's or assay's datasheet>"},
  {"id": "mean", "op": "posterior_normal_mean", "args": ["m0", "s0", "x", "s"]},
  {"id": "sd", "op": "posterior_normal_sd", "args": ["m0", "s0", "x", "s"]},
  {"id": "p_lo", "value": "0.025", "source": "a 95 % interval"},
  {"id": "lo", "op": "normal_quantile", "args": ["p_lo", "mean", "sd"]}],
 "result": ["mean", "sd", "lo"]}
```

For a rate (k of n), a Beta(a, b) prior: `posterior_beta_a`, `posterior_beta_b`, `posterior_beta_mean`,
`posterior_beta_variance` and `posterior_beta_sd` take `[a, b, k, n]`, and `posterior_beta_interval_lower` and
`posterior_beta_interval_upper` take `[a, b, k, n, level]` (the equal-tailed interval; give the level).

## The randomization test (step 6)

**Whether an on/off trial's difference is real.** `randomization_test` takes `[outcomes, on]`: an array of one outcome
per period in the order they ran, and a true/false array, true where the period was on. Its `"scheme"` is
`"every_arrangement"` when any set of that many periods could have been on, `"within_pairs"` when each pair of periods
(1-2, 3-4 ...) had one on and one off by a coin flip. Give `"statistic": "mean_difference"` and `"alternative"`:
`"greater"` or `"less"` for a question with a direction, `"two_sided"` for "any difference". The p-value is exact,
over every arrangement; its working says how many were as extreme: "p = 1/70: 1 of the 70 possible arrangements is as
low as yours".

## Shapley values (step 6)

**How to share credit among a few factors tried together.** `shapley_values` takes `[outcomes]`, an array with the
outcome of EVERY combination of the factors on or off, with `"factors"` (the names, in order) and `"combinations"`
(for each outcome, the list of the factors on in it): `{"op": "shapley_values", "args": ["v"], "factors": ["sleep",
"diet"], "combinations": [[], ["sleep"], ["diet"], ["sleep", "diet"]]}`. The values always sum to the outcome with
every factor minus the outcome with none, and the working shows it.

## When an operator refuses its argument (step 7)

`"kind": "out_of_domain"` or `"undefined"`: the argument is outside what the function takes (`sqrt(-1)`, a
probability of 1, `tan(90 deg)`). The computation, not the calculator, needs fixing. For an array, the reason names
the element (`at element [3]`).
