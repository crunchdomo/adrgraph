---
id: ADR-0003
title: LadybugDB is the graph store and the database file is disposable
status: accepted
owner: maintainers
date: 2026-11-05
review_date: 2027-05-05
rules:
  - id: ladybug-only-in-graph
    description: Only graph.py may import ladybug, so the store can be swapped behind one module.
    only:
      from: { path: "adrgraph/graph.py" }
      to: { kind: unit, name: "ladybug" }
      via: IMPORTS
---

## Context

The tool needs a real property graph with Cypher so rules are expressive and
the graph is explorable, but a CI check cannot require a database server.
LadybugDB (the renamed Kùzu) is embedded, in-process, and Cypher-native.
It is a 0.x project with a young release cadence.

## Options considered

- Neo4j or Memgraph: real graphs, but a server in CI.
- networkx in memory: no server, no Cypher, no exploration story.
- LadybugDB: embedded, Cypher, columnar, pip-installable.

## Decision

LadybugDB, confined to `adrgraph/graph.py`. The database file under
`.adrgraph/` is a build artifact: rebuilt from source and ADRs on every run,
git-ignored, never the only copy of anything.

## Consequences

Rules are written in Cypher and port to other engines if LadybugDB stalls.
Crash-recovery bugs in the store cannot lose data because nothing is stored
only there. Swapping the engine is a one-module change.
