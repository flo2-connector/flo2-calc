# Hypothesis tests, power and sample size

A reference file of the skill `support-a-decision-with-math`, for its step 6. The rules (fix alpha, the test and
its alternative before the data; the decision's words; never work around a refusal) are in `SKILL.md`; this file
holds each test's arguments, what its record holds, and the edge cases.

## The tests

Each test's last argument is alpha, the significance level fixed in advance: an input such as
`{"id": "alpha", "value": "0.05", "source": {"design_node": "con:significance-level"}}`, exact, strictly between 0
and 1. Each but the chi-square tests needs `"alternative"`: `"greater"`, `"less"` or `"two_sided"`, as fixed before
the data. Data are arrays (`{"array": [...], "unit": "h"}`); a summary is the published numbers as inputs.

| Operator | Args | H0 |
|---|---|---|
| `z_test` | `[data, mu0, sigma, alpha]` or `[mean, n, mu0, sigma, alpha]` | mean = mu0, sigma known |
| `t_test_one_sample` | `[data, mu0, alpha]` or `[mean, sd, n, mu0, alpha]` | mean = mu0 (n - 1 degrees of freedom) |
| `t_test_two_sample` | `[data1, data2, alpha]` or `[mean1, sd1, n1, mean2, sd2, n2, alpha]`, with `"variance"` | mean1 = mean2 |
| `chi2_goodness_of_fit` | `[observed, expected, alpha]` | the categories occur in the expected proportions |
| `chi2_independence` | `[table, alpha]` (a grid of counts) | rows and columns are independent |
| `binomial_test` | `[k, n, p0, alpha]` | each trial succeeds with p0 |
| `fisher_exact` | `[table, alpha]` (2 x 2 counts) | odds ratio 1 (`"greater"`: row 1 more often in column 1) |

- **A paired test** (before and after on the same subjects) is `t_test_one_sample` on the differences, with mu0 0.
- **`"variance"`** for the two-sample t-test: `"welch"` when the variances may differ (its degrees of freedom are
  Welch-Satterthwaite's, and its p-value is Welch's approximation), `"pooled"` when the person has reason to take
  them as equal. Never defaulted.
- **Expected values** for goodness of fit are H0's proportions summing to exactly 1 (`"1/3"`, not `"0.33"`), or
  expected counts summing to the observed total.
- **A sd typed as published** is a decimal; with the data themselves the test computes the sd exactly. Give the data
  when you have them.

Student's sleep data, Welch's test:

```json
{"nodes": [
  {"id": "a", "value": {"array": ["0.7", "-1.6", "-0.2", "-1.2", "-0.1", "3.4", "3.7", "0.8", "0.0", "2.0"], "unit": "h"}, "source": "drug 1"},
  {"id": "b", "value": {"array": ["1.9", "0.8", "1.1", "0.1", "-0.1", "4.4", "5.5", "1.6", "4.6", "3.4"], "unit": "h"}, "source": "drug 2"},
  {"id": "alpha", "value": "0.05", "source": {"design_node": "con:significance-level"}},
  {"id": "p", "op": "t_test_two_sample", "args": ["a", "b", "alpha"], "variance": "welch", "alternative": "two_sided"}]}
```

gives p = 0.0794 (t = -1.861, 17.78 degrees of freedom): "fail to reject H0 at α = 0.05".

## What a test gives back

The node's value is the p-value. Its entry also holds `hypothesis_test`: `test`, `title`, `h0`, `h1`,
`alternative` (`"upper_tail"` for a chi-square test), `sidedness`, `alpha` (its node, value and source), `n`,
`statistic`, `dof` (the t and chi-square tests), `p_value`, `p_value_method`, `assumptions`, `decision` and
`reject_h0`, and `variance` for the two-sample t-test. The working step shows the statistic, the degrees of freedom,
n and reject_H0.

- **How the p-value is computed** is in `p_value_method`. The z- and t-tests' are the normal or Student-t tail,
  correctly rounded. The chi-square tests' are the chi-square tail, an approximation flo2-calc holds to its
  condition. The binomial and Fisher tests' are exact fractions; two-sided, they sum every outcome no more probable
  than the one observed.
- **The decision** is decided on the true p-value: a p-value shown to 2 digits as 0.08 against alpha 0.08 is still
  decided correctly.
- **`assumptions`** are the premises the result stands on (independence, normality, equal variances, expected
  counts). flo2-calc checks only what it can (the expected counts); the rest are yours and the person's to state,
  and an objection can attack each.
- **The record holds no time.** When alpha and the test were fixed, and whether they changed after the data, is the
  design's history: give alpha a `design_node` source so that history can be found.

## When a test refuses (`"kind": "assumption_fails"`)

A chi-square test whose expected count in any cell is below 5 is refused, naming the cell: the chi-square
distribution is not a fair approximation there. Use the exact test it names (`fisher_exact` for a 2 x 2 table,
`binomial_test` for two categories), collect more data, or combine categories only where the person agrees that is
meaningful. Never drop a cell or round a count to get past it.

## Power and sample size, before the data

Each test has `<test>_power` (the power at n) and `<test>_sample_size` (the smallest n whose power reaches a
target), with the same `"alternative"` and `"variance"` as the test. Alpha is the last argument.

| Operators | Args (power; sample size) |
|---|---|
| `z_test_power`, `z_test_sample_size` | `[delta, sigma, n, alpha]`; `[delta, sigma, power, alpha]` |
| `t_test_one_sample_power`, `_sample_size` | `[delta, sd, n, alpha]`; `[delta, sd, power, alpha]` |
| `t_test_two_sample_power`, `_sample_size` | as above, n per group; `"variance": "pooled"` |
| `chi2_goodness_of_fit_power`, `_sample_size` | `[p0, p1, n, alpha]`; `[p0, p1, power, alpha]` |
| `chi2_independence_power`, `_sample_size` | `[p1, n, alpha]`; `[p1, power, alpha]` (p1 a grid of joint proportions) |
| `binomial_test_power`, `_sample_size` | `[p0, p1, n, alpha]`; `[p0, p1, power, alpha]` |
| `fisher_exact_power`, `_sample_size` | `[p1, p2, n, alpha]`; `[p1, p2, power, alpha]`, n per group |

- **delta** is the smallest difference worth finding, signed (a one-sided alternative looks one way), and the sd is
  the one the plan assumes: both come from the person or a pilot study, as inputs with their sources.
- **The entry's `test_plan`** holds `test`, `kind` (`power` or `sample_size`), `title`, `alternative`, `alpha`,
  `effect`, `n` and `n_is`, `power` (at n), `target_power` (a sample size), `method` and `assumptions`. A sample
  size's working shows the power at n and at n - 1.
- **Welch's test has no exact power**: plan with `"pooled"` and say it is the plan's assumption.
- **The chi-square plans** use the noncentral chi-square approximation (lambda = n w^2), and a planned n also needs
  every expected count under H0 to be at least 5: the sample size is the larger of the two, both shown.
- **The exact tests' power is not monotone in n**: it saw-teeths, so a larger n can have less power. The sample size
  is the smallest n that reaches the target; say so when you quote it.
- A target that no n reaches (at most alpha, no effect, an effect the other way from a one-sided alternative) is
  refused with its reason. A search past the host's deadline is stopped like any calculation (step 11).

A two-group plan: "with delta 1 h and sd 1 h, two-sided at alpha 0.05, 90 % power needs 23 per group":

```json
{"nodes": [
  {"id": "d", "value": "1 h", "source": {"design_node": "con:smallest-effect-worth-finding"}},
  {"id": "s", "value": "1 h", "source": "pilot study"},
  {"id": "target", "value": "0.9", "source": {"design_node": "con:target-power"}},
  {"id": "alpha", "value": "0.05", "source": {"design_node": "con:significance-level"}},
  {"id": "n", "op": "t_test_two_sample_sample_size", "args": ["d", "s", "target", "alpha"],
   "variance": "pooled", "alternative": "two_sided"}]}
```
