---
id: ADR-0005
title: Everything graph-shaped is delegated to srcgraph
status: accepted
owner: maintainers
date: 2026-11-06
review_date: 2027-11-06
depends_on: [ADR-0002]
scope:
  - { path: "adrgraph/schema.py" }
  - { path: "adrgraph/cli.py" }
---

## Context

Two projects share one graph. srcgraph owns parsing, resolution, the two tiers and the store;
adrgraph owns decisions, rules, verdicts and provenance. The seam is srcgraph's
schema-extension API, and `adrgraph/schema.py` is the only place that knows what adrgraph adds
to the graph.

## Decision

adrgraph never re-implements scanning, extraction or loading. New code-level facts (an edge
type, a language) are added in srcgraph and consumed here. `schema.py` declares adrgraph's
tables; `cli.build` is the one place that composes a srcgraph build with those tables.

## Consequences

A feature that needs a new edge is two changes in two repositories, in order: srcgraph first,
then a version bump here. In exchange, srcgraph stays useful to people who never write an ADR.
