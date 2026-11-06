---
id: ADR-0001
title: Extractors are the only code that touches tree-sitter
status: accepted
owner: maintainers
date: 2026-11-05
review_date: 2027-11-05
rules:
  - id: tree-sitter-only-in-extractors
    description: Only modules under adrgraph/extractors may import tree-sitter or a grammar package.
    only:
      from: { path: "adrgraph/extractors/**" }
      to: { kind: unit, name: "tree_sitter*" }
      via: IMPORTS
---

## Context

The code graph must stay language-neutral. If parsing details leak out of the
extractors, adding a language means touching the rule engine, and rules stop
being portable across languages.

## Decision

Every tree-sitter import lives in `adrgraph/extractors/`. Extractors emit only
the shared vocabulary in `adrgraph/model.py`; nothing else knows a syntax tree
exists.

## Consequences

Adding a language is one extractor module plus one grammar dependency. The
rule engine, scanner, and CLI are unaffected. This rule is enforced by
`adrgraph check` on this repository.
