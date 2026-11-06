---
id: ADR-0002
title: Handlers log every request
status: proposed
owner: platform
date: 2026-11-05
rules:
  - id: every-handler-logs
    description: Every handler function calls the logger.
    must:
      every: { path: "src/handlers/**", kind: function }
      has: { path: "src/log.py" }
      via: CALLS
---

## Context

Proposed, not yet accepted.
