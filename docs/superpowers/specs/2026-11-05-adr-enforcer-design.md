# ADR Enforcer: design

Date: 2026-11-05
Status: approved 2026-11-05

## Intent

ADRs record architecture decisions as prose. Code is structure. Nothing bridges the two, so codebases drift from their ADRs silently: nobody checks, and by the time someone asks "are we still compliant?" the answer is unknowable without a human re-reading every ADR and grepping. ADRs also drift from each other: they contradict, go stale, or bind to code that no longer exists.

This tool makes ADRs enforceable. Each ADR carries machine-checkable rules. The tool builds a knowledge graph of the codebase from its syntax trees, builds a graph of the ADRs, links them, and evaluates the rules in CI. It also checks the ADRs against each other.

The motivating case: an ADR said all gateway interaction goes through a contract layer. Services drifted to direct calls. Nobody noticed because nothing looked.

## Goals

1. `adrgraph check` fails CI when code violates an ADR rule, naming the ADR, the rule, and the offending symbol with file and line.
2. `adrgraph audit` reports ADR-level problems: rules that bind to nothing, active rules that contradict, superseded decisions whose rules still fire, overdue reviews.
3. The code graph is language-agnostic and low level. Any language with a tree-sitter grammar can be added by writing one extractor. Rules never know which language they query.
4. The graph is a real property graph, queryable in Cypher, usable for exploration beyond the built-in checks.
5. Zero infrastructure. CI needs a Python install and `pip install`. No server.
6. The tool enforces its own ADRs on its own code from the first commit.
7. Adoptable on existing code: a baseline file records known violations so `check` fails only on new ones and ratchets down as they are fixed.
8. Usable from GitHub Actions as `uses: <owner>/adrgraph@v1`, via a composite action in this repo.
9. Reports numbers: per rule, per ADR, overall compliance, and movement against the baseline.

## Non-goals (v1)

- Live cloud state (AWS API). Terraform source is the cloud side for now. The schema must not preclude a live-state extractor later.
- LLM review agents, approval workflows, a ten-stage lifecycle. Process around the tool is the team's business.
- A web UI. The database file is openable with LadybugDB's own tooling for browsing.
- A separate `report` command or dashboard. Metrics ride along with `check` output.
- Inline suppression comments in source. They need per-language comment syntax. The baseline file is the suppression mechanism.
- Per-rule violation tolerances. The baseline covers the ratchet case.
- A pre-commit hook definition.
- Multi-repo governance (a central architecture repo ruling many service repos). Single repo, including monorepos, for v1.
- Auto-discovery of nested ADR directories. `--adr` is repeatable instead.
- Incremental builds. Every run rebuilds the graph from scratch.
- Type-accurate call resolution. Calls resolve by import graph and name. See "Known ceilings".
- Languages beyond Python and Terraform (HCL). The schema is designed for more; v1 ships two extractors.

## Anti-goals

Things that would make this a failure even if it technically works:

- Requiring a database server to run the check. Teams won't adopt it.
- Rules that are Python-shaped, so adding Rust means touching the rule engine.
- A graph that is only reachable through the tool's own commands. It must be a real graph you can open and query.
- ADRs that become YAML blobs. The prose (context, options, consequences) stays markdown and stays primary.

## Constraints

- Open source, MIT licence, published to PyPI as `adrgraph`. Package, import name and command are all `adrgraph`. (`adrc` and `adr-enforcer` are taken on PyPI.)
- Python 3.11+, single package, installable with pip.
- Dependencies: `ladybug` (LadybugDB, the renamed Kùzu, embedded, Cypher), `tree-sitter` plus the `tree-sitter-python` and `tree-sitter-hcl` grammar packages, a YAML parser. Nothing else without a reason in an ADR.
- LadybugDB is 0.x. The database file is a build artifact, rebuilt every run, never the only copy of anything, and git-ignored. Rules are Cypher, so they port to Neo4j or Memgraph if LadybugDB stalls.
- `mise.toml` pins the Python version and defines task aliases (`check`, `audit`, `test`).

## Decided: the ADR file

ADRs are markdown files in `docs/adr/`, one decision per file, named `NNNN-slug.md`. YAML frontmatter carries the structured fields; the body is prose.

```markdown
---
id: ADR-0003
title: All gateway access goes through the contract layer
status: accepted            # proposed | accepted | superseded | deprecated
owner: platform
date: 2026-11-05
review_date: 2027-05-01
supersedes: [ADR-0001]      # optional
rules:
  - id: gateway-only-via-contracts
    description: Only the contracts package may import the gateway client.
    severity: error          # error (default) | warn
    only:
      from: { path: "src/contracts/**" }
      to:   { path: "src/gateway/client.py" }
      via:  IMPORTS
  - id: every-bucket-has-policy
    description: Every S3 bucket has a bucket policy referencing it.
    must:
      every: { kind: resource, name: "aws_s3_bucket.*" }
      has:   { kind: resource, name: "aws_s3_bucket_policy.*" }
      via:   REFERENCES
      direction: in
  - id: no-handler-calls-db
    description: HTTP handlers never call the database layer directly.
    never:
      from: { path: "src/handlers/**", kind: function }
      to:   { path: "src/db/**" }
      via:  CALLS
      transitive: true
  - id: custom
    description: Anything the shapes can't express.
    cypher: |
      MATCH (s:Symbol)-[:CALLS]->(t:Symbol)
      WHERE t.name = 'eval' RETURN s.id AS node_id, 'calls eval' AS message
---

## Context
...prose...

## Decision
...prose...

## Consequences
...prose...
```

Each rule has a `severity`: `error` (default) fails `check`; `warn` is reported and never fails. Rules on `accepted` decisions run at their declared severity. Rules on `proposed` decisions run as `warn` regardless of declaration, so a proposal shows its blast radius before acceptance. Rules on `superseded` or `deprecated` decisions are skipped by `check` and reported by `audit` if they would still fire.

## Decided: the graph schema

One vocabulary, shared by every extractor. Extractors emit only these.

Nodes:

| Label      | Properties |
|------------|------------|
| `Unit`     | `id`, `path`, `name`, `lang`, `kind` (`file`, `package`, `module`, `external`) |
| `Symbol`   | `id`, `name`, `qualified`, `kind`, `lang`, `path`, `line`, `end_line`, `ast_kind` |
| `Decision` | `id`, `title`, `status`, `owner`, `date`, `review_date`, `path` |
| `Rule`     | `id`, `decision`, `shape`, `cypher`, `description` |

`Unit.name` is the unit's import name: the dotted module path for Python (`adrgraph.extractors.python`), the file path for Terraform. An import of a module that is not in the scanned tree (a third-party or stdlib module) creates a `Unit` with `kind: external`, `name` and `path` both set to the dotted name, and `lang` of the importer. External units are never silently dropped; rules can target them by `name`, which is how the dogfood rule ADR-0001 matches `tree_sitter*`.

`Symbol.kind` is a small shared enum: `function`, `method`, `class`, `type`, `variable`, `resource`, `module_call`, `unresolved`. `ast_kind` keeps the grammar's own node type (for example `function_definition`, `block`) so nothing is lost. `id` is `path::qualified` for symbols and the path for units. Line numbers are 1-based.

Edges:

| Edge         | From → To            | Meaning |
|--------------|----------------------|---------|
| `CONTAINS`   | Unit→Unit, Unit→Symbol, Symbol→Symbol | Structural nesting |
| `IMPORTS`    | Unit→Unit            | Module or file import |
| `CALLS`      | Symbol→Symbol, Unit→Symbol | Direct call. Calls at module scope (top level, `if __name__ == "__main__":`) originate from the file's `Unit` |
| `REFERENCES` | Symbol→Symbol, Symbol→Unit, Unit→Symbol, Unit→Unit | Any other name reference, including Terraform resource and variable references. Module-scope references originate from the `Unit` |
| `HAS_RULE`   | Decision→Rule        | |
| `SUPERSEDES` | Decision→Decision    | |
| `BINDS`      | Rule→Unit, Rule→Symbol | Materialised after extraction: every node a rule's selectors matched |

Unresolved references (a call to a name the extractor cannot map to a known symbol) point at a `Symbol` with `kind: unresolved` and the bare name. They are never silently dropped; a rule can target them.

## Decided: selectors

A selector is a small map that resolves to a set of graph nodes. Keys, all optional, all ANDed:

- `path`: glob over `path`, `**` allowed
- `kind`: a `Symbol.kind` value, or `unit`
- `name`: glob over `name` or `qualified` (symbols) and over `name` (units)
- `lang`: extractor language id

A selector with no `kind` matches both units and symbols. Each selector compiles to a Cypher `MATCH ... WHERE` fragment.

## Decided: rule shapes

Three shapes cover most architecture rules. Each compiles to a Cypher query that returns zero rows when compliant, otherwise one row per violation with `node_id` and `message`. Raw `cypher` rules follow the same contract and skip compilation.

- **only**: `from`, `to`, `via`, optional `transitive`. Violation: any node not matched by `from` with a `via` edge (or path, if transitive) into a `to` node.
- **never**: `from`, `to`, `via`, optional `transitive`. Violation: any `from` node with a `via` edge or path into a `to` node.
- **must**: `every`, `has`, `via`, optional `direction` (`out` default, or `in`). Violation: any `every` node with no `via` edge to (or from) a `has` node.

`via` is one edge label or a list. `transitive` defaults to false. Transitive `only` and `never` use variable-length paths over the listed edge labels.

Transitive `only` counts a path as a violation only when every intermediate node on it lies outside `from`. A module that reaches the gateway *through* the contracts layer is compliant; that is the whole point of a layering rule. Transitive `never` has no such exemption.

## Decided: the `audit` checks

Run against the ADR graph after `BINDS` edges exist:

1. **Orphan rule**: a selector in an accepted rule matched zero nodes. Likely mis-scoped or the code moved.
2. **Stale rule**: a rule on a `superseded` or `deprecated` decision that would produce violations if evaluated.
3. **Dangling supersession**: `supersedes` points at an id that does not exist, or at a decision still `accepted`.
4. **Overdue review**: `review_date` is in the past on an accepted decision.
5. **Contradiction**: an accepted `must` that cannot be satisfied without violating an accepted `never` or `only`. Computed from bound node sets, comparing only rules that share a `via` label, with `must` pairs oriented by its `direction`. For each node `e` matched by the `must`'s `every`, the forbidden targets are the `never`'s `to` set if `e` is in its `from`, or the `only`'s `to` set if `e` is outside its `from`. It is a contradiction when the `must`'s entire `has` set lies inside `e`'s forbidden targets: there is no edge `e` could have that satisfies one rule without breaking the other. A `must` whose `has` set has at least one permitted target is not a contradiction, even if some of its targets are forbidden. Raw `cypher` rules are not compared.
6. **Duplicate id**: two files declare the same decision or rule id.

`audit` exits non-zero on 3, 5 and 6. The rest are warnings unless `--strict`.

## Decided: the CLI

Package and command name: `adrgraph`.

- `adrgraph build [--adr docs/adr] [--src .]` builds `.adrgraph/graph.lbug` from scratch. `--adr` and `--src` both repeat; defaults are `docs/adr` and the current directory. ADR and rule ids must be unique across all `--adr` dirs. Default excludes: `.git`, `.venv`, `venv`, `node_modules`, `.terraform`, `.adrgraph`, plus `--exclude` globs.
- `adrgraph check` runs `build`, then evaluates every accepted and proposed rule. Exit 0 when no `error`-severity violation is outside the baseline, 1 otherwise, 2 on tool error (bad ADR, parse failure).
- `adrgraph check --write-baseline` writes `.adrgraph/baseline.json`: the set of current violations keyed by decision id, rule id and node id. On later runs a violation present in the baseline is reported as `baselined` and does not fail. A baselined violation that no longer occurs is reported as `fixed`; the baseline is only rewritten on `--write-baseline`, so the ratchet is explicit. The baseline is committed.
- `adrgraph audit` runs `build`, then the audit checks. Same exit convention.
- `adrgraph query "<cypher>"` runs ad hoc Cypher against the last built graph and prints rows.
- `--format text|json` on `check` and `audit`. Text output is one line per finding: `path:line  ADR-0003/gateway-only-via-contracts  message`, prefixed with `error`, `warn`, or `baselined`.
- `check` ends with a metrics summary, also present in the JSON output: per rule, bound nodes and violations; per ADR and overall, compliance as 1 minus violations over bound nodes; and against the baseline, counts of fixed and new violations. Rules with zero bound nodes report compliance as not applicable, never as 100%.

## Decided: GitHub Action

A composite `action.yml` at the repo root. Inputs: `adr` (repeatable as a newline list), `src`, `baseline`, `format`, `python-version`. It sets up Python, installs `adrgraph` at the action's own version, and runs `check`, so a workflow is one `uses:` step. The action is a thin wrapper and contains no logic of its own.

No config file in v1. Defaults plus flags. Repo layout is a monorepo-friendly single repo: both extractors run over every scanned file, chosen by extension. If flags get unwieldy, a `[tool.adrgraph]` table in `pyproject.toml`, never a new file.

## Decided: extractors

An extractor is one module per language that takes a file path and source bytes and yields nodes and edges in the shared vocabulary. It knows tree-sitter; nothing else does.

- **Python**: units for packages and modules; symbols for functions, methods, classes, module-level variables; `IMPORTS` from `import` and `from ... import`; `CALLS` resolved by import graph plus name, falling back to `unresolved`; `REFERENCES` for attribute and name references that are not calls.

  Import resolution: every `--src` directory is an import root (the flag may repeat; default is the current directory). A dotted name resolves to `<root>/a/b/c.py` or `<root>/a/b/c/__init__.py` under exactly one root. Relative imports resolve from the importing file's package. No hit under any root creates an `external` unit. A hit under more than one root is a warning naming both candidates, and the import is treated as external; the build does not fail. `pyproject.toml` package-dir settings are not read in v1.
- **Terraform (HCL)**: one unit per `.tf` file; symbols with `kind: resource` for `resource`, `data`, `variable`, `output`, `locals` entries, `kind: module_call` for `module` blocks; `name` is `type.label` (for example `aws_s3_bucket.logs`); `REFERENCES` for every interpolation or attribute reference to another block (`aws_s3_bucket.logs.id` references `aws_s3_bucket.logs`).

Adding a language means adding one module and one grammar dependency. The core must not special-case either language.

## Decided: dogfooding

The repo ships with its own ADRs in `docs/adr/`, enforced by `adrgraph check` in its own CI. At minimum:

- ADR-0001: extractors are the only code that imports tree-sitter. Rule: `only from {path: "adrgraph/extractors/**"} to {name: "tree_sitter*"} via IMPORTS`.
- ADR-0002: the rule engine never imports extractors. Rule: `never from {path: "adrgraph/rules/**"} to {path: "adrgraph/extractors/**"} via IMPORTS`.
- ADR-0003: LadybugDB is the graph store, and the database file is a disposable build artifact.

## Known ceilings

Deliberate simplifications with a known upgrade path:

- Call resolution is name-based through the import graph. Dynamic dispatch, re-exports and decorators will produce `unresolved` symbols. Upgrade: a per-language resolver using a real type checker.
- Contradiction detection compares bound node sets, not rule semantics. It catches direct conflicts, not ones that only appear through transitive paths. Upgrade: evaluate both rules' Cypher and intersect results.
- Full rebuild every run. Fine for one repo; upgrade to incremental by hashing files when it isn't.

## Left to the builder

- Package layout inside `adrgraph/`, test layout, CI config.
- How selectors with no `kind` are unioned in Cypher.
- Exact LadybugDB schema DDL and how node tables map to the labels above (LadybugDB needs explicit node and rel tables).
- Whether `BINDS` edges are stored or computed on demand in v1.
- Error messages and the JSON output schema, as long as every finding carries decision id, rule id, node id, path, line and message.
- Which tree-sitter grammar packages to pin (`tree-sitter-hcl` may only be available through `tree-sitter-language-pack`), and the `mise.toml` contents.
- Whether raw `cypher` rules get `BINDS` edges. They are skipped by the orphan and contradiction checks either way.
- How `query` prints results.
