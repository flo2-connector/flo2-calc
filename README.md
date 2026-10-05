# flo2-calc: exact math and logic for the decisions in a design

flo2-calc is an MCP server that does a design's arithmetic and logic, so that a critical decision can carry the
computation that supports it: the operators, the inputs with their units and where each came from, and the result.
The math is done here, exactly, not by the model.

**It is the calculator of record: trust and traceability, not breadth.** Wolfram, MATLAB and SciPy wrappers do far
more math. flo2-calc does what a decision needs and keeps the evidence: every result is exact, or rounded with a
proven bound and labelled so, or refused with its reason; units are part of the value; the working is shown, step by
step, from what was actually computed; and the whole computation is a record anyone can re-run. Operators are added
when a question set or a real design needs them, never for parity (`dec:idea-what-sets-flo2-calc-apart-from-other-math-mcps`).

- **Exact for these inputs.** Every number is an exact fraction. `0.1 + 0.2` is `0.3`, and every unit conversion is
  exact. A result is exact for the inputs as written, and no more accurate than they are: a typed `3.14159` is taken
  as that decimal, not as pi, and every reply and record says so.
- **Or correctly rounded, and labelled so.** pi, e, roots, `exp`, `ln`, `log10`, non-whole powers, trigonometry,
  deg-rad conversion and the normal, chi-square and Student-t distributions are irrational in general. Their results
  are **correctly rounded** to 30 significant digits (or as many as a node asks, up to 1000), labelled `rounded` with
  a rigorous `error_at_most`, and never called exact. Where the result is rational it stays exact: `sqrt(9/4)` is
  `3/2`, and `sin(30 deg)` is `1/2`.
- **Arrays, like numpy.** Vectors and grids with one unit each: element-wise arithmetic, logic and functions, sums
  and other reductions (along an axis of a grid too), statistics over data (variance and standard deviation, sample or
  population, and a least-squares fit with standard errors) and the FFT. An exact array stays exact; an FFT, a
  function over an array or a large grid is computed in float64 and labelled `float64`, with a rigorous bound on every
  element.
- **Units, checked.** A value can carry a unit, spelled as reflow2 designs spell it (`mm`, `g`, `V`, `mA`, ...).
  Units that measure different things are refused, naming the operation and both units, never stripped. A unit
  flo2-calc does not know is refused, never guessed, and a hint never offers a unit of another size or kind.
- **Correct or refused.** A computation that cannot be done says which node, which operation and why. It never
  returns a number it cannot stand behind. An ambiguous expression is given back with both readings, never one chosen.
- **The agent reasons; flo2-calc calculates.** It never chooses an equation, and an empirical formula's constants come
  from the person or a document they can check, never from the agent's memory: the served skill and the server's
  instructions say so, because flo2-calc cannot tell where a number came from.
- **Shown back.** Every reply and record shows the computation as a formula and as numbered steps, each in plain text
  with LaTeX beside it: `t = C / I = 450/13 h`. You can check it is the computation you meant.
- **Re-runnable.** A computation comes back as a **computation record**, a `.calc.json` file a decision can cite.
  Anyone can re-run it and get the same values, and an edited record is caught.
- **Never runs away.** Each host sets limits at start-up: a deadline per call, and a budget for the digits of any
  exact number and for the reply. They are the only limits. A calculation past one is stopped cleanly, with its reason. A recorded one comes
  back as a **not-yet-computed record** that flo2-calc on a machine with more room completes.

It stands alone. Nothing in it imports, calls or assumes flo2, reflow2 or another helper, and no feature needs them.
Its spec is the flo2-hosted design "reflow2 calculator" (`0bee0c00b35845f6`). Build agents start from
[AGENTS.md](AGENTS.md); agents that use it start from
[skills/support-a-decision-with-math/SKILL.md](skills/support-a-decision-with-math/SKILL.md).

## Standalone

flo2-calc runs on your machine as a plugin, as a command, or in Docker. It needs Python 3.12 (uvx fetches it) and
nothing else running.

**As a plugin.** The repository root is both a Claude Code plugin (`.claude-plugin/plugin.json`, `.mcp.json`) and an
[Agent Plugins 1.0.0](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json) plugin (`plugin.json`, `mcp.json`).
Grok Build reads Claude's format as it is. Both formats start the same server, with the same skill:

```sh
uvx --from git+https://github.com/flo2-connector/flo2-calc flo2-calc --root .
```

**As a command**, in any MCP client's configuration:

```json
{ "mcpServers": { "flo2-calc": { "command": "uvx",
  "args": ["--from", "git+https://github.com/flo2-connector/flo2-calc", "flo2-calc", "--root", "."] } } }
```

**In Docker:** `docker build -t flo2-calc .` then `docker run --rm -i flo2-calc`.

**The skill comes with the server.** An agent that uses flo2-calc should read
[skills/support-a-decision-with-math/SKILL.md](skills/support-a-decision-with-math/SKILL.md): when to use it, what to
route to a domain's own helper, and the rules against typing constants, changing prefixes or deciding what a rounded
value cannot. A plugin install brings it. A client that starts flo2-calc as a plain command gets it from the server
itself, as the MCP prompt `support-a-decision-with-math` and the resource
`skill://flo2-calc/support-a-decision-with-math/SKILL.md` (`text/markdown`). Both are read from that one file; the
wheel and the image carry it.

### Saving records

A record always comes back inside the reply, as the embedded file `calcfile:///<name>.calc.json`. Run locally, it can
also be written to disk:

- `--root <folder>` (or `FLO2_CALC_ROOT`) names the **one** folder flo2-calc may write records in and read them from.
  The plugin passes `--root .`, the folder the agent was started in.
- `record_computation`'s `output_path` (for example `decisions/fiber-bend.calc.json`) writes the record there. A path
  outside the root, a path through a link that leads out of it, and a name not ending in `.calc.json` are refused. A
  file that already exists is never written over: the same record again is left alone, and a different one is refused.
- `rerun_record`'s `path` re-runs a record file inside the root.
- With no root, flo2-calc touches no file at all, and `output_path` or `path` is refused with the reason.

## Hosted on flo2.io

On flo2.io, flo2-calc would run as a **helper** beside a person's design, the way flo2-cad and flo2-ifc do: one
container per person and design, from this repository's `Dockerfile` at a pinned commit, with no network, a read-only
root and no `--root`. A chat reaches it through flo2's shared door, `use_helper_tool`. flo2 keeps the files a helper
returns from a step that writes, so the record `record_computation` returns becomes a file in the person's design,
kept every version. The agent links it to the decision it supports.

flo2 has no door for flo2-calc yet. What it needs is listed under "What flo2 needs to host it", below.

## Limits

flo2-calc's arithmetic is exact, and exact numbers can grow without bound: a high power, or a long chain of
divisions, gives numerators and denominators of thousands of digits. So each host sets three limits at start-up,
the same way as `--root`: a flag, or its environment variable. A calculation past one is **stopped cleanly, with its
reason**. It is never cut short, never guessed, and never killed by a sandbox as if it had crashed.

| Limit | Flag | Variable | Laptop (the default) | flo2.io's sandbox (the image) |
|---|---|---|---|---|
| deadline, per call | `--deadline SECONDS` | `FLO2_CALC_DEADLINE` | 45 s | 20 s |
| digits of any exact numerator or denominator | `--max-digits N` | `FLO2_CALC_MAX_DIGITS` | 20,000 | 2,000 |
| bytes in a reply, its record included | `--max-reply-bytes N` | `FLO2_CALC_MAX_REPLY_BYTES` | 8,388,608 (8 MiB) | 2,097,152 (2 MiB) |
| bytes the arrays of one call may hold | `--max-array-bytes N` | `FLO2_CALC_MAX_ARRAY_BYTES` | 536,870,912 (512 MiB) | 16,777,216 (16 MiB) |
| elements an exact array may have (past it: float64, labelled) | `--max-exact-elements N` | `FLO2_CALC_MAX_EXACT_ELEMENTS` | 65,536 (a 256 x 256 grid) | 4,096 (a 64 x 64 grid) |

Why each value:

- **Deadline, 45 s on a laptop.** MCP clients built on the official TypeScript SDK give up on a request after 60 s
  (`DEFAULT_REQUEST_TIMEOUT_MSEC`). flo2-calc stops first, with time left to send its reason.
- **Deadline, 20 s on flo2.io.** flo2's gateway stops a helper call at 60 s (`CAD_CALL_MS` in
  `services/edge-gateway/src/cad-door.ts`, and `DEFAULT_CALL_MS` for any helper). A third of that leaves flo2-calc
  40 s to send the refusal and the not-yet-computed record, on one shared CPU. A person in a chat is not left waiting
  a minute.
- **Digits, 20,000 on a laptop.** That is far past any number a decision rests on. One step on two such numbers
  takes about 10 ms on one CPU, so a deadline is never overrun by more than that. A host may set up to 100,000; at
  that size one step takes most of a second.
- **Digits, 2,000 on flo2.io.** Still far past a decision's numbers. Every value in a 500-node graph can then be
  written out exactly within the reply budget, so 128m holds the heaviest call the profile allows. Its measured
  peak is 91 MiB (Measurements, below). The record of the very heaviest such graph, which since 0.5.0 also carries
  its formula and every working step, passes the 2 MiB reply budget and comes back as a not-yet-computed record.
- **Reply, 8 MiB on a laptop.** That is room for a 500-node graph of large exact values. A record larger than the
  budget is also refused as input, so a host never takes in a record it could not have made.
- **Reply, 2 MiB on flo2.io.** This is the most flo2's door keeps of a `calcfile` in one reply, well under its
  gateway's 16 MiB reply cap.
- **Arrays, 512 MiB on a laptop.** Room for a 1024 x 1024 grid's FFT workflow many times over. The budget counts
  what each array holds (a float64 element and its bound 16 bytes, a complex one 24, a true/false 1, an exact one about
  128 with its digits) and, for an FFT whose length is not a power of two, the room Arb's check of it takes while it
  runs.
- **Exact arrays, 65,536 elements on a laptop and 4,096 on flo2.io** (`dec:v0-6-0-array-choices`). This one is not a
  stop: past it an array is carried in float64 and labelled so, as `dec:idea-how-arrays-are-computed` has large grids
  be. An exact element costs about 128 bytes and a float64 one 16, so flo2.io's lower value keeps a 256 x 256 grid's
  workflow inside its array budget and its 128m cap. A computed record that holds an array keeps the value it was made
  with (`max_exact_elements`), and re-running uses that value, not the host's, so the record re-runs to the same values
  anywhere; a version 5 record (0.6.0) was made with a fixed 4,096 and re-runs with it.
- **Arrays, 16 MiB on flo2.io.** A 256 x 256 grid's discretised integral and 2-D FFT hold about 7 MiB; the image's
  measured peak with them is 105 MiB under the 128m cap (Measurements, below).

**These are the only limits on a calculation.** A power has no exponent cap of its own: flo2-calc 0.1.0 to 0.6.1
also refused any whole exponent above 1000 (kind `too_large`), a cap none of the served limits named, which refused
`2^1001` (302 digits) and gave `record_computation` no not-yet-computed record (round 3, q072 and q086). Since 0.7.0 a
power is sized against the digits budget alone. How a graph may be written (at most 500 nodes, 100 arguments a
node, 1,000 digits for a rounded value, 80 characters for a number) is part of the graph's form: a graph past it is a
malformed call naming the field, not a stopped calculation.

The image sets flo2.io's profile (`ENV` in the `Dockerfile`). Run elsewhere, pass your own, for example
`docker run -e FLO2_CALC_MAX_DIGITS=20000 ...`. A workstation raises them all. A setting flo2-calc cannot use, such as
`--max-digits 5`, stops it at start-up with the reason, and is never silently replaced. The limits in force are in
the server's instructions, and in every refusal they cause.

How they are kept (`src/flo2_calc/limits.py`):

- **While running.** The deadline is checked before every node, after every step of an operation with many
  arguments, and every 1,024 elements of an array operation. An array is sized from its shape BEFORE it is made, so
  one too large for the host is never allocated. Every input, partial sum, partial product and value is held to the digits budget. The reply is measured
  as it is written, so a reply too large to send is never built whole.
- **A power is sized BEFORE it is computed.** A huge power stalls inside a single Python operation, which nothing can
  interrupt. For example, a 20,000-digit number to the power 1000 takes about 44 s on one CPU. flo2-calc counts the
  power's digits from its operands first (exactly, `floor(n log10 b) + 1`, decided by Arb), and refuses one that would
  pass the budget, at once, saying how many digits it would have: `2^(10^9)` would have 301,029,996, more than any
  host can be set to carry. Where the exact power passes the budget, a `pow` node given `"digits"` returns its
  correctly rounded value instead (`(1 - 1e-6)^(10^6)`, whose exact numerator has 6,000,000 digits, is
  `0.367879257231645094285798125270`), and the refusal says so when that value would fit. A whole power of a rounded
  base takes any exponent, sized from the value it will have.
- **The refusal** is a normal reply, never `isError`. It has `kind: "exceeds_limits"` and names:
  - the limit, its value, and the least it would have needed when that is known (`needed_at_least`);
  - the setting that raises it;
  - the node reached and how many nodes were done;
  - how many digits the largest number had reached;
  - the time taken;
  - the limits in force.

  For example:

  ```json
  {"node": "z", "op": "pow", "kind": "exceeds_limits",
   "reason": "pow at node \"z\": the power's numerator would have 20,000,000 digits, past this host's budget of 20,000 digits for any exact number, so it was not computed ...",
   "limit": {"name": "max_digits", "value": 20000, "needed_at_least": 20000000, "setting": "--max-digits or FLO2_CALC_MAX_DIGITS"},
   "reached": {"nodes_done": 4, "nodes": 5, "largest_digits": 20000, "elapsed": "0.002 s"},
   "limits": {"deadline": "45 s", "max_digits": 20000, "max_reply_bytes": 8388608}}
  ```

## Tools

| Tool | Class | Arguments | Returns |
|---|---|---|---|
| `evaluate_graph` | read | `graph` | `status` (`ok` or `refused`), the `result` (or `results`), every node's value in evaluation order, the `formula` and `working` (below), and `exactness` (below) |
| `add_node` | read | `node`, `graph?` (the graph so far) | the new node's value, every value so far, the `formula` and `working`, and the grown `graph` to pass next time |
| `record_computation` | write | `graph`, `name`, `supports?`, `output_path?`; or, to complete one, a not-yet-computed `record` | the result, the `formula` and `working`, the record's file name, sha256 and content hash, and the record as `calcfile:///<name>.calc.json`. Stopped at a limit: the refusal and a not-yet-computed record |
| `rerun_record` | read | `record` (the object or its text) or `path` | `reproduces`, whether the content hash matches, every difference, and the re-run's `formula` and `working`. For a not-yet-computed record: that it has no result yet, and what it needs |

"Class" is the tool's `readOnlyHint`, which flo2's door reads: `record_computation` makes a file to keep. Nothing is
kept between calls. `add_node` is stateless: the graph you pass is the whole state, so a graph built node by node is
the same graph, and gives the same result, as the same nodes sent whole.

### A graph

```json
{"nodes": [
  {"id": "cavity", "value": "2 mm", "source": {"design_node": "con:cavity-depth"}},
  {"id": "bend",   "value": "1.4 mm", "source": "fiber datasheet: minimum bend radius"},
  {"id": "margin", "op": "sub", "args": ["cavity", "bend"]},
  {"id": "needed", "value": "0.5 mm", "source": "assumed"},
  {"id": "fits",   "op": "ge", "args": ["margin", "needed"]}],
 "result": "fits"}
```

- **An input** has a `value`: a number with its unit as text (`"1.4 mm"`), a plain number (`"0.1"`, `"1/3"`, or a
  JSON integer), or `true`/`false`. A JSON number with a fraction part (`0.1`) is refused, because it arrives as a
  binary float whose exact value is already lost: write `"0.1"`.
- **A value is one number.** Arithmetic typed inside a value (`"2^10"`, `"1/0.725"`) is refused as an expression,
  with the shape of the nodes to build instead: `{"id": "<name>", "value": "<number> <unit>", "source": "..."}` and
  `{"id": "<name>", "op": "<operator>", "args": ["<id>", "<id>"]}`. It is never read as a number and a strange unit.
  A **malformed** one (`"3 + * 4"`, `"(3 + 4"`, `"2 1/2"`) is called malformed, with where (`no operand between "+"
  at character 3 and "*" at character 5`), and the agent is told not to repair it but to ask what was meant. The
  refusal's example has no number and no operator of the input's own: round 2 found the old example, `3` and `4`
  joined by `add`, was the very guess forbidden for `"3 + * 4"`. An **ambiguous** one is not malformed: an implied
  multiplication (`"6/2(1+2)"`: a value written directly next to a bracket) reads one way if it is an ordinary `*`
  taken left to right, `(6 / 2) * (1 + 2)`, and another if it binds first, `6 / (2 * (1 + 2))`. The refusal says it is
  ambiguous, gives both readings, chooses neither, and asks for the person's reading or both values as nodes (round 3
  found 0.6.1 calling it malformed, which, obeyed, dropped the two readings).
- **Its `source`** says where the value came from: free text, or `{"design_node": "<id>"}` naming a node in a reflow2
  design (add `"design": "<id>"` for another design). flo2-calc records it and never resolves it. A record needs a
  source on every input.
- **An operation** has `op` and `args`, the ids of the nodes it takes. Nodes may be listed in any order. A cycle, a
  missing id or an unknown operator is a malformed call naming the field.
- `result` names the result node, and defaults to the last node listed. A **list** of ids (`"result": ["lo", "hi"]`)
  reports each by name, in that order, as `"results"`: a pass/fail with its margin, a count with its rows, an interval
  with both ends.

**Operators** (set operations come later):

| Family | Operators |
|---|---|
| arithmetic | `add`, `sub`, `mul`, `div`, `neg`, `abs`, `pow`, `min`, `max`, `convert` (with `"unit"`) |
| functions | `sqrt`, `exp`, `ln`, `log10` |
| constants | `pi`, `e` (no `args`) |
| trigonometry | `sin`, `cos`, `tan` (of an angle in `deg` or `rad`); `asin`, `acos`, `atan`, `atan2` (with `"unit"`: `"deg"` or `"rad"`, the unit of the angle they give) |
| rounding | `ceil`, `floor`, `round` (with `"places"`, and for `round` a `"mode"`) |
| statistics | `normal_cdf`, `normal_sf`, `normal_quantile`, `chi2_sf`, `t_quantile`, `binomial_pmf`, `binomial_cdf`, `binomial_sf` |
| logic | `and`, `or`, `not`, `nand`, `nor`, `xor` |
| comparison | `eq`, `ne`, `lt`, `le`, `gt`, `ge` |
| counting | `count_true`, `k_of_n`, `to_number` |
| combinatorics | `choose`, `factorial` |
| units | `magnitude` (with `"unit"`), `with_unit` (with `"unit"` and `"source"`) |
| decibels | `db_to_ratio`, `ratio_to_db` (each with `"kind"`: `"power"` or `"amplitude"`) |

- **`pow`** is exact for a whole exponent of any size, sized first against the digits budget (Limits); with `"digits"`
  a whole power past the budget is correctly rounded instead, and a whole power of a rounded base is rounded with its
  bound. A non-whole exponent (`"1/3"`, `"2.5"`) needs a base of 0 or
  more and gives a rounded value, unless the result is rational: `27` to the `1/3` is exactly `3`. A unit survives only
  an exact root: `9 m^2` to the `1/2` is `3 m`, and `2 m` to the `0.5` is refused.
- **`sqrt`** takes a value of 0 or more. `m^2` gives `m`, and `m/s` squared gives `m/s`. A unit with no exact square
  root (`m`, `m^3`) is refused. `%` is folded in first: `sqrt(4 %)` is `0.2`.
- **`exp`, `ln`, `log10`** take a plain number. A unit is refused, never dropped: divide by a value in the same unit
  first. `ln` and `log10` need a number above 0.
- **Trigonometry.** `sin`, `cos` and `tan` take an angle with its unit. A plain number is refused, so an angle is never
  read in the wrong unit. In degrees the rational values are exact (`sin(30 deg)` is `0.5`, `tan(45 deg)` is `1`), and
  `tan(90 deg)` is refused. `asin` and `acos` take a plain number from -1 to 1. `atan2` takes `[y, x]` in one unit and
  gives the angle in (-180, 180] deg; `atan2(0, 0)` is refused.
- **`convert` between deg and rad** (and between `deg/s` and `rad/s`, and the like) is a rounded value, because pi/180
  is irrational. `0 deg` converts to exactly `0 rad`. Adding or comparing deg with rad is still refused: convert one
  first.
- **`ceil`, `floor`, `round`** are exact. They round to `places` decimal places (default 0; negative rounds to tens,
  hundreds ...), in the value's own unit. `round`'s `mode` is `half_even` by default; the others are
  `half_away_from_zero`, `half_toward_zero`, `half_up` (ties toward +infinity) and `half_down` (ties toward -infinity).
- **Statistics.**
  - `normal_cdf` and `normal_sf` take `[x]` for the standard normal, or `[x, mean, sd]` in one unit. `sd` must be more
    than 0. `normal_sf` is the upper tail, computed through `erfc`, so `normal_sf(12)` keeps all its digits
    (`1.77648211207767...e-33`), where 1 minus the cdf would give 0.
  - `normal_quantile` takes `[p]` or `[p, mean, sd]`, with `p` strictly between 0 and 1. The result is in the mean's
    unit.
  - `chi2_sf` takes `[x, dof]`: the upper tail, a chi-square test's p-value.
  - `t_quantile` takes `[p, dof]`: the Student-t critical value.
  - Degrees of freedom are an exact plain number above 0; a rounded one is refused.
  - `binomial_pmf`, `binomial_cdf` and `binomial_sf` take `[k, n, p]`: P(X = k), P(X <= k) and P(X > k) for n
    independent trials of probability p. "At least 3 of 5" is `binomial_sf` with k = 2. `k` and `n` are exact whole
    numbers, `p` a plain number from 0 to 1. Exact for an exact `p` (`binomial_sf(2, 5, 0.8)` is `0.94208`); from a
    rounded `p`, rounded with a bound from the polynomial's values over `p`'s ball. Whether the trials are independent
    with one `p` is the agent's judgement.
- **`digits`**: any rounded operator may take `"digits"`, from 1 to 1000 significant digits; 30 when left out.
- **`count_true`** counts the true values among its arguments: an exact whole number. **`k_of_n`** takes `[k, b1, b2,
  ...]` and is true when at least `k` of the `b` are true (`k` an exact whole number from 0 to their count). `add` still
  refuses true/false: booleans never add as numbers. **`to_number`** is the one way a true/false value becomes a
  number: true is `1`, false is `0` (element by element for a true/false array).
- **`choose`** (`[n, k]`, the binomial coefficient, `0` when `k > n`) and **`factorial`** (`[n]`) are exact, on exact
  whole numbers of 0 or more, and sized before they are computed.
- **Units for an empirical formula.** An empirical relation (a datasheet's curve fit, a standard's sizing rule) works on
  numbers taken in stated units. `magnitude` takes a quantity's number in a named unit (`2 A` in `"mA"` is `2000`),
  refused unless the quantity measures what that unit measures, so `2000` is never read as amperes. `with_unit` puts a
  stated unit on a plain number (`"unit": "mm^2"`), and must say in `"source"` which document states that unit,
  because flo2-calc cannot check it. Both are kept in the graph and the record, so a typed `1 mm^2` can no longer
  stand in for the unit.
- **An empirical formula's constants come from the person or a cited document, never from the agent's memory.** The
  served skill and the server's instructions say so: compute such a formula only when the formula and every constant
  were given, each constant an input whose `source` says where (`"given by the person"`, or the document, edition and
  clause); when a named standard's result is asked for without them, ask for them, or name the document and edition
  and have the person confirm before calculating. flo2-calc cannot tell where a number came from, so this is the
  guard. Round 3 (held-out q077) found an agent computing an IPC-2221 trace width from four constants it recalled,
  following the skill's example of round 2, which was written from a question where the constants were given.
- **Decibels.** `db_to_ratio` turns a gain in dB into a plain ratio, and `ratio_to_db` a plain ratio above 0 into dB.
  Each must be told `"kind"`: `"power"` (10 log10) or `"amplitude"` (20 log10). There is no default, because the same
  10 dB is a power ratio of 10 and an amplitude ratio of about 3.16. Both are rounded, and exact where the result is a
  power of ten.

### Units

Spelled as reflow2 spells them, one spelling each. The vocabulary is in `src/flo2_calc/units.py`:

| Measures | Units |
|---|---|
| length | `m` `km` `cm` `mm` `um` `nm` `in` `ft` `mil` (a thousandth of an inch), `furlong` (660 ft, exactly 201.168 m) |
| mass | `kg` `g` `mg` `ug` `t` `ct` `lb` `oz` (the avoirdupois ounce), `ozt` (the troy ounce, exactly 31.1034768 g), `dwt` (the pennyweight, 1/20 ozt), `grain` (exactly 64.79891 mg) |
| time | `s` `ms` `us` `ns` `min` `h` `d` `week` (7 d) `fortnight` (14 d) |
| electrical | `A` `kA` `mA` `uA` `nA` `pA`, `V` `kV` `mV` `uV`, `ohm` `mohm` `kohm` `Mohm`, `farad` `mF` `uF` `nF` `pF`, `H` `mH` `uH`, `coulomb` `Ah` `mAh` |
| power, energy | `W` `MW` `kW` `mW` `uW`, `J` `kJ` `MJ` `mJ` `uJ` `Wh` `mWh` `kWh` `MWh` `eV` |
| frequency, force | `Hz` `mHz` `kHz` `MHz` `GHz`, `N` `kN` `lbf` |
| pressure | `Pa` `mPa` `kPa` `MPa` `GPa` `bar` `psi` `ksi` |
| temperature | `K`, `degC` `degF` (a temperature), `delta_degC` `delta_degF` `delta_K` (a change of temperature) |
| volume | `L` `mL`, `gal_us` (231 in^3, exactly 3.785411784 L), `gal_imp` (exactly 4.54609 L) |
| angle | `deg` `arcmin` `arcsec`, `rad` |
| money | `USD` `EUR` `JPY` `GBP` `CNY` `AUD` `CAD` `CHF` `HKD` `SGD` |
| decibels | `dB` (a gain or loss), `dBm` `dBW` (a power level, dB above 1 mW or 1 W) |
| other | `%` |

- **Compound units:** `*` between units, `^n` for a power, and one `/` with a bracketed product after it, for
  example `mm^2`, `m/s^2`, `N*m`, `kg/(m*s^2)`, `1/s`.
- **Mixed units** convert exactly to the first operand's unit: `1 m + 20 cm` is `1.2 m`, and `2 m * 3 mm` is
  `0.006 m^2`. `convert` changes a unit: `3.3 V * 20 mA`, converted to `mW`, is `66 mW`.
- **Percent** is a plain ratio: `200 g * 5 %` is `10 g`, and `10 % * 2` is `20 %`.
- **Refused:**
  - units that measure different things (`2 mm + 3 g`);
  - a unit against a plain number (`2 mm + 3`);
  - an unknown spelling, never guessed. A bare `gal` is two units, and the refusal names both; so is a bare `gr`
    (the grain, or the gram). A spelling pint reads but flo2-calc does not carry (`mile`, `hp`) is named for what
    pint reads it as, with the units of that kind flo2-calc knows; nothing is substituted and no factor is offered
    (round 3: `ozt` got no hint, and the agent typed 31.1034768 g).
- **Angles** are their own dimension, so `30 deg + 1` is refused. `arcmin` and `arcsec` are exact fractions of a
  `deg` (1/60 and 1/3600). `deg` and `rad` are never mixed in one operation, because their ratio is pi/180, which no
  fraction holds exactly. `convert` turns one into the other (and `arcmin` or `arcsec` into `rad`, through `deg`) as a
  correctly rounded value, labelled rounded.

#### Decibels

A **gain** (or loss) is a value in `dB`, and `dB` is its own dimension, like a currency:

- `3 dB + -1.5 dB` is `1.5 dB`, `0.2 dB/m * 30 m` is `6 dB`, and dB compares with dB;
- dB with a plain ratio is refused (`3 dB + 2`, `convert` to `""`), and the refusal names `db_to_ratio` and
  `ratio_to_db`. Round 2's agents typed the decibel definition themselves, and a 10 in place of a 20 would have
  been recorded as valid.

A **power level** is a value whose whole unit is `dBm` or `dBW`. Like a temperature on a scale with an offset, it is
not a quantity that adds or multiplies (`src/flo2_calc/decibels.py`):

| Operation | Rule |
|---|---|
| `convert` | to `dBm` or `dBW` exactly (`x dBW` is `x + 30 dBm`), or to a power, `W`, `mW` ... (`10 dBm` is `10 mW`; `13 dBm` is about `19.95 mW`, rounded), and from a power to a level. dBm is a power level by definition, so no kind is needed. |
| `add` | at most one level, plus gains in dB: a level (`20 dBm + -6 dB` is `14 dBm`). Two levels are refused: their sum is not the level of the total power. |
| `sub` | level minus level is a gain in dB (`-50 dBm` is `-80 dBW`); level minus gain is a level; gain minus level is refused. |
| `eq` ... `ge`, `min`, `max` | levels with levels, on one scale. A level is never compared with a gain. |
| `ceil`, `floor`, `round` | in the level's own unit. |
| anything else | refused: convert the level to a power first, or work with gains. |

A level is read only as a value's whole unit: `dBm/Hz` is refused. A level refusal is of kind `decibel_level`.

#### A hint never changes what you wrote

A spelling flo2-calc does not know may come back with the spelling to use, and that hint never changes what was
written, in size or in kind:

- **A listed near miss** names its spelling: `µm` gives `Write "um"`, `Ω` gives `Write "ohm"`, `°C` gives
  `Write "degC"`. Each is tested to mean exactly what its target means.
- **A slip in the case of a unit's name** is hinted only when it cannot change a prefix: `khz` gives `Write "kHz"`,
  and `kOhm` gives `Write "kohm"`. The text is read as written. Its SI prefix is taken exactly as typed, because a
  prefix's case is its size (`m` is milli, `M` is mega; `p` is pico, `P` is peta). Its symbol is checked against
  every SI symbol, not only flo2-calc's own. Only when that reading is one unit, and the hint is that unit, is
  there a hint.
- **Otherwise there is no hint**, only the reason: units are case-sensitive, and flo2-calc does not guess a case.
  So `MV` (a megavolt as written) is never answered with `mV`, `PF` never with `pF`, and `PA` (a petaampere) never
  with `Pa`. `mS` (a millisiemens) is never answered with `ms`, and `Nm` with `nm`. `MM` and `Kg` get no hint either:
  `MM` reads as a megametre or a megamolar, and `K` is not a prefix.

flo2-calc 0.1.0 and 0.2.0 matched a spelling case-insensitively instead. They answered `mJ` with `Write "MJ"`, 10^9
too large (round 1 of the question set, q022). `tests/test_unit_hints.py` walks every SI prefix with every unit
symbol, in every case, and fails on any hint that changes a size, a kind or a typed prefix.

#### A bare `C` or `F`

`C` is the SI symbol for the coulomb and `F` for the farad, but people write them for degrees Celsius and
Fahrenheit. Read as SI, `25 C` would be 25 coulombs, silently. Read as a temperature, `0.1 F` would be wrong for
whoever meant farads. So flo2-calc reads a bare `C` or `F` as neither, anywhere in a unit (`25 C`, `2.5 C/W`), and
the refusal says what to write:

- a temperature: `degC` or `degF` (`25 degC`);
- a change of temperature: `delta_degC` or `delta_degF`, or `degC` inside a compound unit (`2.5 degC/W`);
- a charge: `coulomb` (or `Ah`, `mAh`);
- a capacitance: `farad` (or `mF`, `uF`, `nF`, `pF`).

The prefixed spellings (`mF`, `uF`, `nF`, `pF`) are unambiguous and stay. A record made by an earlier flo2-calc with a
bare `C` or `F` no longer re-runs: `rerun_record` says the unit cannot be read now, and why.

#### Temperatures

`K`, `degC` and `degF`. A value whose whole unit is `degC` or `degF` is a **temperature**: a reading on a scale whose
zero is not zero temperature. A **change** of temperature is `delta_degC`, `delta_degF`, `delta_K`, or a degree inside
a compound unit (`2.5 degC/W` is `2.5 K/W`). A value in `K` can be either, so each rule says which it is, and where
both are possible the operation is refused. A `K` KNOWN to be a change is written `delta_K` (exactly the size of `K`),
so it is never read as a temperature: a change converted to `K` (`18 delta_degF` is `10 delta_K`), a product that
comes out in `K` through a compound unit (`2.5 K/W * 4 W` is `10 delta_K`), and `K` minus a temperature. Round 3
(q036) found 0.6.1 giving a bare `10 K` for `18 delta_degF`, which then converted to `-263.15 degC`.

| Operation | Rule |
|---|---|
| `convert` | A temperature converts exactly between `degC`, `degF` and `K` (`36.6 degC` is `309.75 K`; `98.6 degF` is `37 degC`). A temperature is never turned into a change, nor a change into a temperature: a change converted to `K` is `delta_K`, and `delta_K` (or any change) converted to `degC` or `degF` is refused, naming `delta_degC` or `delta_degF`. |
| `add` | At most one temperature. Everything added to it is a change (`delta_degC`, `delta_degF` or `K`), and the sum is a temperature on its scale: `25 degC + 5 K` is `30 degC`. Two temperatures are refused: their sum means nothing. |
| `sub` | Temperature minus temperature is a change: `30 degC - 77 degF` is `5 delta_degC`. Temperature minus `delta_degC`, `delta_degF` or `delta_K` is a temperature. **Temperature minus `K` is refused**: `5 K` could be a change or a temperature, and the answers differ. `K` minus a temperature is a change, `delta_K`. |
| `eq` `ne` `lt` `le` `gt` `ge` `min` `max` | Temperatures, and `K` as a temperature, are compared exactly on one scale. `min` and `max` answer in the first one's unit. A temperature is never compared with a change. |
| `mul` `div` `pow` `neg` `abs` | Refused on a temperature in `degC` or `degF`. Convert it to `K` first, or work with a change. |

A product that comes out in degrees is a change: `1.2 W * 23.25 degC/W` is `27.9 delta_degC`, and adding it to
`40 degC` gives `67.9 degC`; `1.2 W * 23.25 K/W` is `27.9 delta_K`, the same change. A `K` typed as an input, or a
`K` scaled by a plain number, is still read by where it stands (`20 degC + 10 K` is `30 degC`, round 3's q096). A
record of version 6 or older was made before `delta_K`, and re-runs under the rules it was made with. A temperature refusal is of kind `offset_temperature`. `°C`, `℃`, `°F` and `℉` are
hinted to `degC` and `degF`.

#### Money

Each currency is its own dimension, named by its ISO 4217 code. flo2-calc knows the ten most traded in the BIS
Triennial Central Bank Survey of 2022: `USD` `EUR` `JPY` `GBP` `CNY` `AUD` `CAD` `CHF` `HKD` `SGD`.

- Amounts in one currency add, compare and scale exactly: `987.50 USD + 12.50 USD` is `1000 USD`.
- **flo2-calc holds no exchange rates.** `USD + EUR`, and `convert` from one currency to another, are refused as a
  unit mismatch naming both, and the reason asks for a rate.
- Only a rate the caller gives converts. It is an input whose unit holds two currencies, with its source, and it
  multiplies: `100 USD * 0.92 EUR/USD` is `92 EUR`. **A rate must have a source** (`"ECB reference rate,
  2026-10-02"`), even in `evaluate_graph`. A rate with none is a malformed call naming its `source` field.
- `$`, `¥` and `£` are each the sign of more than one currency, so they are refused, naming them. `€` is hinted to
  `EUR`.

### Exactness

Every value not labelled `rounded` is an exact fraction, and `+ - * /` and whole-number powers are exact. **"Exact"
means exact for these inputs.** A value follows exactly from the inputs as written, and is no more accurate than they
are. flo2-calc cannot know that `3.14159265` was typed for pi: it takes it as exactly that decimal. So a value built
from a truncated pi or e is the exact value of the given inputs, not of the math they stand for. Every answer with a
result says so in `exactness`, and every record says so in `arithmetic`. Use the `pi` and `e` operators instead: they
give the constants themselves, correctly rounded and labelled (Rounded values, below). When an answer holds a rounded
value, its `exactness` says that those values are not exact.

How a value is written:

- **A whole number is written as an integer, every digit**: `2^1000` is its 302 digits, never 30 of them beside a
  fraction ending in `/1`. Only a whole number of more than 40 digits whose significant digits number 40 or fewer
  keeps its short exact form (`1e+5000`).
- If its decimal ends within 40 significant digits, it is written exactly: `0.3`, `25.4 mm`, `1.602176634e-19 J`.
- Otherwise it is written rounded half-even to 30 significant digits, with its exact value beside it as a fraction:
  `"value": "4.44444444444444444444444444444 h", "exact": "40/9 h"`. That fraction is the exact value for these
  inputs.

#### A computed unit, shown simpler

An operation's value is shown in a simpler unit where one is exactly as large, so `mAh/mA` needs no convert to
become `h`. Only what is shown changes: the value, its dimension and its exact fraction do not, and
`"simplified_from"` names the unit it was computed in:

```json
{"node": "t", "value": "34.6153846153846153846153846154 h", "exact": "450/13 h", "simplified_from": "mAh/mA"}
```

The rule, deterministic and applied in this order (`units.simplify`):

0. A unit of one spelling (`mm`, `mm^2`, `1/s`, `degC`, `%`) is shown as it is.
1. A compound that measures nothing (`mm/m`) is shown as a plain number.
2. A compound exactly the size of one unit of the vocabulary that measures the same thing is shown in that unit, and
   the number does not change: `mAh/mA` is `h`, `V/mA` is `kohm`, `V*mA` is `mW`, `kPa*m^2` is `kN`, `uF*V^2` is `uJ`,
   `N*s^2/m` is `kg`. No two units of the vocabulary share a size, so this never has to choose.
3. Otherwise, a compound that measures what one of its own spellings measures is shown in the first such spelling:
   `um^2/m` (a length) in `um`. A degree inside a compound is a change of temperature, so it is shown as `delta_degC`
   (and a kelvin as `delta_K`).
4. Otherwise it is shown as it is: `m/s`, `J/kg`, `lbf*ft`.

A temperature reading and `%` are never chosen. A unit the graph chose itself is never re-chosen: an input's, a
`convert` target's, a `with_unit` unit's, an inverse trigonometric function's. A rounded value is re-shown only by
a power of ten, so its digits and bound stay as labelled.

Comparisons of exact values are exact. A value whose numerator or denominator passes the host's digits budget is not
carried: the calculation stops there, with its reason (Limits, above).

### Rounded values

A **rounded** value is not exact, and it never comes with an `exact` fraction. It comes with its label instead:

```json
{"node": "sd", "value": "0.230217288664426764419484158642 mm",
 "rounded": {"digits": 30, "correctly_rounded": true, "error_at_most": "5e-31 mm", "from": ["sd"]}}
```

| Field | Says |
|---|---|
| `digits` | the significant digits the value is written to, every one shown, trailing zeros kept (`sqrt(2)` at 40 digits ends `...078570`) |
| `correctly_rounded` | `true`: the value is the true result, rounded half-even to `digits`. `false`: it was computed from rounded values |
| `error_at_most` | a rigorous bound on how far the written value is from the true one, in the value's unit |
| `from` | the nodes whose rounding the value carries |

**How a correctly rounded value is found.**

1. Every function is evaluated with Arb, FLINT's ball arithmetic (through `python-flint`). Arb's contract is that each
   result is a ball, a midpoint and a radius, that **contains** the true value.
2. Both ends of that ball are rounded half-even to the digits asked for. If they round to the same decimal, the true
   value, which lies between them, rounds to it too: that decimal is the correctly rounded result. If they do not, the
   working precision is doubled and the test repeated (Ziv's method).
3. The test cannot finish when the true value is exactly a rounding tie, so every case where these functions are
   rational at rational arguments is answered exactly first: perfect squares and powers, `exp(0)`, `ln(1)`,
   `log10(10^k)`, trigonometry at the degree angles where it is rational, and the distributions at their centre.
   Everywhere else the value is proven irrational, so there is no tie and the loop ends.
4. For the distributions, irrationality is not proven in general, so the working precision is held to the host's
   digits budget. Past it the call stops with its reason (`exceeds_limits`), never with a guess.
5. `t_quantile` narrows a bracket around the quantile, each step decided by an Arb enclosure of the t tail, until both
   ends round to the same decimal. `normal_quantile` uses Arb's enclosure of `erfcinv`.

The tests check every rounded operator against mpmath, a different implementation, worked at 120 digits, on cases
built to lie within about 1e-15 of a unit in the 30th digit from a rounding tie, on both sides of it.

**Arithmetic on a rounded value** is labelled rounded too (`correctly_rounded: false`). It is the exact result on
the written decimals, rounded to the most digits among them. Its `error_at_most` grows by what the arguments' bounds
allow, rounded up to two significant digits. A function of a rounded value is the correctly rounded result at its
written decimal, with a bound taken from Arb's enclosure over the argument's whole error ball. `neg` and `abs` keep
the label as it is, and `0` times anything is exactly `0`.

**A comparison, `ceil`, `floor` or `round` of a rounded value** is answered only when the error bound decides it. Then
the answer is exact, and true of the true value. Otherwise it is refused, with kind `undecidable`: for example,
`sqrt(2) * sqrt(2) = 2` cannot be told from the rounded values, so neither "equal" nor "greater" is guessed. A
division by, or a domain edge within, a rounded value's bound is refused the same way.

### Shown back: the formula and the working

Every reply and every record shows the computation back, rendered from the graph that was evaluated and the values
it gave (`src/flo2_calc/formula.py`). Nothing is written separately, so it cannot drift from the answer. Each line is
plain text, with LaTeX beside it.

**The formula** is one equation per named node: every result, and every operation that is not folded into the one
that uses it. An operation used once, not a result, and at most 80 characters long is folded in, so a small graph reads
as one equation and a large one as named sub-expressions. **Every line ends with its value**, as every step of the
working does: `=` for an exact value (its exact fraction where its decimal does not end), `≈` for a rounded or float64
one, an array by its description (round 3 found 17 answers whose intermediate lines, `t_raw = C / I_avg`, carried
none). A record of version 4 to 6 ended only a result's line with its value, and re-runs that way.

**The working** is every node as a numbered step, in evaluation order: an input as given; an operation with its
arguments by name, then with their values written in, then its value; and its label (`given`, `exact`, or `rounded:`
with its digits and bound). A refused evaluation's working stops at the refused step, which says so.

```json
"formula": [{"node": "fits", "text": "fits = cavity - bend >= needed = true",
             "latex": "\\text{fits} = \\text{cavity} - \\text{bend} \\ge \\text{needed} = \\text{true}"}],
"working": [{"step": 1, "node": "cavity", "text": "cavity = 2 mm", "latex": "...", "label": "given"},
            ...,
            {"step": 3, "node": "margin", "text": "margin = cavity - bend = 2 mm - 1.4 mm = 0.6 mm", "latex": "...", "label": "exact"},
            ...]
```

**Large graphs stay readable in a reply.** A run of four or more steps of one shape (the same operation on the same
kinds of node, ids differing only in a trailing number) shows its first and last step and says how many lie between.
Past 40 entries, the first 29 and the last 10 are shown, with how many steps are left out and where they are. The
formula's lines are capped the same way. **The record holds every line and every step.** A value longer than 80
characters is not repeated in a line: the line gives its length, and `values` holds it.

### Arrays

`req:flo2-calc-computes-over-arrays`, `dec:idea-how-arrays-are-computed`. flo2-calc computes over vectors and grids
the way an agent would with numpy, and the agent still decides what to compute
(`rule:the-agent-reasons-flo2-calc-calculates`).

**An array is an input's value**, written as an object with ONE unit for the whole array:

```json
{"id": "t", "value": {"array": ["0", "2", "4", "6", "8", "10"], "unit": "s"}, "source": "frame times"}
{"id": "g", "value": {"array": [["1", "2", "3"], ["4", "5", "6"]], "unit": "mm"}, "source": "measured grid"}
{"id": "ok", "value": {"array": [true, false, true]}, "source": "checks"}
```

- One or two dimensions: a list of elements, or a list of rows of equal length.
- Each element is a number as text (`"2.5"`, `"1/3"`), a JSON integer, or, for the whole array, true/false. An element
  with a unit of its own (`"2 mm"`) is refused: the unit is given once, in `"unit"`. A JSON number with a fraction part
  is refused, as for a single value.

**A large array** enters one of two ways, and the record keeps it so that it re-runs and its content hash covers the
data:

- **Inline**, as above, up to whatever the call can carry. The record keeps it in its graph, element for element, so it
  re-runs anywhere. This is the way on flo2.io.
- **From a file, run locally:** `{"file": "data/grid.csv", "unit": "mm"}`, inside the folder flo2-calc was started with
  (`--root`). A `.csv` or `.txt` holds numbers separated by commas or spaces, a row per line (one row or one column is a
  1-D array; `#` starts a comment); a `.npy` holds numbers or true/false, its doubles taken exactly as given. The
  record's graph keeps the path and the sha256 of the file's bytes, so the content hash covers the data. Re-running
  reads the file again from `--root` and checks that sha256: a changed file is a difference, and a missing one leaves
  the record neither confirmed nor contradicted (`kind: "data_unavailable"`). With no `--root`, as hosted, a file is
  refused, and the reason says to give the array inline.

**Every operator works element by element** on arrays, with numpy's broadcasting, strict about units:

- Shapes combine when they are equal, when one side is a single value, when a row of n meets a grid of m x n, or when a
  column (m x 1) meets a row (n), which makes a grid. Any other pair is refused (`kind: "shape_mismatch"`).
- The single-value rules hold element by element: units that measure different things are refused, `1 m + 20 cm`
  converts to the first one's unit, a division by zero is refused naming the element, and so on.
- Comparisons give true/false arrays, and logic combines them: `(arr < 3) | (arr > 12)` is `lt`, `gt` and `or`.

**Operators only arrays have:**

| Family | Operators |
|---|---|
| reductions | `sum`, `product` (plain arrays), `mean`, `min` and `max` (with one array), `count_true`, `any`, `all`: each with `"axis"` 0 (down each column) or 1 (along each row) for a grid; `argmin`, `argmax` (1-D); `length`, the number of elements, exact (with `"axis"` 0, each column's length, the rows; with 1, each row's), so n comes from the data, never a typed count (round 3, q070) |
| statistics over data | `variance_sample`, `variance_population`, `sd_sample`, `sd_population` (1-D; sample divides by n - 1, population by n: named, never a default); `fit_slope`, `fit_intercept`, `fit_slope_se`, `fit_intercept_se`, `fit_residual_se` (args `[x, y]`: least squares y = intercept + slope x, and s = sqrt(SSR / (n - 2))) |
| transforms | `fft`, `ifft` (1-D), `fft2`, `ifft2` (2-D), numpy's convention: no scaling forward, 1/n back |
| complex values | `abs` (the modulus), `phase` (with `"unit"`: `"deg"` or `"rad"`), `real`, `imag`, `conj` |
| making and shaping arrays | `linspace` (`[start, stop, count]`, both ends included), `column` (1-D to n x 1), `transpose`, `element` (`[array, i]` or `[array, row, col]`, from 0) |

A function over an array (`sqrt`, `exp`, `ln`, `sin`, the distributions ...) works element by element, and a
`count_true` of several true/false values counts them. `to_number` turns a true/false array into an exact array of 1
and 0. `choose`, `factorial` and the binomial work element by element on exact arrays, by the rules for one value; a
float64 argument is refused.

**Exact or float64, and labelled.**

- **Exact.** An array of exact numbers stays exact through every rational operation (`add`, `sub`, `mul`, `div`,
  `neg`, `abs`, whole powers, `min`, `max`, `convert`, `ceil`, `floor`, `round`, the comparisons), through the
  reductions, and through the statistics that are rational: a mean, a variance, and a regression's slope and intercept.
  A standard deviation or a standard error is the square root of an exact number, so it is correctly rounded, the
  rounded class, as a single value's root is.
- **float64.** An FFT, a function of the rounded class over an array, an array of more elements than the host's
  `max_exact_elements` (65,536 on a laptop, 4,096 on flo2.io: Limits, above), and anything that mixes such a value in (a rounded value such as `pi` mixed into an array too) are computed in
  IEEE 754 double precision. Mixing exact and float64 gives float64. Every such value is labelled:

  ```json
  {"node": "spectrum", "value": "array 8 (complex, float64, V)",
   "array": {"shape": [8], "kind": "complex", "unit": "V", "sha256": "sha256:...", "values": ["36.0+0.0j", "..."]},
   "float64": {"error_at_most": "3.7e-13 V",
               "how": ["an exact value taken into float64: its exact rounding error to the nearest double",
                       "fft of 8 (numpy's pocketfft): every element within (B / (1 - B)) ||y||_2 of the exact DFT ..."],
               "from": ["spectrum"]}}
  ```

  `error_at_most` is a rigorous bound on every element's distance from the true value, `how` says what each part of it
  rests on, and `from` names where float64 entered. A comparison, `ceil`, `floor`, `round`, `argmin` or `argmax` of a
  float64 value is answered only where the bounds decide it, and refused (`kind: "undecidable"`) otherwise, as for a
  rounded value.

How each float64 bound is found:

| Where | How |
|---|---|
| an exact number taken into float64 | its exact rounding error to the nearest double (0 for a number a double holds exactly) |
| `+ - * /`, conversions | each operation's IEEE rounding (at most half a unit in the last place, u = 2^-53) and the arguments' bounds, carried through; every bound computed in float64 is inflated by (1 + 2^-40) so its own rounding never makes it too small |
| a function over an array | each element from Arb's rigorous enclosure over its argument's error ball (python-flint), rounded to the nearest double |
| `sum`, `mean` | `math.fsum`, which rounds the exact sum once, plus the elements' bounds |
| statistics and fits over float64 data | Arb ball arithmetic over every element's error ball, rounded once |
| complex products | the textbook product one IEEE operation at a time, within sqrt(5) u (Brent, Percival and Zimmermann, Math. Comp. 76, 2007) |
| `fft` of a power-of-two length (each axis of a grid) | twice Higham's bound for the radix-2 FFT: ||y_computed - y||_2 <= (t eta / (1 - t eta)) ||y||_2, t = log2 n, eta = mu + gamma_4 (sqrt 2 + mu), with mu = 8u for the twiddle factors (Higham, *Accuracy and Stability of Numerical Algorithms*, 2nd ed., SIAM 2002, Theorem 24.2); doubled for pocketfft's radix-4 passes |
| `fft` of any other length | computed for that transform: numpy's result checked against Arb's rigorous enclosure of the exact DFT of its input (FLINT's `acb_dft`) |

The FFT's bound is normwise, so every element of a spectrum carries the same bound; the inverse transform divides the
carried error's 2-norm by sqrt(n), so a round trip `ifft(fft(x))` comes back within about 1e-12 of x's scale.

**Shown back.** An array operation is a line of the formula and a step of the working like any other: `sum(f)` (with
LaTeX `\sum`), `fft2(field)` (`\mathcal{F}`), `g[1, 2]`; an array's value is named there by its shape and kind, and its
elements are in `values`, never written into a line.

**The same on every machine.** A record must re-run to the same values. So a function over an array goes through Arb
and rounds once, not through a platform's libm (whose last bits differ between CPUs); sums go through `math.fsum`;
complex products and moduli use the basic IEEE operations only. The FFT's values are numpy's own (pocketfft, the same
values an agent gets from `np.fft.fft`), so its last bits are those of the pinned numpy on the machine's architecture,
and `produced_by` names numpy.

**Written back,** an array is `{"value": a description, "array": {"shape", "kind", "unit", "sha256", "values"}}`:
every element as text (an exact element exactly, `"1/3"`; a double as the shortest text that reads back as the same
double; a complex one as `"re+imj"`) when it has at most 1,024 elements, else only its first 8, its least and
greatest, and its `sha256`. The sha256 is over the canonical text of every element, so a record of a large result
still covers its data, and re-running compares it. A float64 value of one element (a sum, a mean, a fit over float64
data) is written like a single value, with its `float64` label. A whole number is written in full. A computed array's
compound unit is shown simpler as a single value's is: `[3.3, 5] V / 20 mA` comes back as `[0.165, 0.25] kohm`, with
`"simplified_from": "V/mA"`; an exact array's elements take the exact factor, and a float64 array is shown simpler only
where the factor is 1, so a shown double is never one its bound does not cover.

**Two worked examples.** A straight-line fit with its standard error, in a few nodes instead of the eighty a value at a
time took:

```json
{"nodes": [
  {"id": "t", "value": {"array": ["0", "2", "4", "6", "8", "10"], "unit": "s"}, "source": "frame times"},
  {"id": "y", "value": {"array": ["0.0000", "0.0291", "0.0574", "0.0868", "0.1152", "0.1447"], "unit": "deg"},
   "source": "along-track angle, frames 1 to 6"},
  {"id": "slope", "op": "fit_slope", "args": ["t", "y"]},
  {"id": "slope_se", "op": "fit_slope_se", "args": ["t", "y"]}],
 "result": "slope"}
```

The slope is exact, `316/21875 deg/s` (0.0144457142857... deg/s), and its standard error is correctly rounded,
`0.0000374982992811619636... deg/s`. A small 2-D FFT, with the power at each frequency:

```json
{"nodes": [
  {"id": "g", "value": {"array": [["1", "2", "1", "0"], ["2", "4", "2", "0"], ["1", "2", "1", "0"], ["0", "0", "0", "0"]],
   "unit": "V"}, "source": "a 4 x 4 aperture"},
  {"id": "spectrum", "op": "fft2", "args": ["g"]},
  {"id": "power", "op": "abs", "args": ["spectrum"]},
  {"id": "dc", "op": "max", "args": ["power"]}]}
```

`power` is labelled float64 with its bound (Higham's, t = 4), and `dc` is `16.0 V`. The discretised integral
`sum(sum(f(x, y) * exp(...)))` is the same idea on a grid made from two axes: `linspace` each axis, `column` one of
them, and the element-wise product of a column and a row is the grid.

### Errors

flo2's helper contract fixes the split.

- **A refused computation** is a normal reply: `{"status": "refused", "refused": {"node", "op", "kind", "reason",
  "units"}}`, with no result and no record. For example: units that measure different things or two currencies
  (`unit_mismatch`), a temperature used where it has no meaning (`offset_temperature`), a division by zero, a logic
  operator given a number, an argument outside a function's domain (`out_of_domain`, such as `sqrt(-1)` or a
  probability of 1), a point where a function has no value (`undefined`, such as `tan(90 deg)`), a question a
  rounded or float64 value's error bound cannot decide (`undecidable`), arrays whose shapes do not combine
  (`shape_mismatch`), or a value past float64's range (`too_large`). An array's refusal names the element.
- **A limit passed** is a refused computation of its own kind, `exceeds_limits`, as above (Limits). It is still a
  normal reply. From `record_computation` it carries a not-yet-computed record.
- **A malformed call** is `isError: true`. Its text starts `Malformed call.` and names the field path, for example
  `graph.nodes[0].value: "notaunit" is not a unit flo2-calc knows`. It is raised as the SDK's `ToolError`, because
  python-sdk 2.x passes on a `ToolError`'s text and hides every other exception's.

## The computation record

One JSON object, defined by
[`src/flo2_calc/schemas/calc-record-7.schema.json`](src/flo2_calc/schemas/calc-record-7.schema.json) (JSON Schema
draft 2020-12). Version 7 (0.7.0, round 3) ends every line of `formula` with its value, allows round 3's operators
(`choose`, `factorial`, `binomial_pmf`, `binomial_cdf`, `binomial_sf`, `to_number`, `length`), and writes a `K` known to
be a change of temperature as `delta_K`. A record of version 6 or older re-runs under the writing and the rules it was
made with (`tests/data/temperature-and-formula.v6.calc.json`, made by 0.6.1, holds every path 0.7.0 changes and
reproduces byte for byte). Version 6 (0.6.1) added `max_exact_elements` to a record that holds an array (the host's exact-array
limit it was made with, which re-running uses), and to a host's limits. Version 5 (0.6.0) added arrays: an inline array or a data file's path and sha256 as an input's value,
the `array` and `float64` labels on values, the array operators and `axis`, `numpy` in `produced_by`, and
`max_array_bytes` among a host's limits. Versions 1 to 3 ([`calc-record-1.schema.json`](src/flo2_calc/schemas/calc-record-1.schema.json),
made by flo2-calc 0.1.0, [`calc-record-2.schema.json`](src/flo2_calc/schemas/calc-record-2.schema.json), made by
0.2.0 and 0.3.0, and [`calc-record-3.schema.json`](src/flo2_calc/schemas/calc-record-3.schema.json), made by 0.4.0)
still re-run. Version 2 added `status`, and a version 1 record is a computed one. Version 3 added the rounded class:
the `rounded` label on values and the result, the new operators and their `digits`, `places` and `mode`, and
`python_flint` in `produced_by`. Version 4 (0.5.0) adds `formula` and `working`, `results` for a graph that names
several, `simplified_from`, the round-2 operators with `kind` and with_unit's `source`, and the new writing of values
(whole numbers in full, every digit of a rounded value, simpler units). A not-yet-computed record of version 2 or 3
completes to the version 4 record a direct computation gives.

**Each version keeps its own writing.** A record of version 1 to 3 is re-run under the writing of its own version, so a
record 0.4.0 made still reproduces byte for byte (`tests/data/display.v3.calc.json` holds every value whose writing
0.5.0 changes). The formula's and the working's rendering are part of the format too: changing them is a new schema
version.

| Field | Holds |
|---|---|
| `record_format`, `schema_version` | `"flo2-calc computation record"`, `7` |
| `max_exact_elements` | a record that holds an array: the most elements an exact array had where it was made; re-running uses it |
| `status` | `"computed"`, or `"not_computed"` (below) |
| `name` | the record's name; its file is `<name>.calc.json` |
| `supports` | optional: what it supports, as free text or `{"design_node": "dec:...", "design"?: "..."}` |
| `arithmetic` | what exactness means in this record: exact for these inputs, and no more accurate than they are |
| `graph` | the graph exactly as read, every value as text |
| `inputs` | each input's `id`, `value`, `unit` and `source` (free text or `{"design_node"}`) |
| `values` | every node's value, in evaluation order, with `"exact"` (the exact value for these inputs) beside an exact value whose text is rounded, or the `"rounded"` label on a rounded value: which values were rounded, and at what precision; `"simplified_from"` where a computed unit is shown simpler; `"array"` (shape, kind, unit, sha256, the elements up to 1,024) on an array, `"float64"` (error_at_most, how, from) on a float64 value |
| `result` | `{"node", "value"}`, labelled the same way; or `results`, one each, when the graph names a list |
| `formula` | the computation as equations, plain text with LaTeX beside it, every line ending with its value |
| `working` | every step, numbered, with its formula, value and label |
| `produced_by` | `{"flo2_calc", "pint", "python_flint", "numpy"}` versions |
| `content_hash` | `sha256:` over the canonical JSON (keys sorted, no spaces, UTF-8) of every other field |

How a record behaves:

- **Deterministic.** There is no timestamp, and the file is written with sorted keys. The same graph gives the same
  file, byte for byte, wherever it is made. When it was made is the business of whatever keeps it: flo2 keeps every
  version, and git keeps every commit.
- **The hash is a seal, not a signature.** It catches a record edited by hand. `rerun_record` also re-evaluates the
  graph, and that catches a result that no longer follows from its inputs, even after someone recomputed the hash.
- **Linking is the agent's job.** The agent links a record to the decision it supports with the design tool's own
  tools, for example as an Artifact that documents the decision. flo2-calc never writes to reflow2.
- **Ready for stale-math checks.** An input that names a design quantity (`{"design_node": "con:..."}`) is what will
  let reflow2 flag a decision whose math rests on a changed input. That is a later step, done on reflow2's side.
- **A computed record carries no host limits**, so where it was made never changes it.

### Not yet computed

When `record_computation` is stopped at a limit, the record still comes back, with `"status": "not_computed"`. It
holds:

- the graph;
- the inputs, with their units and sources;
- the formula and the working, with no values (each step `not computed`);
- `stopped`: the limit it passed, its value, the least it needed when known, the node it reached, why, and how far it
  got;
- `limits_in_force`: the limits of the host that stopped it;
- `produced_by` and `content_hash`, as any record.

It holds no `values` and no `result`. It is returned as `calcfile:///<name>.calc.json`, and written under `--root`
when `output_path` asks. So the equations travel, and the machine is chosen later.

**Completing it.** On any machine with more room, a laptop, a workstation or a cluster node, pass the record to
`record_computation` as `record`, in place of `graph` and `name`:

- flo2-calc checks its seal first. A record whose content hash does not match, or whose inputs no longer follow from
  its graph, is not completed: `kind: "record_changed"`.
- Then it evaluates the graph under its own limits. The completed record keeps the same name, supports, graph and
  inputs, and adds the values, the result and the hash.
- It is **the record a direct computation of that graph gives, byte for byte**, with the same hash rules. Nothing in it
  says where it was first tried.
- Where there is still not enough room, the reply is a new not-yet-computed record, with this host's limits.
- Run locally with `output_path`, the completed record replaces the not-yet-computed file of the same calculation.
  That file must be intact and have the same name, supports, graph and inputs. Nothing else is ever written over.

**An FFT on another processor.** An FFT's values are numpy's own, so their last bits can differ between processors
(another architecture may fuse a multiply and an add). `rerun_record` accepts a float64 value that rests on an FFT (the
FFT's result, and what was computed from it) when every element lies within the bound the record states for it, and
says so as its own outcome, never as identical: `"reproduces": "within_bound"`, `"outcome": "reproduced_within_bound"`,
each such value in `within_bound`, and `largest_difference` naming the node, the difference and its bound. Every exact
value and every other float64 value must still reproduce byte for byte (`"reproduces": true`, `"outcome":
"reproduced"`), and a difference beyond a bound, or anywhere else, is `"reproduces": false` with each difference and
why. An FFT result of more than 1,024 elements is kept only as its sha256, so a difference in it cannot be weighed
against its bound, and the answer says that.

**Checking it.** `rerun_record` on a not-yet-computed record says plainly that it has no result yet (`"status":
"not_computed"`, `"reproduces": null`). It checks the seal, says what the record needs (for example, "max_digits of
at least 4,999 digits"), and says whether this flo2-calc has the room to complete it. A computed record that passes
the limits of the host re-running it is neither confirmed nor contradicted: `"status": "refused"`, naming the limit.

## Generic math only

A domain's formulas stay with the helper that owns the domain: metal weight, ring sizes and stone sizes belong to
flo2-cad, and a building's quantities to flo2-ifc. flo2-calc does generic arithmetic, logic and comparison, the
standard functions, trigonometry and the common distributions, with units. Where a decision needs a domain number, the owning helper produces it, and flo2-calc takes it as an input with
its source.

## What is pinned and why

Every dependency is pinned exactly in `pyproject.toml`. That list is what the image and the plugin install.

| Pin | Why |
|---|---|
| `mcp==2.3.0` | The latest official MCP Python SDK (`dec:evaluator-language`). |
| `pint==0.26.1` | Gives what each unit measures and its exact factor to SI base units, loaded with exact fractions. |
| `flexparser==0.4`, `flexcache==0.3` | pint parses and caches its definitions with these, so they decide what a unit is. A record must re-run to the same result. |
| `jsonschema==4.26.0` | `rerun_record` checks a record against its schema first. |
| `python-flint==0.9.0` | Arb ball arithmetic, the rigorous enclosures every rounded value is decided from. A correctly rounded result is the same whichever version computes it; the bound on a value computed from rounded values can move in its last digit, which is why `produced_by` names the version. It also bounds every float64 function over an array, and checks every FFT whose length is not a power of two. |
| `numpy==2.5.3` | Arrays: the FFT (pocketfft) and float64 storage and arithmetic. An FFT's last bits are pocketfft's, so `produced_by` names the version. About 69 MB of the image. |
| `pytest==9.1.1`, `mpmath==1.4.1` (the `test` extra) | The tests, and their independent oracle for every rounded value. The package never imports mpmath. |
| `setuptools==84.0.0` (build) | The build backend. |

Transitive dependencies (pydantic, anyio and the rest) come in at whatever versions the pins accept. `pip freeze
--all`, in the image build and in CI, shows what was installed.

## Measurements

Measured on 2026-10-04 with `python3 tools/measure.py --cap 128m` (and `--cap 256m`). The image ran under
flo2-tool-sandbox's flags:

- no network, a read-only root and a 64 MB `/tmp`;
- user 65534, no capabilities and no new privileges;
- one CPU, 64 processes, and the memory cap with no swap.

| What | Measured |
|---|---|
| Peak memory of one session (the cgroup's `memory.peak`) | 105.4 MiB under a 128 MiB cap, 98.2 MiB under 256 MiB (a rehearsal of the same code measured 102.5 and 99.8: runs differ by a few MiB) |
| The session | 34 calls: three each of a 500-node graph, its record, the record's re-run, and a refused mixed-unit sum; three each of a 484-node graph of rounded operators at 1,000 digits each (sqrt, exp, ln, sin, atan, deg-rad, normal_quantile, chi2_sf, t_quantile), its record and the record's re-run; arrays (below); then the runaway calls below, and one more call that answers |
| Arrays, one call each, under 128m | a 256 x 256 grid built from two axes, its Gaussian field (`exp` over 65,536 elements), discretised integral, 2-D FFT, modulus (`abs`) and peak: 1.5 s; the same recorded and re-run: 3.0 s; a 250 x 250 grid (its FFT checked against Arb's rigorous DFT): 2.7 s; a fit with standard errors over 4,000 exact points: 0.3 s, and over 20,000 points (float64): 0.9 s |
| Runaway calls, under the image's own limits (flo2.io's profile) | a 20,000-digit power to the 1000th, 30 squarings, `exp(1e5)` and `normal_sf(1e6)`: each stopped at `max_digits`. A 100,000 x 100,000 grid: stopped at `max_array_bytes` before it was made. The heaviest graph the profile allows (500 nodes of about 1,900 digits each), sent whole: answered; recorded: stopped at `max_reply_bytes` with a not-yet-computed record, since its record, with the formula and all 500 working steps beside two copies of every value, passes 2 MiB (0.4.0's fitted) |
| Time for the whole session, one CPU, cold start included | 74 s under 128m and under 256m (the 1,000-digit rounded graphs take about 8 s a call; t_quantile is most of it) |
| Image size | 278 MB (`python:3.12-slim` and the venv; python-flint adds about 26 MB, numpy about 69 MB) |

Measured on 2026-10-04 with flo2-calc 0.6.0. 0.7.0 (round 3's fixes) ran the same 34-call session under the 128 MiB
cap the same day and peaked at 100.2 MiB, every runaway call stopped at its limit and the container alive after: its
changes (new operators, the formula's values, delta_K) cost no measurable memory. 0.5.0 peaked at 91.3 MiB and 0.4.0 at 78.2 MiB in their 27-call sessions; numpy, loaded and
working on the arrays above, costs about 14 MiB more than 0.5.0. A cap of **128m** is still above the peak, with 22 MiB to spare,
and the array budget (16 MiB in the image) keeps a call's arrays inside it. CI runs the image under 128m, and asks it
every limit's questions there (`tests/test_limits.py`, `tests/test_pending_record.py`) and the arrays' questions
(`tests/test_arrays_server.py`).

## Working on it

```sh
uv venv -p 3.12 /tmp/flo2-calc-venv
uv pip install --python /tmp/flo2-calc-venv/bin/python -e '.[test]'
/tmp/flo2-calc-venv/bin/python -m pytest -v
```

- `tests/test_evaluator.py`, `tests/test_units.py`: exactness, every operator, every unit, money, and every refusal;
  counting, several results, whole numbers, units for empirical formulas, furlong and fortnight, and the
  simplification rule (it never changes a dimension or a size, over every pair of units).
- `tests/test_decibels.py`: dB as its own kind, the kind always stated, power levels, against mpmath.
- `tests/test_formula.py`: the formula and the working, in plain text and LaTeX; large graphs; a refused one; the record
  holds every step, and a shown working that no longer follows from its graph does not reproduce.
- `tests/test_unit_hints.py`: every SI prefix with every unit symbol, in every case, through the hint. No hint may
  change a size, a kind or a typed prefix. It also holds round 1's list, one by one.
- `tests/test_temperature.py`: `degC` and `degF`, converted exactly; a difference of temperatures stays correct, and
  stays a difference through `convert`, products and subtraction (`delta_K`), on every path, single values and arrays.
- `tests/test_rounded.py`, with `tests/oracle.py`: every rounded operator against mpmath at 120 digits, on hard cases
  next to a rounding tie, both sides; exact results that stay exact; the unit rules and domains of every new operator;
  the labels in the record; and the limits.
- `tests/test_record.py`: the record is deterministic and fits its schema; it re-runs; tampering is caught; several
  results; records of versions 1 to 3 and 6 reproduce under their own writing (and version 6's under its own
  temperature rules); round 3's operators in a version 7 record.
- `tests/test_server.py`: the four tools over a real MCP client session. Every refusal's reason is read on the
  client's side. The served skill (prompt and resource) is read there too, and matches its file.
- `tests/test_conformance.py`: flo2's helper contract, asked in raw JSON-RPC as flo2's plug asks it. It also holds
  the four tool names and their read/write classes to the ones flo2's door holds.
- `tests/test_limits.py`: each limit trips with its reason; a huge power is refused before it stalls; the server
  stays alive after every stop.
- `tests/test_pending_record.py`: a not-yet-computed record made under low limits and completed under higher ones
  is the direct computation's record, byte for byte. Tampering with one is caught, and a version 1 record still
  re-runs (`tests/data/`, made by flo2-calc 0.1.0).
- `tests/test_arrays.py`: arrays against two oracles, numpy (the values an agent would get) and mpmath at 50 digits (the
  true values), so every float64 bound is shown to hold: element-wise operations and functions, broadcasting and units,
  reductions and the discretised integral, variance and the regression (exact slope on rational data), the FFT and its
  inverse at lengths from 1 to 256 (powers of two and not, primes among them) and in 2-D, the limits, and records with
  arrays (re-run, a large result's sha256, a data file's sha256, completion of a not-yet-computed record).
- `tests/test_arrays_server.py`: arrays over a real MCP session, and in CI's image job under 128m: the regression in a
  few nodes, a 256 x 256 grid's integral and 2-D FFT, a record re-run, the array budget, a data file.
- `tests/test_standalone.py`: the server alone, with a clean environment. It checks the root's edges, and that the
  package imports nothing of flo2 or reflow2.
- `tests/test_manifests.py`, `tests/test_dependency_currency.py`: both plugin formats, the skill (and that it and the
  server's instructions say an empirical formula's constants come from the person or a cited document, never memory),
  and the dependency check.

Set `FLO2_CALC_SERVER` to a command line, such as a confined `docker run` of the image, to ask the image the
conformance, server, limit and not-yet-computed questions instead (CI's `image` job does).

The dependency report, live (it needs the network): `python3 tools/dependency_currency.py`.
`.github/workflows/dependencies.yml` runs it on the first of every month.

## What flo2 needs to host it

flo2-calc meets flo2's helper contract (MUST tier) and OUR STANDARD. To offer it on flo2.io, flo2 needs:

1. **The image, pinned.** `ops/images/flo2-calc/COMMIT` is the commit flo2 runs. `ops/flo2-tool-sandbox` names it:
   `[calc]=flo2-calc:<commit>`, with a memory cap of `128m`. `ops/flo2-tool-sandbox-install` builds it from this
   repository's `Dockerfile`.
2. **A door for the `calc` helper** (`calc-door.ts`, beside `cad-door.ts`), with a fail-closed allow-list:
   - `evaluate_graph`, `add_node` and `rerun_record` classed read;
   - `record_computation` classed write.

   The door's file rule keeps `calcfile:///<name>.calc.json` (`application/json`, at most 2 MB a reply) as a new
   version of that file in the person's design. The resource comes as `text`, not `blob`.

   The four names and classes are unchanged by the limits, the not-yet-computed record and arrays (0.6.0: arrays are
   new value shapes and new `op` values inside a graph). `record_computation`
   gained an optional `record` argument, and its `graph` and `name` became optional; every call that worked before
   still works. A not-yet-computed record is a file like any other, kept as a version of
   `calcfile:///<name>.calc.json`. Its completion, from the same name, is the next version of the same file.
3. **The helper's description**, its served skill (`skills/support-a-decision-with-math/SKILL.md`), and a row in
   `HELPERS`. 0.3.0 changed the skill's text (exact for these inputs, units, temperatures, money), 0.4.0 again (the
   rounded operators and their labels), and 0.5.0 again (decibels, counting, several results, units for empirical
   formulas, the formula and working shown back). The four tools' names, classes and top-level arguments are
   unchanged by 0.5.0: everything new is inside a graph (new `op` values, node fields `kind` and `source`, `result` as
   a list) or inside a reply (`formula`, `working`, `results`). The record is schema version 4, still one `calcfile`
   per record. **0.5.0 also offers an MCP prompt and a resource** (the skill, `initialize` now lists `prompts` and
   `resources` beside `tools`). They are not tools, so the door's allow-list of four is untouched; the door may ignore
   them, since hosted on flo2.io the skill is served by flo2 itself. The image's size is unchanged (209 MB), and its
   measured peak, 91 MiB, still fits the 128m cap. 0.6.0 changes the skill's text again (arrays, statistics over data, the FFT); an array is a new shape of an input's value and its operators new `op` values. The record becomes schema version 5, still one `calcfile` per record (an array is kept inline in it). The image is about 69 MB larger (numpy), its limits gain `FLO2_CALC_MAX_ARRAY_BYTES=16777216`, and its measured peak still fits the 128m cap (Measurements). 0.6.1 makes the exact-array limit the host's (`FLO2_CALC_MAX_EXACT_ELEMENTS=4096` in the image, the value 0.6.0 had fixed, so the image computes as before), the record schema version 6, and `rerun_record`'s answer gains `outcome` and, for an FFT re-run on another processor, `"reproduces": "within_bound"`. 0.7.0 (round 3's fixes) changes the skill's text again (an empirical formula's constants come from the person or a cited document, never the agent's memory; ambiguous expressions; troy weight; the new operators) and the server's instructions; adds `op` values inside a graph (`choose`, `factorial`, `binomial_pmf`, `binomial_cdf`, `binomial_sf`, `to_number`, `length`) and the units `ozt`, `dwt`, `grain`, `week` and `delta_K`; and makes the record schema version 7. The four tools, their classes and their top-level arguments are unchanged; the image's limits are unchanged.
4. **A row in the conformance check.**
   - One call that answers: `evaluate_graph` on `0.1 + 0.2`.
   - One call that fails: an input `"2 notaunit"`, whose reason starts `Malformed call. graph.nodes[0].value`.
     Before 0.5.0 the example was `"2 furlong"`, which is a unit now: **flo2's conformance row must change with this
     release**.
   - The door strips the SDK's `Error executing tool <name>:` preamble, as `model-door.ts` does.

No `--root` is passed when hosted, so flo2-calc writes no file and reads no data file: an array comes inline.
`rerun_record` takes the record's content. Reading a kept record by path is not offered. **No limit needs setting:** the image carries flo2.io's profile (Limits, above).
A broker that wants others passes `-e FLO2_CALC_DEADLINE=...` and the like. Its call deadline must stay above
flo2-calc's own, so the refusal arrives before the gateway gives up.

## Licence

Apache-2.0 ([LICENSE](LICENSE)).
