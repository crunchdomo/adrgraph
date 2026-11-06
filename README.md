# adrgraph

Architecture decision records are prose. Code is structure. Nothing checks one against the other, so codebases drift from their ADRs silently. adrgraph builds a knowledge graph of your code and Terraform from their syntax trees, builds a graph of your ADRs, and evaluates the rules each ADR declares as graph queries. It fails CI when code breaks a decision, and it checks the ADRs against each other for contradictions and rot.

No server. The graph lives in an embedded [LadybugDB](https://github.com/LadybugDB/ladybug) file that is rebuilt on every run and queryable in Cypher.

## Install

```bash
pip install adrgraph
```

Python 3.11 or later. Python and Terraform (HCL) are supported out of the box.

## An ADR with rules

ADRs are markdown files in `docs/adr/` with YAML frontmatter. The prose stays yours. The `rules` list is what adrgraph enforces.

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
    must:
      every: { kind: resource, name: "aws_s3_bucket.*" }
      has:   { kind: resource, name: "aws_s3_bucket_policy.*" }
      via:   REFERENCES
      direction: in
  - id: no-handler-calls-db
    never:
      from: { path: "src/handlers/**", kind: function }
      to:   { path: "src/db/**" }
      via:  CALLS
      transitive: true
  - id: custom
    cypher: |
      MATCH (s:Symbol)-[:CALLS]->(t:Symbol) WHERE t.name = 'eval'
      RETURN s.id AS node_id, s.path AS path, s.line AS line, 'calls eval' AS message
---

## Context
...
```

### Rule shapes

| Shape | Reads as | Violation |
|-------|----------|-----------|
| `only` | only `from` may reach `to` via `via` | a node outside `from` with an edge (or path, if `transitive`) into `to` |
| `never` | `from` never reaches `to` via `via` | a `from` node with an edge or path into `to` |
| `must` | every `every` has a `via` edge to (or from, with `direction: in`) some `has` | an `every` node with no such edge |
| `cypher` | anything else | each row the query returns; it must return `node_id`, `path`, `line`, `message` |

Transitive `only` ignores paths that pass through `from`, so a layering rule does not flag everything upstream of the layer it protects.

### Selectors

A selector picks graph nodes. Keys are ANDed: `path` (glob, `**` allowed), `kind` (`unit`, or a symbol kind: `function`, `method`, `class`, `type`, `variable`, `resource`, `module_call`, `unresolved`), `name` (glob over a symbol's name or qualified name, or a unit's import name), `lang`.

### The graph

Nodes: `Unit` (file, package, module, or an `external` import such as `logging`), `Symbol` (function, class, Terraform resource, ...), `Decision`, `Rule`. Edges: `CONTAINS`, `IMPORTS`, `CALLS`, `REFERENCES`, `HAS_RULE`, `SUPERSEDES`, `BINDS`. Every symbol keeps its file, line and the grammar's own node type.

## Commands

```bash
adrgraph check                 # build the graph, evaluate rules, exit 1 on violations
adrgraph audit                 # orphan rules, stale rules, dangling supersession, overdue reviews, contradictions
adrgraph build                 # just build .adrgraph/graph.lbug
adrgraph query "MATCH (u:Unit)-[:IMPORTS]->(v:Unit) RETURN u.path, v.name LIMIT 10"
```

`--adr` and `--src` repeat. `--exclude` adds names or globs to the defaults (`.git`, `.venv`, `node_modules`, `.terraform`, ...). `--format json` on `check` and `audit`.

Rules on `proposed` decisions run as warnings. Rules on `superseded` or `deprecated` decisions are skipped by `check` and reported by `audit` if they would still fire.

### Adopting on an existing codebase

```bash
adrgraph check --write-baseline     # records current violations in .adrgraph/baseline.json
git add .adrgraph/baseline.json
```

From then on `check` reports baselined violations without failing, flags new ones, and reports fixed ones. Rewrite the baseline when you want to ratchet it down.

### Metrics

`check` ends with per-ADR and overall compliance (1 minus violations over bound nodes) and the number of violations fixed and new against the baseline. A rule whose selectors match nothing reports `n/a`, never 100%.

## GitHub Action

```yaml
- uses: <owner>/adrgraph@v1
  with:
    adr: docs/adr
    src: .
```

## Adding a language

Write one module in `adrgraph/extractors/` that turns a tree-sitter tree into `Unit`, `Symbol`, `Edge`, `RawImport` and `RawRef` records from `adrgraph/model.py`, and register its extension in `adrgraph/extractors/__init__.py`. Nothing else changes. This repository enforces that boundary on itself; see `docs/adr/`.
