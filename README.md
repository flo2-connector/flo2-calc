# flo2-calc: exact math and logic for the decisions in a design

flo2-calc is an MCP server that does a design's arithmetic and logic, so that a critical decision can carry the
computation that supports it: the operators, the inputs with their units and where each came from, and the result.
The math is done here, exactly, not by the model.

- **Exact.** Every number is an exact fraction. `0.1 + 0.2` is `0.3`, and every unit conversion is exact.
- **Or correctly rounded, and labelled so.** pi, e, roots, `exp`, `ln`, `log10`, non-whole powers, trigonometry,
  deg-rad conversion and the normal, chi-square and Student-t distributions are irrational in general. Their results
  are **correctly rounded** to 30 significant digits (or as many as a node asks, up to 1000), labelled `rounded` with
  a rigorous `error_at_most`, and never called exact. Where the result is rational it stays exact: `sqrt(9/4)` is
  `3/2`, and `sin(30 deg)` is `1/2`.
- **Units, checked.** A value can carry a unit, spelled as reflow2 designs spell it (`mm`, `g`, `V`, `mA`, ...).
  Units that measure different things are refused, naming the operation and both units, never stripped. A unit
  flo2-calc does not know is refused, never guessed.
- **Correct or refused.** A computation that cannot be done says which node, which operation and why. It never
  returns a number it cannot stand behind.
- **Re-runnable.** A computation comes back as a **computation record**, a `.calc.json` file a decision can cite.
  Anyone can re-run it and get the same values, and an edited record is caught.
- **Never runs away.** Each host sets limits at start-up: a deadline per call, and a budget for the digits of any
  exact number and for the reply. A calculation past one is stopped cleanly, with its reason. A recorded one comes
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
  peak is 71 MiB (Measurements, below).
- **Reply, 8 MiB on a laptop.** That is room for a 500-node graph of large exact values. A record larger than the
  budget is also refused as input, so a host never takes in a record it could not have made.
- **Reply, 2 MiB on flo2.io.** This is the most flo2's door keeps of a `calcfile` in one reply, well under its
  gateway's 16 MiB reply cap.

The image sets flo2.io's profile (`ENV` in the `Dockerfile`). Run elsewhere, pass your own, for example
`docker run -e FLO2_CALC_MAX_DIGITS=20000 ...`. A workstation raises them all. A setting flo2-calc cannot use, such as
`--max-digits 5`, stops it at start-up with the reason, and is never silently replaced. The limits in force are in
the server's instructions, and in every refusal they cause.

How they are kept (`src/flo2_calc/limits.py`):

- **While running.** The deadline is checked before every node and after every step of an operation with many
  arguments. Every input, partial sum, partial product and value is held to the digits budget. The reply is measured
  as it is written, so a reply too large to send is never built whole.
- **A power is sized BEFORE it is computed.** A huge power stalls inside a single Python operation, which nothing can
  interrupt. For example, a 20,000-digit number to the power 1000 takes about 44 s on one CPU. flo2-calc bounds
  the power's size from its operands first, and refuses one that would pass the budget, at once.
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
   "reason": "pow at node \"z\": the power's numerator would have at least 19,999,167 digits, past this host's budget of 20,000 digits for any exact number, so it was not computed ...",
   "limit": {"name": "max_digits", "value": 20000, "needed_at_least": 19999167, "setting": "--max-digits or FLO2_CALC_MAX_DIGITS"},
   "reached": {"nodes_done": 4, "nodes": 5, "largest_digits": 20000, "elapsed": "0.002 s"},
   "limits": {"deadline": "45 s", "max_digits": 20000, "max_reply_bytes": 8388608}}
  ```

## Tools

| Tool | Class | Arguments | Returns |
|---|---|---|---|
| `evaluate_graph` | read | `graph` | `status` (`ok` or `refused`), the `result`, every node's value in evaluation order |
| `add_node` | read | `node`, `graph?` (the graph so far) | the new node's value, every value so far, and the grown `graph` to pass next time |
| `record_computation` | write | `graph`, `name`, `supports?`, `output_path?`; or, to complete one, a not-yet-computed `record` | the result, the record's file name, sha256 and content hash, and the record as `calcfile:///<name>.calc.json`. Stopped at a limit: the refusal and a not-yet-computed record |
| `rerun_record` | read | `record` (the object or its text) or `path` | `reproduces`, whether the content hash matches, and every difference. For a not-yet-computed record: that it has no result yet, and what it needs |

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
- **Its `source`** says where the value came from: free text, or `{"design_node": "<id>"}` naming a node in a reflow2
  design (add `"design": "<id>"` for another design). flo2-calc records it and never resolves it. A record needs a
  source on every input.
- **An operation** has `op` and `args`, the ids of the nodes it takes. Nodes may be listed in any order. A cycle, a
  missing id or an unknown operator is a malformed call naming the field.
- `result` names the result node, and defaults to the last node listed.

**Operators** (set operations come later):

| Family | Operators |
|---|---|
| arithmetic | `add`, `sub`, `mul`, `div`, `neg`, `abs`, `pow`, `min`, `max`, `convert` (with `"unit"`) |
| functions | `sqrt`, `exp`, `ln`, `log10` |
| constants | `pi`, `e` (no `args`) |
| trigonometry | `sin`, `cos`, `tan` (of an angle in `deg` or `rad`); `asin`, `acos`, `atan`, `atan2` (with `"unit"`: `"deg"` or `"rad"`, the unit of the angle they give) |
| rounding | `ceil`, `floor`, `round` (with `"places"`, and for `round` a `"mode"`) |
| statistics | `normal_cdf`, `normal_sf`, `normal_quantile`, `chi2_sf`, `t_quantile` |
| logic | `and`, `or`, `not`, `nand`, `nor`, `xor` |
| comparison | `eq`, `ne`, `lt`, `le`, `gt`, `ge` |

- **`pow`** is exact for a whole exponent, as before. A non-whole exponent (`"1/3"`, `"0.44"`) needs a base of 0 or
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
- **`digits`**: any rounded operator may take `"digits"`, from 1 to 1000 significant digits; 30 when left out.

### Units

Spelled as reflow2 spells them, one spelling each. The vocabulary is in `src/flo2_calc/units.py`:

| Measures | Units |
|---|---|
| length | `m` `km` `cm` `mm` `um` `nm` `in` `ft` |
| mass | `kg` `g` `mg` `ug` `t` `ct` `lb` `oz` |
| time | `s` `ms` `us` `ns` `min` `h` `d` |
| electrical | `A` `kA` `mA` `uA`, `V` `kV` `mV` `uV`, `ohm` `kohm` `Mohm`, `F` `mF` `uF` `nF` `pF`, `H` `mH` `uH`, `C` `Ah` `mAh` |
| power, energy | `W` `MW` `kW` `mW` `uW`, `J` `kJ` `MJ` `Wh` `mWh` `kWh` `eV` |
| frequency, force, pressure | `Hz` `kHz` `MHz` `GHz`, `N` `kN`, `Pa` `kPa` `MPa` `GPa` `bar` |
| other | `K` (absolute only), `L` `mL`, `deg` `rad`, `%` |

- **Compound units:** `*` between units, `^n` for a power, and one `/` with a bracketed product after it, for
  example `mm^2`, `m/s^2`, `N*m`, `kg/(m*s^2)`, `1/s`.
- **Mixed units** convert exactly to the first operand's unit: `1 m + 20 cm` is `1.2 m`, and `2 m * 3 mm` is
  `0.006 m^2`. `convert` changes a unit: `3.3 V * 20 mA`, converted to `mW`, is `66 mW`.
- **Percent** is a plain ratio: `200 g * 5 %` is `10 g`, and `10 % * 2` is `20 %`.
- **Refused:**
  - units that measure different things (`2 mm + 3 g`);
  - a unit against a plain number (`2 mm + 3`);
  - an unknown spelling. A near miss names the spelling to use: `MM` gives "write mm", and `µm` gives "write um".
- **Angles** are their own dimension, so `30 deg + 1` is refused. `deg` and `rad` are never mixed in one operation,
  because their ratio is pi/180, which no fraction holds exactly. `convert` turns one into the other as a correctly
  rounded value, labelled rounded.
- **Temperatures** are kelvin only. `°C` has an offset and does not add or multiply like a unit.

### Exactness

An exact value is an exact fraction, and `+ - * /` and whole-number powers are exact. How it is written:

- If its decimal ends within 40 significant digits, it is written exactly: `0.3`, `25.4 mm`, `1.602176634e-19 J`.
- Otherwise it is written rounded half-even to 30 significant digits, with its exact value beside it as a fraction:
  `"value": "4.44444444444444444444444444444 h", "exact": "40/9 h"`.

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
| `digits` | the significant digits the value is written to |
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

### Errors

flo2's helper contract fixes the split.

- **A refused computation** is a normal reply: `{"status": "refused", "refused": {"node", "op", "kind", "reason",
  "units"}}`, with no result and no record. For example: units that measure different things (`unit_mismatch`), a
  division by zero, a logic operator given a number, an argument outside a function's domain (`out_of_domain`, such
  as `sqrt(-1)` or a probability of 1), a point where a function has no value (`undefined`, such as `tan(90 deg)`),
  or a question a rounded value's error bound cannot decide (`undecidable`).
- **A limit passed** is a refused computation of its own kind, `exceeds_limits`, as above (Limits). It is still a
  normal reply. From `record_computation` it carries a not-yet-computed record.
- **A malformed call** is `isError: true`. Its text starts `Malformed call.` and names the field path, for example
  `graph.nodes[0].value: "furlong" is not a unit flo2-calc knows`. It is raised as the SDK's `ToolError`, because
  python-sdk 2.x passes on a `ToolError`'s text and hides every other exception's.

## The computation record

One JSON object, defined by
[`src/flo2_calc/schemas/calc-record-3.schema.json`](src/flo2_calc/schemas/calc-record-3.schema.json) (JSON Schema
draft 2020-12). Versions 1 and 2 ([`calc-record-1.schema.json`](src/flo2_calc/schemas/calc-record-1.schema.json),
made by flo2-calc 0.1.0, and [`calc-record-2.schema.json`](src/flo2_calc/schemas/calc-record-2.schema.json), made by
0.2.0) still re-run. Version 2 added `status`, and a version 1 record is a computed one. Version 3 adds the rounded
class: the `rounded` label on values and the result, the new operators and their `digits`, `places` and `mode`, and
`python_flint` in `produced_by`. A version 2 not-yet-computed record completes to the version 3 record a direct
computation gives.

| Field | Holds |
|---|---|
| `record_format`, `schema_version` | `"flo2-calc computation record"`, `3` |
| `status` | `"computed"`, or `"not_computed"` (below) |
| `name` | the record's name; its file is `<name>.calc.json` |
| `supports` | optional: what it supports, as free text or `{"design_node": "dec:...", "design"?: "..."}` |
| `arithmetic` | what exactness means in this record |
| `graph` | the graph exactly as read, every value as text |
| `inputs` | each input's `id`, `value`, `unit` and `source` (free text or `{"design_node"}`) |
| `values` | every node's value, in evaluation order, with `"exact"` beside an exact value whose text is rounded, or the `"rounded"` label on a rounded value: which values were rounded, and at what precision |
| `result` | `{"node", "value"}`, labelled the same way |
| `produced_by` | `{"flo2_calc", "pint", "python_flint"}` versions |
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
| `python-flint==0.9.0` | Arb ball arithmetic, the rigorous enclosures every rounded value is decided from. A correctly rounded result is the same whichever version computes it; the bound on a value computed from rounded values can move in its last digit, which is why `produced_by` names the version. |
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
| Peak memory of one session (the cgroup's `memory.peak`) | 71.3 MiB under a 128 MiB cap, 71.1 MiB under 256 MiB |
| The session | 16 calls: three each of a 500-node graph, its record, the record's re-run, and a refused mixed-unit sum; then the runaway calls below, and one more call that answers |
| Runaway calls, under the image's own limits (flo2.io's profile) | a 20,000-digit power to the 1000th, and 30 squarings: each stopped at `max_digits`. The heaviest graph the profile allows (500 nodes of about 1,900 digits each), sent whole and recorded: both answered, the record within 2 MiB |
| Time for the first 12 calls, one CPU, cold start included | 4.9 s |
| Image size | 182 MB (`python:3.12-slim` and the venv) |

Measured on 2026-10-04 with flo2-calc 0.2.0; 0.1.0 peaked at 62.4 MiB in the first 12 calls. A cap of **128m** is
still about twice the peak, the same rule flo2 used for flo2-cad's cap. CI runs the image under 128m, and asks it
every limit's questions there (`tests/test_limits.py`, `tests/test_pending_record.py`).

## Working on it

```sh
uv venv -p 3.12 /tmp/flo2-calc-venv
uv pip install --python /tmp/flo2-calc-venv/bin/python -e '.[test]'
/tmp/flo2-calc-venv/bin/python -m pytest -v
```

- `tests/test_evaluator.py`, `tests/test_units.py`: exactness, every operator, every unit, and every refusal.
- `tests/test_rounded.py`, with `tests/oracle.py`: every rounded operator against mpmath at 120 digits, on hard cases
  next to a rounding tie, both sides; exact results that stay exact; the unit rules and domains of every new operator;
  the labels in the record; and the limits.
- `tests/test_record.py`: the record is deterministic and fits its schema; it re-runs; tampering is caught.
- `tests/test_server.py`: the four tools over a real MCP client session. Every refusal's reason is read on the
  client's side.
- `tests/test_conformance.py`: flo2's helper contract, asked in raw JSON-RPC as flo2's plug asks it. It also holds
  the four tool names and their read/write classes to the ones flo2's door holds.
- `tests/test_limits.py`: each limit trips with its reason; a huge power is refused before it stalls; the server
  stays alive after every stop.
- `tests/test_pending_record.py`: a not-yet-computed record made under low limits and completed under higher ones
  is the direct computation's record, byte for byte. Tampering with one is caught, and a version 1 record still
  re-runs (`tests/data/`, made by flo2-calc 0.1.0).
- `tests/test_standalone.py`: the server alone, with a clean environment. It checks the root's edges, and that the
  package imports nothing of flo2 or reflow2.
- `tests/test_manifests.py`, `tests/test_dependency_currency.py`: both plugin formats, the skill, and the dependency
  check.

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

   The four names and classes are unchanged by the limits and the not-yet-computed record. `record_computation`
   gained an optional `record` argument, and its `graph` and `name` became optional; every call that worked before
   still works. A not-yet-computed record is a file like any other, kept as a version of
   `calcfile:///<name>.calc.json`. Its completion, from the same name, is the next version of the same file.
3. **The helper's description**, its served skill (`skills/support-a-decision-with-math/SKILL.md`, unchanged), and a
   row in `HELPERS`.
4. **A row in the conformance check.**
   - One call that answers: `evaluate_graph` on `0.1 + 0.2`.
   - One call that fails: an input `"2 furlong"`, whose reason starts `Malformed call. graph.nodes[0].value`.
   - The door strips the SDK's `Error executing tool <name>:` preamble, as `model-door.ts` does.

No `--root` is passed when hosted, so flo2-calc writes no file. `rerun_record` takes the record's content. Reading a
kept record by path is not offered. **No limit needs setting:** the image carries flo2.io's profile (Limits, above).
A broker that wants others passes `-e FLO2_CALC_DEADLINE=...` and the like. Its call deadline must stay above
flo2-calc's own, so the refusal arrives before the gateway gives up.

## Licence

Apache-2.0 ([LICENSE](LICENSE)).
