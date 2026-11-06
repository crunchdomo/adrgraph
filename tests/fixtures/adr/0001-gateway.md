---
id: ADR-0001
title: Gateway via contracts
status: accepted
owner: platform
date: 2026-11-05
review_date: 2027-05-01
rules:
  - id: gateway-only-via-contracts
    description: Only the contracts package may import the gateway client.
    only:
      from: { path: "src/contracts/**" }
      to: { path: "src/gateway/client.py" }
      via: IMPORTS
  - id: no-handler-calls-db
    description: HTTP handlers never call the database layer, even indirectly.
    severity: warn
    never:
      from: { path: "src/handlers/**" }
      to: { path: "src/db/**" }
      via: CALLS
      transitive: true
  - id: custom
    description: Nothing calls eval.
    severity: warn
    cypher: "MATCH (s:Symbol) WHERE s.name = 'eval' RETURN s.id AS node_id, s.path AS path, s.line AS line, 'calls eval' AS message"
---

## Context

Services were calling the gateway directly and drifting from the contract layer.

## Decision

All gateway access goes through `src/contracts`.

## Consequences

Direct imports of the gateway client outside contracts fail CI.
