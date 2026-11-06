# srcgraph and adrgraph: the split, and provenance (milestone 3)

Date: 2026-11-06
Status: draft, awaiting approval
Builds on: milestone 1 (`2026-11-05-adr-enforcer-design.md`) and milestone 2 (`2026-11-06-two-tier-graph-design.md`), shipped as adrgraph 0.2.0.

## Intent

Two things became clear on the f1 fork. First, half of adrgraph is a general codebase-to-graph
tool that has nothing to do with ADRs, and people will want it on its own. Second, the tool
knows exactly why every finding exists (decision, rule, node, edge, syntax node) and shows none
of it; the only way to see provenance is to write Cypher by hand.

This milestone splits the code into two projects and gives the enforcer a provenance layer with
three views built on one model.

- **srcgraph**: source code (and Terraform) in, a queryable two-tier property graph out. Knows
  nothing about ADRs. Ships the explorer.
- **adrgraph**: ADRs in, verdicts out. Depends on srcgraph as a library. Ships `explain` and
  `report`, and overlays its findings on srcgraph's explorer.

The provenance model is a **trail**: an ordered list of steps from the decision to the syntax
node, each step carrying its evidence. One builder produces trails; three renderers consume
them (terminal text, HTML report, JSON for the explorer).

## Goals

1. `srcgraph` is installable alone and can build, query and serve an explorer for any repo
   with no ADR anywhere.
2. `adrgraph` installs `srcgraph` as a dependency, adds its tables to the graph through a
   schema-extension API, and behaves exactly as 0.2.0 does for `build`, `check`, `audit`,
   `query` (same output, same exit codes, same ADR format).
3. `adrgraph explain <path>:<line> [ADR-id]` prints the trail for a finding with source lines.
4. `adrgraph report [-o report.html]` writes one self-contained HTML page: every finding as a
   trail, every ADR with what it binds to, metrics.
5. `srcgraph serve` opens a local explorer: search, a node's neighbourhood as a graph, a detail
   panel, source excerpt, drill into the syntax tier. `adrgraph serve` is the same explorer with
   findings and trails overlaid.
6. The dependency direction (adrgraph → srcgraph, never back) is enforced by adrgraph's own ADRs.
7. All 105 existing tests still pass, relocated into the package they test.

## Non-goals

- Publishing either package. Still waits on PyPI setup.
- A hosted or multi-user explorer. `serve` binds to localhost for one person.
- Editing anything through the explorer. Read-only.
- Trails for `audit` findings. Those are about ADRs, not code; `audit` output is unchanged.
- A third language. Still the milestone after this one.

## Anti-goals

- A provenance view that recomputes anything. Everything a trail shows is already in the graph;
  the trail builder only reads.
- Three provenance features with three data models. One `Trail`, three renderers.
- srcgraph importing anything from adrgraph, even in tests.
- The explorer requiring a build step, a bundler, or a package manager. One HTML file and the
  stdlib HTTP server.

## Constraints

- Still no new Python dependencies in either package. The explorer page may load `d3` from a
  pinned CDN URL for layout (it runs in the browser, not in CI); everything else inline.
- Python 3.11+. Same tree-sitter and LadybugDB versions.
- `adrgraph` 0.2.0 behaviour is the compatibility bar: the f1 fork's baseline and hook keep
  working without edits.

## Decided: two repositories

`srcgraph` is its own repository, `crunchdomo/srcgraph`, checked out at `~/Documents/srcgraph`,
created private (the user makes it public). `adrgraph` stays in `crunchdomo/adrgraph`
(`~/Documents/adr-as-code`) and becomes the enforcer only. Each repository has its own tests,
CI, README, licence (MIT), `mise.toml` and `docs/adr/`. The history of the moved modules stays in
adrgraph's git log; srcgraph starts fresh with one commit that cites the source commit.

## Decided: repository layout

```
~/Documents/srcgraph/                              (repo crunchdomo/srcgraph)
    pyproject.toml          name "srcgraph", version 0.1.0
    srcgraph/
      model.py              vocabulary: Unit, Symbol, Edge, AstNode, RawImport, RawRef, NORM_KINDS, TEXT_NORMS, ...
      extractors/           __init__.py, lines.py, syntax.py, python.py, terraform.py
      scan.py
      graph.py              Graph with schema-extension API (below)
      selectors.py
      source.py             NEW: read a file's lines for excerpts (used by trails and serve)
      serve.py              NEW: stdlib HTTP server + JSON API
      explorer.html         NEW: the single-page explorer
      cli.py                srcgraph build | query | serve
    tests/
    docs/adr/               ADR-0001 "nothing in srcgraph imports adrgraph" (adrgraph is a dev-only tool here)
    .github/workflows/ci.yml  pytest, then `adrgraph check` with adrgraph installed from git as a dev tool

~/Documents/adr-as-code/                           (repo crunchdomo/adrgraph)
    pyproject.toml          name "adrgraph", version 0.3.0, dependency srcgraph>=0.1
    adrgraph/
      adr.py, rules.py, check.py, audit.py, baseline.py
      schema.py             NEW: Decision/Rule tables and ADR rel tables, registered on a srcgraph Graph
      trail.py              NEW: Trail, Step, build_trail()
      render/               NEW: text.py, html.py, json.py
      cli.py                adrgraph build | check | audit | query | explain | report | serve
    tests/
    docs/adr/               ADR-0001..0004 rewritten for the enforcer; ADR-0005 "adrgraph never
                            re-implements what srcgraph provides" is prose with scope; the direction
                            rule lives in srcgraph's repo
    docs/superpowers/
    mise.toml, .github/workflows/ci.yml, action.yml
```

**Installing without PyPI.** Until srcgraph is published, adrgraph's `srcgraph>=0.1` dependency
is satisfied from git: CI runs `pip install git+https://github.com/crunchdomo/srcgraph` before
`pip install -e .`; the f1 fork's pipx install becomes `pipx install --force <adrgraph wheel>
--pip-args "git+https://github.com/crunchdomo/srcgraph"`, or two wheels with `--find-links` on a
local srcgraph build. `action.yml`'s non-tag branch installs srcgraph from git then adrgraph from
the action path. Development: `pip install -e ~/Documents/srcgraph -e ~/Documents/adr-as-code`.

**Self-checks.** Each repo checks itself with the default root. In srcgraph the only ADR rule is
`never from {path: "srcgraph/**"} to {name: "adrgraph*"} via IMPORTS, transitive: true`, and its
negative control is planting `import adrgraph` into a srcgraph module. In adrgraph the existing
ADRs keep their rules with paths updated; ADR-0003 (ladybug only in graph.py) moves to srcgraph
since graph.py does. Neither repo scans the other.

## Decided: the schema-extension API

srcgraph's `Graph` owns the code tables (`Unit`, `Symbol`, `Ast`) and code rel tables. It accepts
extensions at construction:

```python
Graph(path, node_tables: dict[str, str] = {}, rel_tables: dict[str, tuple[list[tuple[str, str]], list[str]]] = {})
```

merged into its own definitions before the DDL runs. Loading becomes two generic methods plus
one convenience:

- `Graph.load_nodes(table: str, rows: list[dict]) -> None`
- `Graph.load_edges(edges: list[Edge], props: dict[str, dict] = {}) -> None` where `props` maps
  an edge's `(label, src, dst)` to extra property values when the label has properties beyond
  `line` (used for `CHILD.field`); endpoint tables resolved as today.
- `Graph.load_code(result: ScanResult) -> None` = units, symbols, ast, then all edges.

adrgraph's `schema.py` provides `ADR_NODE_TABLES`, `ADR_REL_TABLES` (`Decision`, `Rule`,
`HAS_RULE`, `SUPERSEDES`, `DEPENDS_ON`, `CONFLICTS_WITH`, `BINDS`) and
`load_adrs(graph, decisions) -> None`. `adrgraph build` is: open `Graph` with the extensions,
`load_code`, `load_adrs`, then the bind pass as today. `Graph.open(path)` is unchanged.

## Decided: what moves where

| Module | Goes to | Note |
|---|---|---|
| model, extractors/*, scan, graph, selectors | srcgraph | unchanged apart from the API above |
| adr, rules, check, audit, baseline | adrgraph | `rules.matched_ids`/`bound_ids` stay in adrgraph (they are rule semantics); `compile_selector` is srcgraph |
| cli | split | srcgraph gets `build`, `query`, `serve`; adrgraph keeps all of its commands and adds `explain`, `report`, `serve` |
| tests | by subject | the `layered` fixture lives in adrgraph's conftest (it tests rules); extractor/scan/graph/selector tests move with their modules |
| docs/adr | root | ADR-0001..0004 rewritten with the new paths; add ADR-0005: "adrgraph depends on srcgraph, never the reverse", enforced as `never from {path: "packages/srcgraph/**"} to {name: "adrgraph*"} via IMPORTS, transitive: true` |

## Decided: the trail

```python
@dataclass(frozen=True)
class Excerpt:            # source lines around a point of interest
    path: str
    start: int            # 1-based first line shown
    lines: list[str]
    highlight: int        # the line to mark

@dataclass(frozen=True)
class Step:
    kind: str             # "decision" | "rule" | "node" | "edge" | "path" | "syntax" | "context"
    title: str            # one line, e.g. "ADR-0004  Use PySide6 for menus and insights"
    detail: dict          # kind-specific facts, all JSON-serialisable
    excerpt: Excerpt | None

@dataclass(frozen=True)
class Trail:
    finding: Finding
    steps: tuple[Step, ...]

def build_trail(graph: Graph, decisions: list[Decision], finding: Finding, findings: list[Finding],
                baseline_path: str | None, read_source) -> Trail
```

`findings` is the whole check result, so the `context` step can say pass or fail for every other
decision bound to the same node without recomputing anything; `baseline_path` is the file the CLI
loaded, named in the `context` step when the finding is baselined. `read_source(path) ->
list[str]` is injected so `check.py` never imports a renderer or touches the filesystem.

Step order and content, for every shape:

1. `decision`: id, title, status, path to the ADR file; `detail.decision_text` is the first
   paragraph under a `## Decision` heading in the markdown, when present.
2. `rule`: id, shape, the spec as written (`detail.spec`), severity, portability.
3. `node`: the violating node: id, label, kind, path, line; `detail.why` is one sentence from the
   shape: for `only` "outside the `from` set and not excepted", for `never` "in the `from` set",
   for `must` "in the `every` set with no matching edge". Excerpt: 3 lines before and after
   `finding.line` (or the node's line).
4. For `only`/`never`: `edge` (label, line, target id and kind) for direct rules, or `path` (the
   `path_nodes`, each with its label and path) for transitive ones. For `must`: `edge` with
   `detail.missing = True` and the edges that do exist from the node with that label
   (`detail.existing`, capped at 10).
5. `syntax`: the `DERIVED_FROM` target of the violating node (id, kind, norm, line range), and
   for direct edge rules the syntax node of the edge's line when one exists under the node's
   subtree (an `Import` for imports, a `Call` for calls).
6. `context`: other accepted decisions whose rules or scope bind the same node
   (`detail.governed_by`: list of ids and a pass/fail word), and `detail.baselined` with the
   baseline file path when the finding is baselined.

Raw `cypher` rules produce steps 1, 2, 3 and 6 only. A `fixed` finding (its node is gone)
produces steps 1, 2 and 6, with `detail.fixed = True` on the rule step. `baselined` findings get
the full trail; the `context` step carries `baselined: true` and the baseline path. `report`
shows every finding `check` prints, at every severity, so its count always matches `check`.

## Decided: renderers

- `render/text.py`: `render_text(trail: Trail) -> str`. Fixed-width layout close to the mockup:
  decision and rule lines, the excerpt with the highlighted line marked `│` and an arrow note,
  then the edge or path, then `derived from`, then context. No colour codes in the string;
  the CLI adds ANSI colour only when stdout is a TTY.
- `render/html.py`: `render_html(trails: list[Trail], decisions, metrics, binds) -> str`. One
  self-contained page (inline CSS, no scripts): a summary table (per-ADR compliance, counts by
  severity), the findings as vertical trails in the mockup's style, then one section per ADR
  with its status, rules, portability, and the files and symbols it binds to.
- `trail.py`: `trail_dict(trail: Trail) -> dict`, plain `dataclasses.asdict` plus
  `finding` flattened. Used by `check --format json --trails` and by the explorer overlay.

## Decided: the CLI additions

- `adrgraph explain <path>:<line> [<decision-id>]`: builds (as `check` does), evaluates, picks
  the findings at that path and line (all decisions, or the one named), prints a trail for
  each. Exit 0 if a finding was found and explained, 1 if none matched, 2 on error.
  `adrgraph explain <decision-id>/<rule-id>` explains every finding of that rule.
- `adrgraph report [-o PATH]`: default `.adrgraph/report.html`; prints the path written.
- `adrgraph check --trails` with `--format json`: each finding carries `trail`.
- `srcgraph build | query`: same as adrgraph's today, without ADR tables. srcgraph's default
  database path is `.srcgraph/graph.lbug` and `.srcgraph` joins `DEFAULT_EXCLUDES`; adrgraph keeps
  `.adrgraph/graph.lbug`.
- `srcgraph serve [--src ...] [--db] [--port 8765] [--no-build]`: builds (exactly as `build` does)
  then serves the explorer and prints the URL; `--no-build` opens the existing database instead.
  The server opens the database read-only, so a concurrent `build` fails loudly rather than
  corrupting it.
- `adrgraph serve`: builds as `check` does (ADRs and the bind pass included), evaluates, then
  serves srcgraph's explorer with the findings overlay routes mounted. Same flags.

## Decided: the explorer

`serve.py` is the stdlib `http.server` with a handler class. Routes, all GET, all JSON unless
noted:

- `/` → `explorer.html`
- `/api/search?q=` → up to 50 Units and Symbols whose `name`, `qualified` or `path` contains `q`
- `/api/node/<id>` → the node's properties and label
- `/api/neighbors/<id>?labels=IMPORTS,CALLS&direction=both&limit=100` → nodes and edges one hop out
- `/api/subtree/<id>?depth=2` → syntax children of an `Ast` node (or of a Symbol's `DERIVED_FROM` target)
- `/api/source?path=&from=&to=` → lines of a file under the source root (path must resolve
  inside the root; anything else is 403)
- `/api/query` (POST, body `{"cypher": ...}`) → rows; refused unless the server was started with
  `--allow-query`, since raw Cypher can mutate the graph

The overlay (`adrgraph serve`) adds `/api/findings` (the current check result with trails) and
`/api/decisions` (decisions with their binds), and the page shows a findings list and colours
violating nodes.

`explorer.html`: one page, three regions: a search box with results, the graph canvas (SVG,
force layout via `d3` from a pinned cdnjs URL, nodes coloured by label, edges labelled, click a
node to select, double-click to expand its neighbours, a label filter), and a detail panel
(properties, governed-by when the overlay is present, the source excerpt, a "syntax tree"
button that expands the subtree into the canvas). No framework.

## Acceptance

In the f1 fork, with both packages installed:

- `adrgraph check` and `adrgraph audit` print exactly what 0.2.0 printed; the baseline is
  untouched and the pre-push hook passes.
- `adrgraph explain src/services/stream.py:9` prints a trail whose excerpt shows line 9
  highlighted and whose edge step names `PySide6.QtCore`.
- `adrgraph explain src/insights/telemetry_stream_viewer.py:13` prints a `must` trail whose
  edge step says the `INHERITS` edge to `*PitWallWindow` is missing and lists the existing
  edge to `PySide6.QtWidgets.QMainWindow`.
- `adrgraph report` writes a page with 5 findings and 7 ADR sections.
- `srcgraph serve` on the fork builds `.srcgraph/graph.lbug` and opens the explorer; searching
  `stream` finds the unit; expanding it shows its five imports; the detail panel shows line 9 in
  the excerpt. `adrgraph serve` additionally lists
  the 5 findings and colours `stream.py` red.

In each repository: its test suite passes and `adrgraph check` on it is at 100%; in srcgraph,
planting `import adrgraph` into a srcgraph module makes its ADR-0001 fail.

## Known ceilings

- `explain` rebuilds the graph each time, like `check`. Fine at f1 scale (3 s); a `--db` reuse
  flag is the upgrade when it isn't.
- The explorer's force layout is client-side and comfortable to a few hundred visible nodes;
  expansion is capped at 100 neighbours per click for that reason.
- `decision_text` extraction is a heading heuristic (`## Decision`); ADRs with other headings
  get no excerpt, never an error.

## Left to the builder

- Exact `pyproject.toml` contents for both packages and how `python -m build` is run per package.
- The `source.py` reader's caching and encoding fallback.
- JSON API error shapes and the 403 path check implementation.
- The `d3` version to pin and the explorer's visual details beyond the three regions.
- How `check --trails` threads `read_source` through without `check.py` importing the renderer.
- Test fixtures for trails: the `layered` graph plus a tiny on-disk source tree in `tmp_path`.
