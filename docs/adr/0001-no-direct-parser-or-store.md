---
id: ADR-0001
title: adrgraph never touches tree-sitter or LadybugDB directly
status: accepted
owner: maintainers
date: 2026-11-05
review_date: 2027-11-05
rules:
  - id: no-tree-sitter
    description: Parsing belongs to srcgraph; adrgraph never imports a tree-sitter package.
    never:
      from: { path: "adrgraph/**" }
      to: { kind: unit, name: "tree_sitter*" }
      via: IMPORTS
  - id: no-ladybug
    description: The graph store belongs to srcgraph; adrgraph never imports ladybug.
    never:
      from: { path: "adrgraph/**" }
      to: { kind: unit, name: "ladybug" }
      via: IMPORTS
---

## Context

adrgraph used to contain the extractors and the graph store. They moved to
[srcgraph](https://github.com/crunchdomo/srcgraph) so the code graph can be used without ADRs.
If adrgraph reached past srcgraph to the parser or the database, the two would drift apart and
every rule would silently depend on which one parsed the file.

## Decision

adrgraph consumes srcgraph's API only: `Graph` with extension tables, `load_nodes`,
`load_edges`, `load_code`, `scan`, `compile_selector`, `Source`. No module under `adrgraph/`
imports `tree_sitter*` or `ladybug`.

## Consequences

Adding a language or swapping the store is srcgraph's business; adrgraph gets it for free. The
cost is one more package to install. This rule is enforced by `adrgraph check` on this repo.
