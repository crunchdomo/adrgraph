# adrgraph

Architecture decision records are prose. Code is structure. Nothing checks one against the other, so codebases drift from their ADRs silently. adrgraph builds a knowledge graph of your code and Terraform from their syntax trees, builds a graph of your ADRs, and evaluates the rules each ADR declares as graph queries. It fails CI when code breaks a decision, and it checks the ADRs against each other for contradictions and rot.

No server. The graph lives in an embedded [LadybugDB](https://github.com/LadybugDB/ladybug) file that is rebuilt on every run and queryable in Cypher.

**Two projects.** The code-to-graph engine is [srcgraph](https://github.com/crunchdomo/srcgraph): parsing, resolution, both tiers, the store, `build` and `query`. adrgraph depends on it and adds decisions, rules, verdicts and provenance. If you want the graph without ADRs, install srcgraph alone.

## Install

```bash
pipx install adrgraph        # or: pip install adrgraph inside a virtualenv
```

Until both packages are on PyPI, install straight from git:

```bash
pipx install git+https://github.com/crunchdomo/adrgraph --pip-args "git+https://github.com/crunchdomo/srcgraph@v0.1.0"
```

Python 3.11 or later. Python and Terraform (HCL) are supported out of the box.

## An ADR with rules

ADRs are markdown files in `docs/adr/` with YAML frontmatter. The prose stays yours. The `rules` list is what adrgraph enforces; the other keys put the decision into the graph even when it has no rules.

```markdown
---
id: ADR-0003
title: All gateway access goes through the contract layer
status: accepted            # proposed | accepted | superseded | deprecated
owner: platform
date: 2026-11-05
review_date: 2027-05-01
supersedes: [ADR-0001]      # optional
depends_on: [ADR-0002]      # optional: this decision assumes those hold
conflicts_with: []          # optional: declared conflicts (audit flags both accepted)
scope:                      # optional: the code this decision governs, rules or not
  - { path: "src/contracts/**" }
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
  - id: insights-subclass-base
    must:
      every:  { path: "src/insights/**", kind: class }
      except: [{ name: "_*" }]            # drop private helpers from the subject set
      has:    { name: "*PitWallWindow" }
      via:    INHERITS
  - id: no-handler-calls-db
    never:
      from: { path: "src/handlers/**", kind: function }
      to:   { path: "src/db/**" }
      via:  CALLS
      transitive: true
  - id: no-eval
    lang: python                          # a grammar-specific raw rule says which grammar
    cypher: |
      MATCH (a:Ast {kind:'call'})-[:CHILD {field:'function'}]->(f:Ast) WHERE f.text = 'eval'
      RETURN a.id AS node_id, a.path AS path, a.line AS line, 'calls eval' AS message
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

Every shape takes an optional `except` list of selectors removed from the subject set (`from` or `every`). Transitive `only` ignores paths that pass through `from`, so a layering rule does not flag everything upstream of the layer it protects.

### Selectors

A selector picks graph nodes. Keys are ANDed: `path` (glob, `**` allowed), `kind` (`unit`, `ast`, or a symbol kind: `function`, `method`, `class`, `type`, `variable`, `resource`, `module_call`, `unresolved`), `name` (glob over a symbol's name or qualified name, a unit's import name, or a syntax node's text with `kind: ast`), `lang`. Selectors never match syntax nodes unless `kind: ast` is given.

## The graph

The graph is srcgraph's; its [README](https://github.com/crunchdomo/srcgraph#the-graph) documents both tiers, the edge labels and the normalised vocabulary. adrgraph adds `Decision` and `Rule` nodes with `HAS_RULE`, `SUPERSEDES`, `DEPENDS_ON`, `CONFLICTS_WITH` and `BINDS` (rule or decision to the code it matched). Rules use the semantic tier by default; raw `cypher` rules may reach the syntax tier, and `audit` reports each rule's portability: `semantic`, `normalised` (uses only `norm`), or `grammar` (uses `kind`, tied to one language).

### Queries worth knowing

```bash
adrgraph query "MATCH (d:Decision)-[:BINDS]->(n) WHERE n.path = 'src/f1_data.py' RETURN d.id"           # which ADRs govern a file
adrgraph query "MATCH (a:Ast {norm:'Decorator'}) RETURN a.text, count(*) ORDER BY count(*) DESC"      # every decorator in use
adrgraph query "MATCH (c)-[:INHERITS]->(b) WHERE b.name = 'PitWallWindow' RETURN c.id"                  # subclasses of X
adrgraph query "MATCH (s:Symbol {name:'view'})-[:DERIVED_FROM]->(r)-[:CHILD*]->(n) RETURN n.kind, n.text"  # a symbol's subtree
```

## Commands

```bash
adrgraph check                        # build the graph, evaluate rules, exit 1 on violations
adrgraph audit                        # ADR-level checks and the portability summary
adrgraph explain src/x.py:9           # why is there a finding here? the full provenance trail
adrgraph explain ADR-0004/my-rule     # every finding of one rule
adrgraph report                       # .adrgraph/report.html: every finding as a trail, every ADR with what it binds
adrgraph check --format json --trails # machine-readable findings with their trails
adrgraph build                        # just build .adrgraph/graph.lbug
adrgraph query "<cypher>"             # ad hoc Cypher against the last build
```

`--adr` and `--src` repeat. With a `src/` layout (code imports `gateway.client`, not `src.gateway.client`) pass `--src src` so imports resolve; adrgraph warns when an import went unresolved but matches a scanned module under a deeper prefix. `--exclude` adds names or globs to the defaults (`.git`, `.venv`, `node_modules`, `.terraform`, ...). `--format json` on `check` and `audit`.

Rules on `proposed` decisions run as warnings. Rules on `superseded` or `deprecated` decisions are skipped by `check` and reported by `audit` if they would still fire.

### Findings and provenance

```
error     src/other/x.py:1   ADR-0003/gateway-only-via-contracts  reaches src/gateway/client.py
warn      src/handlers/h.py:10  ADR-0003/no-handler-calls-db  reaches src/db/q.py::q.run via src/contracts/c.py::c.call -> src/db/q.py::q.run
```

Import violations point at the import line. Transitive violations print the shortest path. JSON output carries `path_nodes`.

Every finding has a **trail**: decision → rule → violating node (with the source lines) → the edge or path that broke the rule → the syntax node it came from → which other ADRs govern the same code and whether the finding is baselined. `explain` prints it:

```
ADR-0004  Use PySide6 for menus and insights            docs/adr/0004-use-pyside6-for-menus-and-insights.md
  Decision: "PySide6 for the menu and insight windows; the replay itself stays on Arcade."
  rule pyside-only-in-ui   only {'path': 'src/gui/**'} may reach {'kind': 'unit', 'name': 'PySide6*'} via IMPORTS   [error, semantic]

violates  src/services/stream.py:9   (outside the from set and not excepted)
   6 │ import json
   7 │ import threading
   8 │ import time
   9 │ from PySide6.QtCore import QThread, Signal      ← IMPORTS → PySide6.QtCore (external)
  10 │

derived from  Ast module  src/services/stream.py#0:4012:module
baselined  yes  (.adrgraph/baseline.json)
```

`report` writes the same trails for every finding into one HTML page, plus a section per ADR listing the code it binds to.

### Audit checks

Orphan rule (a selector matches nothing), stale rule (a superseded decision's rule still fires), dangling supersession, overdue review, inferred contradiction (a `must` no `never`/`only` lets it satisfy), unmet dependency, declared conflict between two accepted decisions, empty scope. `dangling`, `contradiction`, `dependency` and `declared_conflict` fail; the rest warn unless `--strict`.

### Adopting on an existing codebase

```bash
adrgraph check --write-baseline     # records current violations in .adrgraph/baseline.json
git add .adrgraph/baseline.json
```

From then on `check` reports baselined violations without failing, flags new ones, and reports fixed ones. Rewrite the baseline when you want to ratchet it down.

### Local only, no CI

```bash
mkdir -p .githooks && printf '#!/usr/bin/env bash\nset -e\nadrgraph check\nadrgraph audit\n' > .githooks/pre-push
chmod +x .githooks/pre-push && git config core.hooksPath .githooks
```

Pin `adrgraph==<version>` in your dev requirements so everyone builds the same graph.

### Metrics

`check` ends with per-ADR and overall compliance (1 minus violations over bound nodes) and the number of violations fixed and new against the baseline. Bound nodes are the population a rule is measured against: the `from` set for `never`, the `every` set for `must`, and for `only` every node that reaches `to`, all minus `except`. A rule with an empty population reports `n/a`, never 100%.

### Performance

Measured with LadybugDB 0.22.1: a 17k-line repo builds its full two-tier graph (110k syntax nodes) in about 3 seconds; Django at 531k lines (3.0M syntax nodes, 4.5M edges) in about 25 seconds, producing a 630 MB database file, with 2-hop queries answering in tens of milliseconds. The syntax tier is always on.

## GitHub Action

```yaml
- uses: <owner>/adrgraph@v1
  with:
    adr: docs/adr
    src: .
```

## Adding a language

Write one module in `adrgraph/extractors/` that turns a tree-sitter tree into `Unit`, `Symbol`, `Edge`, `RawImport` and `RawRef` records from `adrgraph/model.py`, give it a grammar-kind to normalised-kind mapping and call `emit_syntax`, and register its extension in `adrgraph/extractors/__init__.py`. Nothing else changes. This repository enforces that boundary on itself; see `docs/adr/`.
