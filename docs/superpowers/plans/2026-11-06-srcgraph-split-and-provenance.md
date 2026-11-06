# srcgraph split and provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split adrgraph into two repositories (srcgraph: code to graph; adrgraph: ADR enforcer on top), and give the enforcer a provenance trail with terminal (`explain`) and HTML (`report`) renderers.

**Architecture:** The code-graph modules move verbatim into a new `srcgraph` package with a schema-extension API on `Graph` so adrgraph can add its `Decision`/`Rule` tables without srcgraph knowing them. adrgraph keeps rules, check, audit and baseline, adds `schema.py` (its tables), `trail.py` (one `Trail` model built from the graph and the check result) and `render/` (text, html, json). The explorer is a separate plan.

**Tech Stack:** unchanged (Python 3.11+, ladybug 0.22.1, tree-sitter 0.26 + python/hcl grammars, python-frontmatter, pytest). No new dependencies in either package.

**Spec:** `docs/superpowers/specs/2026-11-06-srcgraph-split-and-provenance-design.md`

## Global Constraints

- Two repositories: `~/Documents/srcgraph` (new, `crunchdomo/srcgraph`, created private) and `~/Documents/adr-as-code` (`crunchdomo/adrgraph`). Nothing in srcgraph imports `adrgraph`, not even tests.
- No new Python dependencies. srcgraph depends on ladybug, tree-sitter, tree-sitter-python, tree-sitter-hcl; adrgraph depends on srcgraph and python-frontmatter.
- adrgraph 0.2.0 behaviour is the compatibility bar: `build`, `check`, `audit`, `query` print the same output with the same exit codes; the f1 fork's ADRs, baseline and hook work unedited.
- srcgraph's default database is `.srcgraph/graph.lbug` and `.srcgraph` joins `DEFAULT_EXCLUDES`; adrgraph keeps `.adrgraph/graph.lbug`.
- Trails never recompute: `build_trail` only reads the graph, the decisions, the findings list, the baseline path and source files.
- Renderer strings contain no ANSI codes; the CLI adds colour only when stdout is a TTY.
- All 105 existing tests keep passing, relocated with their modules.

## Review Focus

1. A source file deleted after the graph was built: `explain` must print the trail with "source unavailable" in place of the excerpt, never a traceback. Test in Task 4 (`test_trail_without_source`).
2. An ADR with no `## Decision` heading: the decision step has no `decision_text`, and nothing errors. Test in Task 4 (`test_decision_text_absent_is_fine`).
3. `explain` on a path:line with no finding: exit 1 with a one-line message, not an empty success. Test in Task 5 (`test_explain_no_match_exits_1`).
4. A `must` violation whose node has no edges of the rule's label at all: the edge step says the edge is missing and `existing` is empty. Test in Task 4 (`test_must_trail_with_no_existing_edges`).
5. The report with zero findings: a page is still written with the ADR sections and "no findings". Test in Task 6 (`test_report_with_no_findings`).

---

## File structure

```
~/Documents/srcgraph/                      new repository
  pyproject.toml  LICENSE  README.md  mise.toml  .gitignore  .github/workflows/ci.yml
  srcgraph/__init__.py  model.py  extractors/{__init__,lines,syntax,python,terraform}.py  scan.py  graph.py  selectors.py  source.py  cli.py
  tests/  (test_model, test_selectors, test_extract_python, test_extract_terraform, test_scan, test_graph, test_source, test_cli; fixtures/pyrepo (sources only), fixtures/tf)
  docs/adr/0001-never-import-adrgraph.md

~/Documents/adr-as-code/                   this repository
  adrgraph/__init__.py  adr.py  rules.py  check.py  audit.py  baseline.py  schema.py  trail.py  render/{__init__,text,html,json}.py  cli.py
  tests/  (test_adr, test_rules, test_check, test_audit, test_cli, test_schema, test_trail, test_render; conftest layered; fixtures/pyrepo incl. docs/adr, fixtures/adr)
  docs/adr/  (0001, 0002, 0004, 0005 updated; 0003 removed, moved to srcgraph as prose)
```

---

### Task 1: srcgraph repository with the moved modules and the schema-extension API

**Files:**
- Create (in `~/Documents/srcgraph`): `pyproject.toml`, `LICENSE`, `.gitignore`, `mise.toml`, `README.md`, `srcgraph/__init__.py`, `srcgraph/model.py`, `srcgraph/extractors/*`, `srcgraph/scan.py`, `srcgraph/graph.py`, `srcgraph/selectors.py`, `tests/*` (moved), `tests/fixtures/pyrepo/src/**`, `tests/fixtures/tf/main.tf`
- Test: `tests/test_graph.py` (moved plus new extension tests)

**Interfaces:**
- Produces, in `srcgraph/graph.py`:
  - `Graph(path: str, node_tables: dict[str, str] = {}, rel_tables: dict[str, tuple[list[tuple[str, str]], list[str]]] = {})`. Own tables: `Unit`, `Symbol`, `Ast`; own rels: `CONTAINS`, `IMPORTS`, `CALLS`, `REFERENCES`, `INHERITS`, `DECORATES`, `READS`, `WRITES`, `TYPE_OF`, `OVERRIDES`, `DERIVED_FROM`, `CHILD`, `NEXT` (same pairs and props as today). Extensions are merged before DDL; an extension that reuses an own table name raises `ValueError`.
  - `Graph.load_nodes(table: str, rows: list[dict]) -> None`: COPY FROM as today; rows must have every column of the table.
  - `Graph.load_edges(edges: list[Edge], props: dict[tuple[str, str, str], dict] = {}) -> None`: endpoints resolved against every node table (own and extension) as today; `line` from `Edge.line`; other props from `props[(label, src, dst)]`.
  - `Graph.load_code(result: ScanResult) -> None`: `load_nodes("Unit", ...)` with `line: 1`, `load_nodes("Symbol", ...)`, `load_nodes("Ast", ...)`, then `load_edges(result.edges + result.ast_edges, props)` where `props` supplies `CHILD.field` from the child `AstNode.field`.
  - `Graph.open`, `query`, `count`, `close`, context manager: unchanged. `escape` unchanged. `rule_key` moves to adrgraph (`schema.py`).
- Produces: `srcgraph.model` identical to `adrgraph.model` today; `srcgraph.scan.DEFAULT_EXCLUDES` gains `".srcgraph"`.
- Everything else moves verbatim with `adrgraph.` → `srcgraph.` in imports.

- [ ] **Step 1: Scaffold the repository and copy the modules**

`git init ~/Documents/srcgraph` on branch `main`. `pyproject.toml`: name `srcgraph`, version from `srcgraph.__version__` (`"0.1.0"`), `requires-python >=3.11`, dependencies `ladybug==0.22.1`, `tree-sitter==0.26.0`, `tree-sitter-python==0.25.0`, `tree-sitter-hcl==1.2.0`, dev extra `pytest>=8`, script `srcgraph = "srcgraph.cli:main"`, setuptools find `srcgraph*`, pytest `testpaths=["tests"]`, `pythonpath=["."]`. `LICENSE` MIT (copy). `.gitignore`: `.srcgraph/*.lbug`, `.srcgraph/*.wal`, `.venv/`, `__pycache__/`, `*.egg-info/`, `dist/`, `build/`, `.superpowers/`, `.DS_Store`. `mise.toml`: python 3.12, tasks `test = "pytest"`, `check = "adrgraph check"`. Copy `model.py`, `extractors/`, `scan.py`, `graph.py`, `selectors.py` and the tests named in the file structure, rewriting imports with `sed -i '' 's/adrgraph\./srcgraph./g; s/from adrgraph /from srcgraph /g'`. Copy `tests/fixtures/pyrepo/src` and `tests/fixtures/tf`. Create `.venv` and `pip install -e '.[dev]'`.

- [ ] **Step 2: Write the failing tests** (replace the Decision/Rule/BINDS tests in the moved `tests/test_graph.py` with these; the moved file must not import adrgraph)

```python
def test_extension_tables_and_generic_loads(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"),
              node_tables={"Decision": "id STRING, title STRING, PRIMARY KEY(id)"},
              rel_tables={"BINDS": ([("Decision", "Unit")], [])})
    g.load_nodes("Unit", [{"id": "a.py", "path": "a.py", "name": "a", "lang": "python", "kind": "file", "line": 1}])
    g.load_nodes("Decision", [{"id": "ADR-1", "title": "t"}])
    g.load_edges([Edge("BINDS", "ADR-1", "a.py")])
    assert g.query("MATCH (d:Decision)-[:BINDS]->(u:Unit) RETURN d.id AS d, u.id AS u") == [{"d": "ADR-1", "u": "a.py"}]
    g.close()

def test_extension_cannot_shadow_own_table(tmp_path):
    with pytest.raises(ValueError, match="Unit"):
        Graph(str(tmp_path / "g.lbug"), node_tables={"Unit": "id STRING, PRIMARY KEY(id)"})

def test_load_code_sets_child_field(tmp_path, monkeypatch):
    from srcgraph.scan import scan
    monkeypatch.chdir("tests/fixtures/pyrepo")
    g = Graph(str(tmp_path / "g.lbug"))
    g.load_code(scan(["."]))
    assert g.count("Ast") > 100
    assert g.query("MATCH (:Ast {kind:'class_definition'})-[c:CHILD]->(n:Ast {kind:'identifier'}) WHERE c.field = 'name' RETURN n.text AS t ORDER BY t")[0]["t"] == "Base"
    g.close()
```

Keep `test_load_and_query`, `test_reopen_is_fresh`, `test_edge_line_property`, `test_ast_tier_and_derived_from`, `test_text_with_newlines_survives_copy`, `test_repeated_load_appends`, `test_empty_strings_load_as_empty_not_null`, `test_binds_can_be_loaded_after_nodes` rewritten to the new API (`load_nodes`/`load_edges`; the BINDS one becomes a `CALLS` edge loaded in a later call).

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd ~/Documents/srcgraph && .venv/bin/pytest -q`
Expected: the graph tests FAIL on the new signatures; everything else (moved tests) passes.

- [ ] **Step 4: Rewrite `graph.py` per Interfaces**

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (about 75 tests).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: srcgraph — code-to-graph package extracted from adrgraph 0.2.0 (commit 7bb15f4)"
```

---

### Task 2: srcgraph CLI, self-ADR, CI, GitHub repository

**Files:**
- Create (srcgraph): `srcgraph/cli.py`, `tests/test_cli.py`, `docs/adr/0001-never-import-adrgraph.md`, `docs/adr/0002-ladybugdb-as-graph-store.md`, `.github/workflows/ci.yml`, `README.md` (real content)

**Interfaces:**
- `srcgraph.cli.main(argv) -> int` with subcommands `build` and `query`, flags as adrgraph's today minus `--adr`; `--db` default `.srcgraph/graph.lbug`. `build` prints `built <db>: N units, N symbols, N syntax nodes`. Exit 2 on `SelectorError`/`RuntimeError` with `error: ...` on stderr.
- `srcgraph.cli.build(src_roots, excludes, db_path) -> tuple[Graph, list[str]]` (graph, warnings).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import pytest
from srcgraph.cli import main

def run(capsys, *args):
    code = main(list(args)); out = capsys.readouterr(); return code, out.out, out.err

def test_build_and_query(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir("tests/fixtures/pyrepo")
    db = str(tmp_path / "g.lbug")
    code, out, _ = run(capsys, "build", "--db", db)
    assert code == 0 and "syntax nodes" in out
    code, out, _ = run(capsys, "query", "--db", db, "MATCH (u:Unit {kind:'external'}) RETURN u.name AS n ORDER BY n")
    assert code == 0 and out.splitlines()[0] == "n" and "logging" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL (`srcgraph.cli` missing).

- [ ] **Step 3: Implement `cli.py`** (copy adrgraph's `build`/`query` branches; drop ADR handling), the two ADRs, `ci.yml`, README

`0001-never-import-adrgraph.md`: `status: accepted`, rule `never-import-adrgraph`: `never from {path: "srcgraph/**"} to {name: "adrgraph*"} via IMPORTS, transitive: true`; prose: adrgraph is a dev-only tool here. `0002-ladybugdb-as-graph-store.md`: the text of adrgraph's ADR-0003 with paths updated (`srcgraph/graph.py`), rule `ladybug-only-in-graph`. `ci.yml`: setup Python 3.12, `pip install -e '.[dev]'`, `pytest`, then `pip install git+https://github.com/crunchdomo/adrgraph` and `adrgraph check` and `adrgraph audit --strict` (these two steps are `continue-on-error: true` until adrgraph 0.3.0 is on main, and flipped in Task 7). README: what srcgraph is, install, `build`/`query`, the graph section and queries from adrgraph's README, adding a language.

- [ ] **Step 4: Run the suite and the negative control**

Run: `.venv/bin/pytest -q && printf 'import adrgraph\n' >> srcgraph/selectors.py && (/Users/oenfadam/Documents/adr-as-code/.venv/bin/python -m adrgraph.cli check --adr docs/adr 2>/dev/null | head -1); git checkout srcgraph/selectors.py`
Expected: tests pass; the check line names `srcgraph/selectors.py` with `ADR-0001/never-import-adrgraph` (adrgraph 0.2.0 from the adr-as-code venv can scan this repo today because it only needs source files).

- [ ] **Step 5: Create the GitHub repository and push**

Run: `gh repo create srcgraph --private --source=. --remote=origin --description "Source code in, a queryable two-tier knowledge graph out" --push`
Expected: `main` pushed to `crunchdomo/srcgraph`. (If creating the repo is refused by the permission classifier as it was for adrgraph, stop and ask the user to run that one command.)

- [ ] **Step 6: Commit** (the commit precedes the push in Step 5; nothing further)

---

### Task 3: adrgraph consumes srcgraph

**Files:**
- Delete (adrgraph): `adrgraph/model.py`, `adrgraph/extractors/`, `adrgraph/scan.py`, `adrgraph/graph.py`, `adrgraph/selectors.py`, `tests/test_model.py`, `tests/test_selectors.py`, `tests/test_extract_python.py`, `tests/test_extract_terraform.py`, `tests/test_scan.py`, `tests/fixtures/tf/`
- Create: `adrgraph/schema.py`, `tests/test_schema.py`
- Modify: `pyproject.toml`, `adrgraph/__init__.py` (`0.3.0`), `adrgraph/adr.py` (no change expected), `adrgraph/rules.py`, `adrgraph/check.py`, `adrgraph/audit.py`, `adrgraph/cli.py`, `tests/conftest.py`, `tests/test_graph.py` → folded into `tests/test_schema.py`, `.github/workflows/ci.yml`, `docs/adr/*`, `mise.toml`

**Interfaces:**
- `adrgraph/schema.py`:
  - `ADR_NODE_TABLES = {"Decision": "...", "Rule": "..."}` (today's DDL), `ADR_REL_TABLES = {"HAS_RULE": ..., "SUPERSEDES": ..., "DEPENDS_ON": ..., "CONFLICTS_WITH": ..., "BINDS": ([("Rule","Unit"),("Rule","Symbol"),("Decision","Unit"),("Decision","Symbol")], [])}`.
  - `rule_key(decision_id, rule_id) -> str`.
  - `open_graph(path: str) -> Graph` = `Graph(path, node_tables=ADR_NODE_TABLES, rel_tables=ADR_REL_TABLES)`.
  - `load_adrs(graph: Graph, decisions: list[Decision]) -> None`: `load_nodes` for Decision and Rule rows (as `graph.py` builds them today), then `load_edges` for HAS_RULE, SUPERSEDES, DEPENDS_ON, CONFLICTS_WITH.
- `cli.build(adr_dirs, src_roots, excludes, db_path)`, in order: `graph = open_graph(db_path)`; `graph.load_code(scan(src_roots, excludes))`; `load_adrs(graph, decisions)`; the bind pass as `graph.load_edges([Edge("BINDS", key, node) ...])`. Same return value as today.
- `pyproject.toml`: dependencies `srcgraph>=0.1`, `python-frontmatter==1.3.0`; the tree-sitter and ladybug pins are removed (they come through srcgraph).
- Imports everywhere: `from srcgraph.model import ...`, `from srcgraph.graph import Graph`, `from srcgraph.selectors import compile_selector, SelectorError`, `from srcgraph.scan import scan, DEFAULT_EXCLUDES`.

- [ ] **Step 1: Install srcgraph into adrgraph's venv and write the failing tests**

Run: `cd ~/Documents/adr-as-code && .venv/bin/pip install -e ~/Documents/srcgraph`

`tests/test_schema.py`: the four Decision/Rule/BINDS graph tests from today's `tests/test_graph.py` (`test_load_and_query` parts about Rule and BINDS, `test_binds_can_be_loaded_after_nodes`, `test_decision_relations_and_scope_binds`) rewritten against `open_graph` + `load_adrs` + `load_edges`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: FAIL (`adrgraph.schema` missing).

- [ ] **Step 3: Delete the moved modules, add `schema.py`, rewrite imports and `cli.build`, update `pyproject.toml`, `conftest.py`, `__init__.py`**

- [ ] **Step 4: Run the suite, the self-check, and the compatibility check on the f1 fork**

Run: `.venv/bin/pytest -q && .venv/bin/python -m adrgraph.cli check --exclude tests/fixtures | head -1 && cd ~/Documents/f1-race-replay && PYTHONPATH=/Users/oenfadam/Documents/adr-as-code:/Users/oenfadam/Documents/srcgraph /Users/oenfadam/Documents/adr-as-code/.venv/bin/python -m adrgraph.cli check --db /tmp/compat.lbug > /tmp/compat-new.txt; adrgraph check --db /tmp/compat-old.lbug > /tmp/compat-old.txt; diff /tmp/compat-old.txt /tmp/compat-new.txt && echo IDENTICAL`
Expected: about 35 tests pass; self-check `overall compliance: 100.0%` (after Step 5's ADR path updates; run again then); `IDENTICAL` (the pipx install is still 0.2.0, which is the point).

- [ ] **Step 5: Update the ADRs, CI, mise**

`docs/adr`: delete `0003-ladybugdb-as-graph-store.md` (it moved to srcgraph). Rewrite ADR-0001 as "adrgraph never imports tree-sitter or ladybug directly", two rules: `never from {path: "adrgraph/**"} to {name: "tree_sitter*"} via IMPORTS` and `never from {path: "adrgraph/**"} to {name: "ladybug"} via IMPORTS`. ADR-0002 keeps its three rules (the `adrgraph/extractors/**` target no longer exists, so change `to` to `{name: "srcgraph.extractors*"}`; the intent, "the engine never reaches extractors", is unchanged). ADR-0004 unchanged. Add ADR-0005 "adrgraph depends on srcgraph for everything graph-shaped", no rules, `scope: [{path: "adrgraph/schema.py"}, {path: "adrgraph/cli.py"}]`, `depends_on: [ADR-0002]`. Ids stay stable; the gap at 0003 is fine. `ci.yml`: `pip install git+https://github.com/crunchdomo/srcgraph` before `pip install -e '.[dev]'`. `mise.toml` unchanged.

- [ ] **Step 6: Run the suite and self-check again**

Run: `.venv/bin/pytest -q && .venv/bin/python -m adrgraph.cli check --exclude tests/fixtures | head -1 && .venv/bin/python -m adrgraph.cli audit --strict --exclude tests/fixtures`
Expected: pass; 100%; audit clean, `5 rules: 5 semantic, 0 normalised, 0 grammar`.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: adrgraph depends on srcgraph; code-graph modules removed"
```

---

### Task 4: `source.py`, the trail model and `build_trail`, JSON renderer

**Files:**
- Create (srcgraph): `srcgraph/source.py`, `tests/test_source.py`
- Create (adrgraph): `adrgraph/trail.py`, `adrgraph/render/__init__.py`, `adrgraph/render/json.py`, `tests/test_trail.py`

**Interfaces:**
- `srcgraph/source.py`: `class Source: __init__(self, root: str = "."); lines(self, path: str) -> list[str] | None` (None when the file is missing or unreadable; decoded UTF-8 with replacement; cached per path).
- `adrgraph/trail.py`: `Excerpt`, `Step`, `Trail` exactly as the spec; `build_trail(graph: Graph, decisions: list[Decision], finding: Finding, findings: list[Finding], baseline_path: str | None, read_source: Callable[[str], list[str] | None]) -> Trail`; `decision_text(markdown: str) -> str | None` (first paragraph after a line matching `^##\s+Decision\s*$`, stripped; None otherwise); `EXCERPT_CONTEXT = 3`.
- Step contents per the spec's numbered list. `detail` keys, fixed: decision: `id`, `title`, `status`, `path`, `decision_text`; rule: `id`, `shape`, `spec`, `severity`, `portability`, `fixed` (bool); node: `id`, `label`, `kind`, `path`, `line`, `why`; edge: `label`, `line`, `target_id`, `target_kind`, `missing` (bool), `existing` (list of `{target_id, target_kind, line}`); path: `nodes` (list of `{id, label, path}`); syntax: `id`, `kind`, `norm`, `line`, `end_line`, plus optional `edge_syntax` (`{id, kind, norm, line}`); context: `governed_by` (list of `{decision, result}` with result `"fails"`/`"passes"`), `baselined` (bool), `baseline_path`.
- `render/json.py`: `trail_dict(trail: Trail) -> dict` = `dataclasses.asdict(trail)` with `finding` left as a flat dict.
- `why` sentences, fixed: only → `"outside the from set and not excepted"`; never → `"in the from set"`; must → `"in the every set with no matching edge"`; cypher → `"returned by the rule's query"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_source.py` (srcgraph): `lines()` returns the lines of a file under `root`, `None` for a missing file, and caches (second call after deleting the file still returns lines).

`tests/test_trail.py` (adrgraph), using `layered` and `tmp_path` with files `src/handlers/h.py` (10 lines, line 3 is `import c`) etc. written by a fixture `source_tree`:
```python
def test_only_trail_steps(layered, source_tree):
    d = dec("ADR-1", "accepted", [ONLY]); d.path = str(source_tree / "ADR-1.md")   # file with "## Decision\n\nGateway via contracts.\n"
    result = run_check(layered, [d], set())
    f = result.findings[0]
    t = build_trail(layered, [d], f, result.findings, None, lambda p: (source_tree / p).read_text().splitlines() if (source_tree / p).exists() else None)
    kinds = [s.kind for s in t.steps]
    assert kinds == ["decision", "rule", "node", "edge", "syntax", "context"] or kinds == ["decision", "rule", "node", "edge", "context"]
    assert t.steps[0].detail["decision_text"] == "Gateway via contracts."
    assert t.steps[2].detail["why"] == "outside the from set and not excepted"
    assert t.steps[2].excerpt.highlight == 1 and t.steps[2].excerpt.lines[0].startswith("from src.gateway")
    assert t.steps[3].detail["target_id"] == "src/gateway/client.py" and t.steps[3].detail["missing"] is False

def test_transitive_trail_has_path_step(layered, source_tree): ...  # NEVER_T: a "path" step with 3 nodes, no "edge" step

def test_must_trail_with_no_existing_edges(layered, source_tree): ...  # must every function has log.py via INHERITS: edge step missing=True, existing == []

def test_trail_without_source(layered, source_tree): ...  # read_source returns None: node step excerpt is None, no exception

def test_decision_text_absent_is_fine(layered, source_tree): ...  # ADR file without "## Decision": decision_text is None

def test_context_lists_other_decisions_and_baseline(layered, source_tree): ...  # two decisions binding src/other/x.py: governed_by has both with pass/fail; baselined finding -> baselined True and path

def test_fixed_finding_trail(layered, source_tree): ...  # a Finding with severity "fixed": steps decision, rule(fixed=True), context

def test_trail_dict_roundtrip(layered, source_tree): ...  # json.dumps(trail_dict(t)) works and has "steps"
```
(Write each `...` out in full in the test file; the assertions are the ones described in the comment.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Documents/srcgraph && .venv/bin/pytest tests/test_source.py -v; cd ~/Documents/adr-as-code && .venv/bin/pytest tests/test_trail.py -v`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `source.py` (srcgraph), then `trail.py` and `render/json.py` (adrgraph)**

Queries `build_trail` runs, each parameterised by id: the violating node's properties (`MATCH (n) WHERE n.id = $id RETURN label(n), n`), its `DERIVED_FROM` target, for direct rules the edge `MATCH (a)-[r:LABEL]->(b) WHERE a.id = $id AND b.id = $target RETURN r.line`, for `must` the existing edges `MATCH (a)-[r:LABEL]->(b) WHERE a.id = $id RETURN b.id, label(b), r.line LIMIT 10`, the syntax node on the edge line `MATCH (n {id:$id})-[:DERIVED_FROM]->(root)-[:CHILD*1..3]->(x:Ast) WHERE x.line = $line AND x.norm IN ['Import','Call'] RETURN x LIMIT 1`, and the other decisions bound to the node `MATCH (d:Decision)-[:BINDS]->(n {id:$id}) RETURN d.id` plus `MATCH (r:Rule)-[:BINDS]->(n {id:$id}) RETURN r.decision`. Pass/fail per other decision comes from `findings` (any error/warn/baselined finding with that decision and this node id → fails).

- [ ] **Step 4: Run both suites**

Run: `cd ~/Documents/srcgraph && .venv/bin/pytest -q; cd ~/Documents/adr-as-code && .venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit both repositories**

```bash
cd ~/Documents/srcgraph && git add -A && git commit -m "feat: Source reader for excerpts" && git push
cd ~/Documents/adr-as-code && git add -A && git commit -m "feat: provenance trails and JSON renderer"
```

---

### Task 5: text renderer and `adrgraph explain`

**Files:**
- Create (adrgraph): `adrgraph/render/text.py`, `tests/test_render.py`
- Modify: `adrgraph/cli.py`, `tests/test_cli.py`

**Interfaces:**
- `render_text(trail: Trail) -> str`. Layout, fixed:
  ```
  ADR-0004  Use PySide6 for menus and insights            docs/adr/0004-....md
    Decision: "<decision_text>"                                     (omitted when None)
    rule pyside-only-in-ui   only {from...} may reach {to...} via IMPORTS   [error, semantic]
         except [...]                                                       (when present)

  violates  src/services/stream.py:9   (outside the from set and not excepted)
     7 │ import threading
     8 │ import time
     9 │ from PySide6.QtCore import QThread, Signal      ← IMPORTS → PySide6.QtCore (external)
    10 │

  derived from  Ast import_from_statement  src/services/stream.py#467:509  norm=Import
  also governed by  ADR-0005 (passes)
  baselined  yes  (.adrgraph/baseline.json)
  ```
  Transitive: the `violates` block is followed by `path  a -> b -> c` lines, one node per line with its label. `must`: `missing  INHERITS → {has selector}` then `existing  INHERITS → X (line N)` lines or `existing  none`. Source unavailable: `(source unavailable)` in place of the excerpt. The highlighted line is the only one with the arrow note.
- CLI: `adrgraph explain TARGET [--adr] [--src] [--exclude] [--db] [--baseline] [--format text|json]` where TARGET is `path:line` or `path:line ADR-ID` or `ADR-ID/rule-id`. Exit 0 when at least one trail printed, 1 when nothing matched (`no finding at <target>` on stderr), 2 on error. `--format json` prints a list of `trail_dict`s. Colour: when `sys.stdout.isatty()`, the `violates` line and the highlighted source line are wrapped in red (`\x1b[31m` ... `\x1b[0m`).

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`: `test_render_text_only_trail` asserting the exact lines `ADR-1  t`, `violates  src/other/x.py:1   (outside the from set and not excepted)`, a line ending in `← IMPORTS → src/gateway/client.py`, and `derived from  Ast`; `test_render_text_transitive_has_path_lines`; `test_render_text_source_unavailable`.

`tests/test_cli.py` additions (pyrepo fixture): `test_explain_path_line` (`explain src/other/x.py:1` exits 0; assert `"rule gateway-only-via-contracts" in out` and `"from src.gateway import client" in out`), `test_explain_rule_form` (`explain ADR-0001/no-handler-calls-db` exits 0 and prints a `path` line naming `src.db.q.run`), `test_explain_no_match_exits_1` (`explain src/other/x.py:99` → 1, stderr `no finding at`), `test_explain_json` (`--format json` parses to a list with one trail whose `steps[0]["kind"] == "decision"`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_render.py tests/test_cli.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement `render/text.py` and the `explain` subcommand** (`cli._run` gains an `explain` branch that builds like `check`, runs `run_check`, filters findings by target, builds trails with `Source(".").lines`, renders)

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add adrgraph/render/text.py adrgraph/cli.py tests/test_render.py tests/test_cli.py
git commit -m "feat: adrgraph explain — provenance trail in the terminal"
```

---

### Task 6: HTML renderer, `adrgraph report`, `check --trails`

**Files:**
- Create: `adrgraph/render/html.py`
- Modify: `adrgraph/cli.py`, `adrgraph/check.py` (no change expected), `tests/test_render.py`, `tests/test_cli.py`

**Interfaces:**
- `render_html(trails: list[Trail], decisions: list[Decision], metrics: Metrics, binds: dict[str, list[str]]) -> str` where `binds` maps decision id → node ids (rule binds and scope binds merged). One self-contained page: `<title>adrgraph report</title>`, inline CSS only, no `<script>`. Sections in order: summary table (per ADR: id, title, status, compliance, counts by severity), findings (one `<section class="finding">` per trail, severity badge, the steps as an ordered list with the excerpt in `<pre>` and the highlighted line in `<mark>`), ADRs (one `<section class="adr">` per decision: status, rules with shape and portability, "binds" list of node ids capped at 200 with a count). With no trails the findings section contains `<p>no findings</p>`.
- CLI: `adrgraph report [-o PATH]` default `.adrgraph/report.html`; builds like `check`, runs `run_check` with the baseline, builds trails for every finding, writes the page, prints `wrote <path> (<n> findings)`; exit 0 always unless error. `adrgraph check --trails` (only with `--format json`) adds `"trail": trail_dict(...)` to each finding; without `--format json` it is an argparse error.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`: `test_render_html_structure` (contains `<title>adrgraph report</title>`, no `<script`, one `class="finding"` per trail, a `<mark>` with the highlighted source line, one `class="adr"` per decision); `test_report_with_no_findings` (`render_html([], [d], metrics, {})` contains `no findings` and still the ADR section).

`tests/test_cli.py`: `test_report_writes_page` (pyrepo: `report -o <tmp>/r.html` exits 0, prints `wrote`, file contains `ADR-0001` and `class="finding"`); `test_check_trails_json` (`check --format json --trails` → every finding has `trail.steps`); `test_check_trails_requires_json` (`check --trails` without json → exit 2).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_render.py tests/test_cli.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add adrgraph/render/html.py adrgraph/cli.py tests
git commit -m "feat: adrgraph report and check --trails"
```

---

### Task 7: wiring across repositories, README, acceptance on the f1 fork

**Files:**
- Modify (adrgraph): `README.md`, `action.yml`, `.github/workflows/ci.yml`
- Modify (srcgraph): `.github/workflows/ci.yml` (drop `continue-on-error`)
- Outside: the f1 fork's pipx install

- [ ] **Step 1: README and action**

adrgraph README: a "two projects" paragraph at the top pointing at srcgraph; the graph section moves to srcgraph's README and is replaced by a link; new sections for `explain`, `report`, `--trails`; the "local only" and baseline sections unchanged. `action.yml`: the non-tag branch becomes `pip install git+https://github.com/crunchdomo/srcgraph "${{ github.action_path }}"`.

- [ ] **Step 2: Push adrgraph, flip srcgraph CI**

Run: `cd ~/Documents/adr-as-code && git push && gh run watch $(gh run list --limit 1 --json databaseId -q '.[0].databaseId') --exit-status`
Expected: adrgraph CI green. If `pip install git+https://github.com/crunchdomo/srcgraph` fails with an auth error because srcgraph is private, stop and ask the user to make srcgraph public (`gh repo edit crunchdomo/srcgraph --visibility public`) or add a PAT; CI cannot read another private repo with its default token.
Then in srcgraph: remove `continue-on-error`, commit `ci: enforce the no-adrgraph-import ADR`, push, watch, expect green.

- [ ] **Step 3: Install into the fork and run the acceptance**

Run (in `~/Documents/srcgraph` then `~/Documents/adr-as-code`): `python -m build --wheel -o dist` in both; then `pipx install --force ~/Documents/adr-as-code/dist/adrgraph-0.3.0-py3-none-any.whl --pip-args "--find-links ~/Documents/srcgraph/dist"`; then in `~/Documents/f1-race-replay`:
- `adrgraph check > /tmp/acc-check.txt; diff /tmp/compat-old.txt /tmp/acc-check.txt` → identical.
- `adrgraph audit` → clean, `4 rules: 4 semantic, 0 normalised, 0 grammar`.
- `adrgraph explain src/services/stream.py:9` → the trail; the excerpt highlights line 9; the arrow note names `PySide6.QtCore`.
- `adrgraph explain src/insights/telemetry_stream_viewer.py:13` → a `must` trail with `missing  INHERITS` and `existing  INHERITS → PySide6.QtWidgets.QMainWindow`.
- `adrgraph report` → `wrote .adrgraph/report.html (5 findings)`; open it and confirm 5 finding sections and 7 ADR sections.
- `git push` (nothing to push) still runs the hook clean.
Record the exact outputs in the task's commit message.

- [ ] **Step 4: Commit**

```bash
cd ~/Documents/adr-as-code && git add -A && git commit -m "docs: two projects, explain and report; action installs srcgraph" && git push
```
