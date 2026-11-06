---
id: ADR-0002
title: The rule engine never depends on extractors
status: accepted
owner: maintainers
date: 2026-11-05
review_date: 2027-11-05
rules:
  - id: rules-never-import-extractors
    description: rules.py must not reach the extractors package, even transitively.
    never:
      from: { path: "adrgraph/rules.py" }
      to: { path: "adrgraph/extractors/**" }
      via: IMPORTS
      transitive: true
  - id: check-never-imports-extractors
    description: check.py must not reach the extractors package, even transitively.
    never:
      from: { path: "adrgraph/check.py" }
      to: { path: "adrgraph/extractors/**" }
      via: IMPORTS
      transitive: true
  - id: audit-never-imports-extractors
    description: audit.py must not reach the extractors package, even transitively.
    never:
      from: { path: "adrgraph/audit.py" }
      to: { path: "adrgraph/extractors/**" }
      via: IMPORTS
      transitive: true
---

## Context

Rules are evaluated against the graph, not against source. If the engine
imported an extractor it would be tempted to special-case a language.

## Decision

`rules.py`, `check.py` and `audit.py` depend only on the graph, the ADR model,
and selectors. Only `scan.py` and the CLI know extractors exist.

## Consequences

The engine can be tested with hand-built graphs (see `tests/conftest.py`)
and never needs a parser installed to run.
