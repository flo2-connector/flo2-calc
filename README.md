# flo2-calc: exact math and logic for the decisions in a design

flo2-calc is an MCP server that does a design's arithmetic and logic, so that a critical decision can carry the
computation that supports it: the operators, the inputs with their units and where each came from, and the result.
The math is done here, exactly, not by the model.

- **Exact.** Every number is an exact fraction. `0.1 + 0.2` is `0.3`, and every unit conversion is exact.
- **Units, checked.** A value can carry a unit, spelled as reflow2 designs spell it (`mm`, `g`, `V`, `mA`, ...).
  Units that measure different things are refused, naming the operation and both units, never stripped. A unit
  flo2-calc does not know is refused, never guessed.
- **Correct or refused.** A computation that cannot be done says which node, which operation and why. It never
  returns a number it cannot stand behind.
- **Re-runnable.** A computation comes back as a **computation record**, a `.calc.json` file a decision can cite.
  Anyone can re-run it and get the same values, and an edited record is caught.

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

## Tools

| Tool | Class | Arguments | Returns |
|---|---|---|---|
| `evaluate_graph` | read | `graph` | `status` (`ok` or `refused`), the `result`, every node's value in evaluation order |
| `add_node` | read | `node`, `graph?` (the graph so far) | the new node's value, every value so far, and the grown `graph` to pass next time |
| `record_computation` | write | `graph`, `name`, `supports?`, `output_path?` | the result, the record's file name, sha256 and content hash, and the record as `calcfile:///<name>.calc.json` |
| `rerun_record` | read | `record` (the object or its text) or `path` | `reproduces`, whether the content hash matches, and every difference |

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

**Operators** (the first increment: set operations come later):

| Family | Operators |
|---|---|
| arithmetic | `add`, `sub`, `mul`, `div`, `neg`, `abs`, `pow` (a plain whole exponent), `min`, `max`, `convert` (with `"unit"`) |
| logic | `and`, `or`, `not`, `nand`, `nor`, `xor` |
| comparison | `eq`, `ne`, `lt`, `le`, `gt`, `ge` |

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
- **Angles** are their own dimension, so `30 deg + 1` is refused. `deg` and `rad` are not converted into each other,
  because their ratio is pi, which no fraction holds exactly.
- **Temperatures** are kelvin only. `°C` has an offset and does not add or multiply like a unit.

### Exactness

Every value is an exact fraction, and `+ - * /` and whole-number powers are exact. How a value is written:

- If its decimal ends within 40 significant digits, it is written exactly: `0.3`, `25.4 mm`, `1.602176634e-19 J`.
- Otherwise it is written rounded half-even to 30 significant digits, with its exact value beside it as a fraction:
  `"value": "4.44444444444444444444444444444 h", "exact": "40/9 h"`.

Comparisons always use exact values. A value whose numerator or denominator passes 20,000 bits is refused, not
carried.

### Errors

flo2's helper contract fixes the split.

- **A refused computation** is a normal reply: `{"status": "refused", "refused": {"node", "op", "kind", "reason",
  "units"}}`, with no result and no record. For example: units that measure different things, a division by zero, or a
  logic operator given a number.
- **A malformed call** is `isError: true`. Its text starts `Malformed call.` and names the field path, for example
  `graph.nodes[0].value: "furlong" is not a unit flo2-calc knows`. It is raised as the SDK's `ToolError`, because
  python-sdk 2.x passes on a `ToolError`'s text and hides every other exception's.

## The computation record

One JSON object, defined by
[`src/flo2_calc/schemas/calc-record-1.schema.json`](src/flo2_calc/schemas/calc-record-1.schema.json) (JSON Schema
draft 2020-12):

| Field | Holds |
|---|---|
| `record_format`, `schema_version` | `"flo2-calc computation record"`, `1` |
| `name` | the record's name; its file is `<name>.calc.json` |
| `supports` | optional: what it supports, as free text or `{"design_node": "dec:...", "design"?: "..."}` |
| `arithmetic` | what exactness means in this record |
| `graph` | the graph exactly as read, every value as text |
| `inputs` | each input's `id`, `value`, `unit` and `source` (free text or `{"design_node"}`) |
| `values` | every node's value, in evaluation order |
| `result` | `{"node", "value"}`, plus `"exact"` when the value is rounded |
| `produced_by` | `{"flo2_calc", "pint"}` versions |
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

## Generic math only

A domain's formulas stay with the helper that owns the domain: metal weight, ring sizes and stone sizes belong to
flo2-cad, and a building's quantities to flo2-ifc. flo2-calc does generic arithmetic, logic and comparison, with
units. Where a decision needs a domain number, the owning helper produces it, and flo2-calc takes it as an input with
its source.

## What is pinned and why

Every dependency is pinned exactly in `pyproject.toml`. That list is what the image and the plugin install.

| Pin | Why |
|---|---|
| `mcp==2.3.0` | The latest official MCP Python SDK (`dec:evaluator-language`). |
| `pint==0.26.1` | Gives what each unit measures and its exact factor to SI base units, loaded with exact fractions. |
| `flexparser==0.4`, `flexcache==0.3` | pint parses and caches its definitions with these, so they decide what a unit is. A record must re-run to the same result. |
| `jsonschema==4.26.0` | `rerun_record` checks a record against its schema first. |
| `pytest==9.1.1` (the `test` extra) | The tests. |
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
| Peak memory of one session (the cgroup's `memory.peak`) | 62.4 MiB under a 128 MiB cap, 62.1 MiB under 256 MiB |
| The session | 12 calls: three each of a 500-node graph, its record, the record's re-run, and a refused mixed-unit sum |
| Time for those 12 calls, one CPU, cold start included | 4.2 s |
| Image size | 182 MB (`python:3.12-slim` and the venv) |

A cap of **128m** is about twice the peak, the same rule flo2 used for flo2-cad's cap. CI runs the image under 128m.

## Working on it

```sh
uv venv -p 3.12 /tmp/flo2-calc-venv
uv pip install --python /tmp/flo2-calc-venv/bin/python -e '.[test]'
/tmp/flo2-calc-venv/bin/python -m pytest -v
```

- `tests/test_evaluator.py`, `tests/test_units.py`: exactness, every operator, every unit, and every refusal.
- `tests/test_record.py`: the record is deterministic and fits its schema; it re-runs; tampering is caught.
- `tests/test_server.py`: the four tools over a real MCP client session. Every refusal's reason is read on the
  client's side.
- `tests/test_conformance.py`: flo2's helper contract, asked in raw JSON-RPC as flo2's plug asks it.
- `tests/test_standalone.py`: the server alone, with a clean environment. It checks the root's edges, and that the
  package imports nothing of flo2 or reflow2.
- `tests/test_manifests.py`, `tests/test_dependency_currency.py`: both plugin formats, the skill, and the dependency
  check.

Set `FLO2_CALC_SERVER` to a command line, such as a confined `docker run` of the image, to ask the image the
conformance and server questions instead (CI's `image` job does).

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
3. **The helper's description**, its served skill (`skills/support-a-decision-with-math/SKILL.md`, unchanged), and a
   row in `HELPERS`.
4. **A row in the conformance check.**
   - One call that answers: `evaluate_graph` on `0.1 + 0.2`.
   - One call that fails: an input `"2 furlong"`, whose reason starts `Malformed call. graph.nodes[0].value`.
   - The door strips the SDK's `Error executing tool <name>:` preamble, as `model-door.ts` does.

No `--root` is passed when hosted, so flo2-calc writes no file. `rerun_record` takes the record's content. Reading a
kept record by path is not offered.

## Licence

Apache-2.0 ([LICENSE](LICENSE)).
