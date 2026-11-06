# Two-tier graph: design (milestone 2)

Date: 2026-11-06
Status: draft, awaiting approval
Builds on: `2026-11-05-adr-enforcer-design.md` (milestone 1, shipped as adrgraph 0.1.0)

## Intent

Milestone 1 proved the loop: ADR rules run against a graph of the code and fail on drift. It also
showed the graph is shallow. tree-sitter produces about 6.5 named nodes per line of source and the
graph keeps 3% of them, so most ADRs that are about structure (inheritance, decorators, what a
function touches) cannot be expressed, and the ADR side of the graph has one relation
(`SUPERSEDES`) and no presence for ADRs without rules.

This milestone realises both graphs properly:

- The **code graph** gets two tiers. A **syntax tier** holds the entire tree for every file,
  exactly as the parser produced it. A **semantic tier** holds language-neutral concepts
  (units, symbols, imports, calls, inheritance, decoration) derived from the syntax tier and
  linked back to it.
- The **ADR graph** gets declared relations between decisions and a way for every ADR, rules
  or not, to bind to the code it governs.

Rules use the semantic tier by default. When it cannot express something, a rule drops to the
syntax tier in raw Cypher, and when such a pattern recurs it is promoted to a semantic edge.

## Goals

1. Every named syntax node of every scanned file is in the graph, with its grammar kind, a
   normalised kind where one exists, position, and leaf text.
2. New semantic edges `INHERITS` and `DECORATES`, derived for Python; the vocabulary admits
   `READS`, `WRITES`, `TYPE_OF`, `OVERRIDES` later without schema change.
3. Each semantic node links to the syntax node it was derived from.
4. ADR frontmatter can declare `depends_on`, `conflicts_with`, and `scope`; `audit` reasons
   over them.
5. Findings explain themselves: import violations carry the import's line; transitive
   violations print the path.
6. Acceptance: a rule for every enforceable ADR in the f1-race-replay fork (0001, 0004, 0005,
   0006) passes or fails for the right reason, and adrgraph's own ADRs still pass.

## Non-goals

- A third language. First item of the next milestone; the normalised-kind table is designed
  for it.
- `READS`/`WRITES`/`TYPE_OF`/`OVERRIDES` edges. Named in the vocabulary, not derived yet.
- Deriving semantic edges in Cypher over the loaded tree. Extractors keep doing it in Python.
- An opt-out flag for the syntax tier, or "standard" and "extended" build modes. Always on
  until a repo shows it hurts. A tree that is sometimes absent makes every raw rule pass
  vacuously on the build where it is missing, which is the failure this tool exists to
  prevent. If a lighter build is ever needed, the shape is a `--no-ast` flag under which
  `check` refuses to evaluate raw rules and says so, never silently passes them.
- Storing anonymous tokens (punctuation, keywords) or full text of non-leaf nodes.
- Incremental builds, live cloud state, a UI. Unchanged from milestone 1.

## Anti-goals

- Per-extractor invented node vocabularies. The normalised kind list is owned by the core.
- Rules that only work with the syntax tier present. The semantic tier stays complete on its
  own; the syntax tier is additive.
- A graph that only sometimes has the tree. Same schema every run.

## Constraints

- Same stack and dependency limits as milestone 1. No new dependencies.
- Build time on the f1 repo (17k lines, ~110k named nodes) stays under 10 seconds end to end.
- Everything milestone 1 enforces (extractors own tree-sitter, engine never imports
  extractors, ladybug only in graph.py) still holds and is still self-enforced.
- Existing ADR files and rules keep working unchanged.

## Decided: the syntax tier

One node table and two edge tables, populated by every extractor:

| Label | Properties |
|-------|------------|
| `Ast` | `id`, `path`, `kind` (grammar node type, e.g. `class_definition`), `norm` (normalised kind or empty), `lang`, `line`, `end_line`, `start_byte`, `end_byte`, `text` (leaf nodes only, else empty), `field` (the field name this node occupies in its parent, or empty) |

| Edge | From → To | Meaning |
|------|-----------|---------|
| `CHILD` | Ast→Ast | Parent to named child, in source order |
| `NEXT` | Ast→Ast | Named sibling order |

`id` is `f"{path}#{start_byte}:{end_byte}:{kind}"`. Only named nodes are stored. `text` is stored
for leaf nodes (named nodes with no named children) and for any node whose `norm` is in
`TEXT_NORMS = {"Decorator", "Attribute", "String", "Name", "Literal", "Type", "Import"}`, which
are the short, high-value spans rules match on (a dotted name, a decorator expression, a string
literal). Text is the source bytes decoded as UTF-8 with replacement and truncated to 512 bytes.
Everything else has empty `text` and is recoverable from `start_byte`/`end_byte`. The root node of each file has `field` empty and is the target of the file Unit's
`DERIVED_FROM` edge.

## Decided: how the graph is loaded

Measured on a synthetic tree the size of the f1 repo (110k nodes, 220k edges) with ladybug
0.22.1: the milestone 1 loader (`UNWIND ... MATCH (a {id}), (b {id}) CREATE`) takes 1.6 s for the
nodes and about an hour for the edges (20k edges in 318 s; the id lookup is a nested loop).
`COPY FROM` a temporary CSV loads the same data in 0.6 s total.

So `graph.py` loads every node and relationship table with `COPY FROM`: rows are written to CSV
files in a temporary directory with the stdlib `csv` module, one file per node table and one per
(label, from-table, to-table) group, then `COPY <table> FROM '<file>' (from='A', to='B')`. Verified:
a rel table accepts repeated COPYs (so `build` can still add `BINDS` after the first pass), edge
properties load from extra columns, and a missing endpoint is a hard error, so edges whose
endpoints are not loaded nodes are filtered in Python first, as today. No new dependency. The
10-second budget holds with margin; `NEXT` and "always on" stay.

## Decided: normalised kinds

A fixed vocabulary in `adrgraph/model.py`, `NORM_KINDS`:

`ClassDef`, `FunctionDef`, `Call`, `Assign`, `Import`, `Decorator`, `Attribute`, `Name`,
`String`, `Return`, `If`, `Loop`, `Try`, `Lambda`, `Parameter`, `Argument`, `Block`,
`Comment`, `Type`, `Literal`.

Each extractor owns a mapping `dict[str, str]` from its grammar's node types to `NORM_KINDS`.
A grammar type with no entry gets `norm = ""`. Extractors never add names to `NORM_KINDS`;
adding one is a core change with a reason. Python mapping, at minimum: `class_definition`→
`ClassDef`, `function_definition`→`FunctionDef`, `call`→`Call`, `assignment`/
`augmented_assignment`→`Assign`, `import_statement`/`import_from_statement`→`Import`,
`decorator`→`Decorator`, `attribute`→`Attribute`, `identifier`→`Name`, `string`→`String`,
`return_statement`→`Return`, `if_statement`→`If`, `for_statement`/`while_statement`→`Loop`,
`try_statement`→`Try`, `lambda`→`Lambda`, `default_parameter`/`typed_parameter`/
`typed_default_parameter`/`list_splat_pattern`/`dictionary_splat_pattern`→`Parameter`,
`keyword_argument`→`Argument`, `block`→`Block`, `comment`→`Comment`, `type`→`Type`, `integer`/
`float`/`true`/`false`/`none`→`Literal`.

`norm` is a function of the node's own grammar type only, never of its parent or field. A bare
`identifier` that happens to be a positional parameter or argument is a `Name`; rules that want
"the parameters of this function" walk `CHILD` from the `FunctionDef` through its `parameters`
child. This keeps the mapping a plain dict and keeps `{norm: 'Parameter'}` meaning one thing. Terraform mapping, at minimum: `block`→`ClassDef` is wrong and
must not be done; use `attribute`→`Assign`, `identifier`→`Name`, `string_lit`→`String`,
`function_call`→`Call`, `numeric_lit`/`bool_lit`→`Literal`, and leave Terraform blocks
unnormalised (they are already first-class `Symbol`s).

## Decided: new semantic edges

| Edge | From → To | Derived from (Python) |
|------|-----------|-----------------------|
| `INHERITS` | Symbol(class)→Symbol(class or unresolved) | each entry of `class_definition.superclasses`, resolved like a reference (alias map, then qualified lookup, else `unresolved`) |
| `DECORATES` | Symbol(function, method or class)→Symbol or unresolved | each `decorator` child of a `decorated_definition`; the decorator expression's dotted name, resolved like a reference; a decorator that is a call (`@route("/x")`) uses the callee |
| `DERIVED_FROM` | Unit→Ast, Symbol→Ast | the file root for a Unit; the defining node for a Symbol (the `class_definition`/`function_definition`, not the enclosing `decorated_definition`) |

Resolution rules are the existing ones in `scan.py`; the extractor emits `RawRef`s with a new
`relation` field (`"calls"`, `"references"`, `"inherits"`, `"decorates"`) replacing the boolean
`call`. `READS`, `WRITES`, `TYPE_OF`, `OVERRIDES` are added to `EDGE_LABELS` and to the rel
tables now so a raw rule can be written against them the day an extractor emits them, but no
extractor emits them in this milestone.

The `IMPORTS` edge gains a `line` property (the import statement's line). `CALLS`, `REFERENCES`,
`INHERITS`, `DECORATES` also carry `line`.

## Decided: `except` on rule shapes

Every shape gains an optional `except` selector list applied to its subject set (`from` for
`only`/`never`, `every` for `must`): nodes matching any `except` selector are removed before
evaluation and from the bound set. Needed the moment a real ADR met a real codebase: ADR-0006 in
the f1 fork is about insight windows, but `src/insights/` also holds private helper widgets.
Compiles to `AND NOT (<except_i>)` fragments; no new query shape.

## Decided: the ADR graph

Frontmatter gains three optional keys:

```yaml
depends_on: [ADR-0002]          # this decision assumes those hold
conflicts_with: [ADR-0005]      # declared, as opposed to the inferred contradiction check
scope:                          # what code this decision governs, rules or not
  - { path: "src/insights/**" }
  - { kind: resource, name: "aws_s3_bucket.*" }
```

Graph: `DEPENDS_ON` and `CONFLICTS_WITH` edges Decision→Decision; `BINDS` edges Decision→Unit|
Symbol for every node a `scope` selector matches (rule-level `BINDS` stay as they are).

`audit` gains:

7. **Unmet dependency**: an accepted decision `depends_on` a decision that is missing, or not
   accepted. Error.
8. **Declared conflict**: two decisions both accepted where either declares `conflicts_with`
   the other. Error.
9. **Empty scope**: an accepted decision whose `scope` selectors match nothing. Warn (error with
   `--strict`), same as orphan rules.

`check` is unchanged by scope; scope is for navigation and audit, not enforcement.

## Decided: findings that explain themselves

- An `only`/`never` violation over `IMPORTS` reports the line of the offending import
  (from the edge), not line 1 of the file. For other edge labels on a Unit, line stays 1.
- A transitive violation's message is the path: `reaches src/db/q.py via src/contracts/c.py ->
  src/db/q.py` (node ids joined by ` -> `, the source excluded). Shortest path, as evaluated.
- JSON output carries `path_nodes: [...]` for transitive findings.

## Decided: rule portability, reported

The two vocabularies live in one graph (`kind` and `norm` on every `Ast` node), so there are no
build modes to choose between. What differs is how portable a rule is across languages, and the
tool reports that rather than leaving it implicit. At compile time each rule is classified:

- `semantic`: a shape rule, or raw Cypher that never matches `Ast` nodes. Portable.
- `normalised`: raw Cypher on `Ast` that filters only by `norm`. Portable to any language whose
  mapping covers those kinds.
- `grammar`: raw Cypher on `Ast` that filters by `kind`. Tied to one grammar; the rule may
  declare `lang: python` to say which, else it is reported as `grammar (unspecified)`.

Classification is textual (does the Cypher mention `:Ast`, `.kind`, `.norm`); it is a report,
not a gate. `check --format json` carries `portability` per rule. `audit` prints one summary
line: `12 rules: 9 semantic, 2 normalised, 1 grammar (python)`. Nothing fails on it.

## Decided: queries worth shipping

Not commands, just documented in the README so the syntax tier is discoverable:

- which ADRs govern a file: `MATCH (d:Decision)-[:BINDS]->(n) WHERE n.path = $p RETURN d.id`
- every decorator in use: `MATCH (a:Ast {norm:'Decorator'}) RETURN a.text, count(*)`
- a symbol's subtree: `MATCH (s:Symbol {id:$id})-[:DERIVED_FROM]->(r)-[:CHILD*]->(n) RETURN n`
- classes that subclass X: `MATCH (c)-[:INHERITS]->(b) WHERE b.name = $x RETURN c.id`

## Acceptance

In the f1-race-replay fork, with frontmatter added to each:

- ADR-0001 FastF1 only via `src/f1_data.py`: `only` on `IMPORTS`, fails on two files, now with
  the real import lines.
- ADR-0004 PySide6 only in `src/gui/**` and `src/insights/**`: `only` on `IMPORTS`, fails on
  `main.py` and `src/services/stream.py`.
- ADR-0005 sockets only in `src/services/stream.py`: `only` on `IMPORTS`, passes.
- ADR-0006 insights subclass `PitWallWindow`: `must every {path: "src/insights/**", kind: class}
  except [{name: "_*"}, {name: "StintBar"}, {name: "LapAxisWidget"}] has {name: "*PitWallWindow"}
  via INHERITS`. Expected result: exactly one violation, `TelemetryStreamViewer`, which subclasses
  `QMainWindow` directly. That is real drift and the right reason to fail; the four excluded
  classes are helper widgets the ADR does not govern.
- ADR-0002, 0003, 0007 get a `scope` and appear in `BINDS` with zero rules.

In adrgraph itself: the three existing ADRs pass, and a fourth is added: "the normalised kind
vocabulary is owned by the core", enforced as `never from {path: "adrgraph/extractors/**"} to
{name: "adrgraph.model.NORM_KINDS"} via WRITES` once `WRITES` exists; until then as prose with a
`scope` of `adrgraph/model.py`.

## Known ceilings

- `INHERITS` to a base that is an expression (`class A(make_base()):`) becomes `unresolved`.
- `DECORATES` resolves by name; a decorator imported under an alias resolves through the alias
  map, a decorator built at runtime does not.
- The syntax tier roughly multiplies graph size by 35. Fine to a few million nodes; beyond that
  an opt-out flag is the upgrade.
- `NEXT` edges double the sibling edge count. Kept because order matters for rules like "the
  first statement in every handler is a permission check"; drop if size ever bites first.

## Decided: selectors never match syntax nodes

`compile_selector` adds `label(n) <> 'Ast'` unless the selector names `kind: ast` explicitly.
Otherwise every `path` selector, every `scope`, every bound-node count and every `BINDS` edge
would pick up the syntax tier and silently change milestone 1's compliance numbers. Raw Cypher
rules reach `Ast` nodes directly and are unaffected.

## Left to the builder

- LadybugDB DDL for `Ast`, `CHILD`, `NEXT`, `DERIVED_FROM`, the new semantic rel tables, and
  the `line` property on existing rel tables.
- The CSV writer: quoting, the temp directory's lifetime, and whether milestone 1's node tables
  also move to COPY FROM (they should; one loader is simpler than two).
- The syntax-tier walk as a shared helper under `adrgraph/extractors/` taking (tree, mapping,
  path), used by both extractors.
- `READS`/`WRITES`/`TYPE_OF`/`OVERRIDES` get the same from/to pairs as `REFERENCES`.
- Duplicate `IMPORTS` of one module from one file report the lowest line; a transitive `only`
  over `IMPORTS` reports the first hop's line.
- "Empty scope" is reported per selector, like orphan rules.
- `Ast.id` collisions (same span, same kind) are deduplicated, never a load error.
- How `RawRef.relation` replaces `call` without breaking the Terraform extractor.
- The exact grammar-type to normalised-kind tables, beyond the minimum listed.
- Test fixtures for `INHERITS`/`DECORATES`, including aliased and call-form decorators.
- Where the per-edge `line` is threaded through `Edge` (a new optional field is the obvious
  choice).
