# Two-tier graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the entire syntax tree of every scanned file into the graph alongside a richer semantic tier, give ADRs declared relations and scope, and make findings explain themselves.

**Architecture:** A shared syntax walker emits `Ast` nodes with `CHILD`/`NEXT` edges for every named tree-sitter node; extractors map grammar kinds onto a fixed normalised vocabulary and link each semantic node to its defining syntax node. `graph.py` is rewritten to bulk-load every table through `COPY FROM` temporary CSVs. `RawRef` grows a `relation` so one resolution path yields `CALLS`, `REFERENCES`, `INHERITS` and `DECORATES`. ADR frontmatter gains `depends_on`, `conflicts_with`, `scope`, rule `except` and `lang`; `audit` and `check` grow to use them.

**Tech Stack:** unchanged from milestone 1: Python 3.11+, `ladybug==0.22.1`, `tree-sitter==0.26.0`, `tree-sitter-python==0.25.0`, `tree-sitter-hcl==1.2.0`, `python-frontmatter==1.3.0`, pytest, stdlib `csv` and `tempfile`.

**Spec:** `docs/superpowers/specs/2026-11-06-two-tier-graph-design.md` (builds on `docs/superpowers/specs/2026-11-05-adr-enforcer-design.md`)

## Global Constraints

- No new dependencies. Everything milestone 1 self-enforces still holds: only `adrgraph/extractors/**` imports `tree_sitter*`, only `adrgraph/graph.py` imports `ladybug`, `rules.py`/`check.py`/`audit.py` never reach `adrgraph/extractors` even transitively. `adrgraph check` on the repo stays green at every commit.
- Existing ADR files and rules keep working unchanged; milestone 1's 69 tests keep passing (modulo the `RawRef.call` → `relation` rename in Task 2, which updates its own tests).
- Build on the f1 repo (17k lines) under 10 seconds end to end.
- Every `COPY FROM` CSV string column has `\n` and `\r` replaced by the two-character sequences `\n` and `\r` before writing. Regexes still go to Cypher as parameters only.
- Only named tree-sitter nodes become `Ast` nodes. `norm` is a function of the node's own grammar type only. `NORM_KINDS` and `TEXT_NORMS` live in `adrgraph/model.py` and extractors never add to them.
- `text` on an `Ast` node is stored when the node is a leaf (no named children) or its `norm` is in `TEXT_NORMS`; UTF-8 with replacement, truncated to 512 bytes, else empty string.
- Selectors never match `Ast` nodes unless `kind: ast` is given.
- Exit codes and the text finding format are unchanged from milestone 1.

## Review Focus

1. A source file with CRLF line endings or a string literal spanning lines: the CSV load must not fail and the stored `text` is the escaped form. Test in Task 1 (`test_text_with_newlines_survives_copy`) and Task 3 (`test_text_truncated_and_escaped`).
2. A decorator on a method inside a class: the `DECORATES` edge must originate from the method symbol, not the class or the unit. Test in Task 4 (`test_method_decorator_originates_from_method`).
3. A class with no base list at all (`class K:`): no `INHERITS` edge, no crash, and a `must ... via INHERITS` rule flags it. Test in Task 4 (`test_class_without_bases_has_no_inherits_edge`).
4. An ADR whose `depends_on` or `conflicts_with` names itself: reported, never a crash or an infinite loop. Test in Task 8 (`test_self_reference_is_reported`).
5. A rule's `except` list containing an unknown selector key: exit 2 naming the decision and rule, not a Cypher error. Test in Task 6 (`test_except_validation`).

---

## File structure

```
adrgraph/model.py                 + NORM_KINDS, TEXT_NORMS, AstNode, Edge.line, RawRef.relation, new edge labels, Extraction.ast/ast_edges
adrgraph/graph.py                 rewritten loader: COPY FROM temp CSVs; Ast/CHILD/NEXT/DERIVED_FROM/new rel tables; line on semantic rels
adrgraph/extractors/syntax.py     NEW: shared syntax-tier walker (ast_id, emit_syntax)
adrgraph/extractors/python.py     PY_NORM mapping; syntax tier; DERIVED_FROM; INHERITS/DECORATES raw refs; relation field
adrgraph/extractors/terraform.py  TF_NORM mapping; syntax tier; DERIVED_FROM; relation field
adrgraph/scan.py                  relation -> label, line on edges, ast passthrough, ScanResult.ast/ast_edges
adrgraph/selectors.py             Ast exclusion / kind: ast
adrgraph/adr.py                   depends_on, conflicts_with, scope, rule except + lang
adrgraph/rules.py                 except, portability(), import line and path in findings, Violation.path_nodes
adrgraph/check.py                 bind_scopes(), Finding.path_nodes, per-rule portability in metrics
adrgraph/audit.py                 checks 7 (dependency), 8 (declared conflict), 9 (empty scope)
adrgraph/cli.py                   decision BINDS, JSON fields, audit portability summary line
docs/adr/0004-core-owns-normalised-kinds.md   dogfood ADR with scope
README.md                         two tiers, new frontmatter, shipped queries
tests/                            one test module per source module as today; fixtures extended
```

---

### Task 1: COPY FROM loader, syntax-tier tables, edge lines

**Files:**
- Modify: `adrgraph/model.py`, `adrgraph/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: existing `Unit`, `Symbol`, `Edge`, `Decision`, `Rule`.
- Produces, in `model.py`:
  - `Edge(label: str, src: str, dst: str, line: int = 0)` (frozen; the default keeps every existing constructor call valid).
  - `@dataclass(frozen=True) AstNode(id: str, path: str, kind: str, norm: str, lang: str, line: int, end_line: int, start_byte: int, end_byte: int, text: str, field: str)`.
  - `EDGE_LABELS = {"CONTAINS", "IMPORTS", "CALLS", "REFERENCES", "INHERITS", "DECORATES", "READS", "WRITES", "TYPE_OF", "OVERRIDES"}`; `AST_EDGE_LABELS = {"CHILD", "NEXT"}`; `LINK_EDGE_LABEL = "DERIVED_FROM"`.
  - `NORM_KINDS = ("ClassDef", "FunctionDef", "Call", "Assign", "Import", "Decorator", "Attribute", "Name", "String", "Return", "If", "Loop", "Try", "Lambda", "Parameter", "Argument", "Block", "Comment", "Type", "Literal")`; `TEXT_NORMS = {"Decorator", "Attribute", "String", "Name", "Literal", "Type", "Import"}`; `TEXT_LIMIT = 512`.
- Produces, in `graph.py`:
  - `Graph.load(self, units, symbols, decisions, edges, binds=(), ast: list[AstNode] = (), ast_edges: list[Edge] = ()) -> None`. All tables loaded through `COPY FROM` CSV files written with the stdlib `csv` module into a `tempfile.TemporaryDirectory()` that lives for the duration of the call. One file per node table; one file per `(label, src_table, dst_table)` group; `COPY <label> FROM '<file>' (from='<Src>', to='<Dst>')` for rels. Edges whose endpoints are not known nodes are dropped as today (unknown ids resolved by one `MATCH (n) WHERE n.id IN $ids RETURN n.id, label(n)` query). `DERIVED_FROM` endpoints may be `Ast` nodes loaded in the same call.
  - `escape(s: str) -> str` module-level: replaces `\r` then `\n` with the literal two-character sequences; applied to every STRING column on write.
  - Node tables: existing four plus `Ast(id STRING, path STRING, kind STRING, norm STRING, lang STRING, line INT64, end_line INT64, start_byte INT64, end_byte INT64, text STRING, field STRING, PRIMARY KEY(id))`.
  - Rel tables: `CONTAINS`, `IMPORTS`, `CALLS`, `REFERENCES` as today **plus a `line INT64` property**; `INHERITS(FROM Symbol TO Symbol, line INT64)`; `DECORATES(FROM Symbol TO Symbol, line INT64)`; `READS`, `WRITES`, `TYPE_OF`, `OVERRIDES` with the same four pairs as `REFERENCES` and `line INT64`; `DERIVED_FROM(FROM Unit TO Ast, FROM Symbol TO Ast)`; `CHILD(FROM Ast TO Ast, field STRING)`; `NEXT(FROM Ast TO Ast)`; `HAS_RULE`, `SUPERSEDES`, `BINDS` unchanged; `DEPENDS_ON(FROM Decision TO Decision)`, `CONFLICTS_WITH(FROM Decision TO Decision)` created now, populated in Task 8. `BINDS` gains the pair `(Decision, Unit)` and `(Decision, Symbol)`.
  - `Graph.count`, `Graph.query`, `Graph.open`, context manager unchanged.
- `CHILD` edges carry `field` from `Edge`? No: `Edge` has no field slot. The walker (Task 3) encodes the field in the `AstNode.field` of the child, and `CHILD.field` is populated from the destination node's `field` at load time. (Simplest: `graph.load` looks up `field` by child id from the `ast` list.)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_graph.py`)

```python
from adrgraph.model import AstNode

def test_edge_line_property(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"))
    g.load(units(), [], [], [Edge("IMPORTS", "src/a.py", "src/b.py", line=7)])
    assert g.query("MATCH ()-[r:IMPORTS]->() RETURN r.line AS l") == [{"l": 7}]
    g.close()

def test_ast_tier_and_derived_from(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"))
    root = AstNode("src/a.py#0:20:module", "src/a.py", "module", "", "python", 1, 2, 0, 20, "", "")
    fn = AstNode("src/a.py#0:20:function_definition", "src/a.py", "function_definition", "FunctionDef", "python", 1, 2, 0, 20, "", "")
    name = AstNode("src/a.py#4:5:identifier", "src/a.py", "identifier", "Name", "python", 1, 1, 4, 5, "f", "name")
    s = Symbol("src/a.py::a.f", "f", "a.f", "function", "python", "src/a.py", 1, 2, "function_definition")
    g.load(units(), [s], [], [Edge("DERIVED_FROM", s.id, fn.id), Edge("DERIVED_FROM", "src/a.py", root.id)],
           ast=[root, fn, name], ast_edges=[Edge("CHILD", root.id, fn.id), Edge("CHILD", fn.id, name.id)])
    assert g.count("Ast") == 3
    assert g.query("MATCH (:Symbol)-[:DERIVED_FROM]->(a:Ast) RETURN a.kind AS k") == [{"k": "function_definition"}]
    assert g.query("MATCH (:Ast {kind:'function_definition'})-[c:CHILD]->(n:Ast) RETURN c.field AS f, n.text AS t") == [{"f": "name", "t": "f"}]
    g.close()

def test_text_with_newlines_survives_copy(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"))
    n = AstNode("x.py#0:9:string", "x.py", "string", "String", "python", 1, 2, 0, 9, "line1\nline2\r\n", "")
    g.load([], [], [], [], ast=[n])
    assert g.query("MATCH (a:Ast) RETURN a.text AS t") == [{"t": "line1\\nline2\\r\\n"}]
    g.close()

def test_repeated_load_appends(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"))
    g.load(units(), [], [], [Edge("IMPORTS", "src/a.py", "src/b.py")])
    g.load([], [], [], [Edge("IMPORTS", "src/b.py", "src/a.py")])
    assert g.count("Unit") == 2 and g.query("MATCH ()-[r:IMPORTS]->() RETURN count(*) AS c") == [{"c": 2}]
    g.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_graph.py -v`
Expected: the four new tests FAIL (`AstNode` import error first); existing ones pass.

- [ ] **Step 3: Implement `model.py` additions and rewrite `graph.py` per Interfaces**

Keep `Graph.__init__`, `query`, `count`, `open`, `close`. Replace `load`'s `UNWIND` calls with CSV writing plus `COPY FROM`. Column order in each CSV matches the DDL column order; rel CSVs are `src, dst[, props...]`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (73 tests).

- [ ] **Step 5: Commit**

```bash
git add adrgraph/model.py adrgraph/graph.py tests/test_graph.py
git commit -m "feat: COPY FROM loader, syntax-tier tables, line on edges"
```

---

### Task 2: `RawRef.relation` and edge lines through the scanner

**Files:**
- Modify: `adrgraph/model.py`, `adrgraph/scan.py`, `adrgraph/extractors/python.py`, `adrgraph/extractors/terraform.py`
- Test: `tests/test_scan.py`, `tests/test_extract_python.py`, `tests/test_extract_terraform.py`

**Interfaces:**
- Produces: `RawRef(src_id: str, name: str, line: int, relation: str)` replacing the `call: bool` field. `REF_RELATIONS = {"calls": "CALLS", "references": "REFERENCES", "inherits": "INHERITS", "decorates": "DECORATES"}` in `model.py`. The scanner emits `Edge(REF_RELATIONS[ref.relation], src, target, line=ref.line)` and `Edge("IMPORTS", unit, target, line=imp.line)`. Extractors emit `relation="calls"` for calls, `"references"` otherwise (Terraform always `"references"`).

- [ ] **Step 1: Update existing tests to the new field and add line assertions**

In `tests/test_extract_python.py`: every `r.call` becomes `r.relation == "calls"`, `not r.call` becomes `r.relation == "references"`; in the regression test's subprocess code likewise. In `tests/test_extract_terraform.py`: `all(r.relation == "references" for r in e.refs)`. Append to `tests/test_scan.py`:

```python
def test_import_and_call_edges_carry_lines(repo):
    lines = {(d.label, d.src, d.dst): d.line for d in repo.edges}
    assert lines[("IMPORTS", "src/handlers/h.py", "logging")] == 1
    assert lines[("IMPORTS", "src/handlers/h.py", "src/db/q.py")] == 3
    assert lines[("CALLS", "src/handlers/h.py::src.handlers.h.leak", "src/db/q.py::src.db.q.run")] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scan.py tests/test_extract_python.py tests/test_extract_terraform.py -v`
Expected: FAIL on `relation` attribute / line assertions.

- [ ] **Step 3: Implement the rename in `model.py`, both extractors, and `scan.py`**

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add adrgraph tests
git commit -m "feat: references carry a relation and a line"
```

---

### Task 3: Syntax tier for Python

**Files:**
- Create: `adrgraph/extractors/syntax.py`
- Modify: `adrgraph/model.py` (`Extraction.ast`, `Extraction.ast_edges`), `adrgraph/extractors/python.py`, `adrgraph/scan.py` (`ScanResult.ast`, `ScanResult.ast_edges`, passthrough), `adrgraph/cli.py` (`build` passes `ast`/`ast_edges` to `graph.load`)
- Test: `tests/test_extract_python.py`, `tests/test_scan.py`

**Interfaces:**
- Produces, in `extractors/syntax.py`:
  - `ast_id(path: str, node) -> str` returning `f"{path}#{node.start_byte}:{node.end_byte}:{node.type}"`.
  - `emit_syntax(root, mapping: dict[str, str], path: str, lang: str, lines: LineIndex) -> tuple[list[AstNode], list[Edge]]`: walks named nodes depth-first; `norm = mapping.get(node.type, "")`; `field` = the parent's `field_name_for_child(i)` or `""`; `text` per Global Constraints; `CHILD` edge parent→child; `NEXT` edge between consecutive named siblings; duplicate ids (same span, same kind) keep the first occurrence.
- Produces, in `python.py`: `PY_NORM: dict[str, str]` with at least the mapping in the spec's "normalised kinds" section; `extract` fills `ex.ast`, `ex.ast_edges`, and `DERIVED_FROM` edges: Unit→root `Ast`, each Symbol→its defining node (`class_definition`, `function_definition`, or the `assignment` node for variables), never the enclosing `decorated_definition`.
- `Extraction` gains `ast: list[AstNode]` and `ast_edges: list[Edge]` (default empty). `ScanResult` likewise; `scan` concatenates them. `cli.build` passes both to `graph.load`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_extract_python.py`)

```python
def test_syntax_tier_for_contracts():
    e = ex("src/contracts/c.py")
    kinds = {a.kind for a in e.ast}
    assert "module" in kinds and "class_definition" in kinds and "import_from_statement" in kinds
    cls = next(a for a in e.ast if a.kind == "class_definition")
    assert cls.norm == "ClassDef" and cls.text == "" and cls.line == 3
    attr = next(a for a in e.ast if a.kind == "attribute")
    assert attr.norm == "Attribute" and attr.text == "client.post"
    by_id = {a.id: a for a in e.ast}
    names = [by_id[d.dst] for d in e.ast_edges if d.label == "CHILD" and d.src == cls.id and by_id[d.dst].field == "name"]
    assert [n.text for n in names] == ["Contract"]
    nxt = [(by_id[d.src].kind, by_id[d.dst].kind) for d in e.ast_edges if d.label == "NEXT" and by_id[d.src].field == "" and by_id[d.src].line == 1]
    assert ("import_from_statement", "class_definition") in nxt

def test_derived_from_points_at_definition_not_decorator():
    e = extract("m.py", b"@dec\ndef f():\n    pass\n", "m")
    sym = next(s for s in e.symbols if s.name == "f")
    link = next(d for d in e.edges if d.label == "DERIVED_FROM" and d.src == sym.id)
    assert link.dst.endswith(":function_definition")
    assert any(d.label == "DERIVED_FROM" and d.src == "m.py" and d.dst.endswith(":module") for d in e.edges)

def test_norm_is_own_type_only():
    e = extract("m.py", b"def f(x, y=1):\n    pass\n", "m")
    by_kind = {}
    for a in e.ast: by_kind.setdefault(a.kind, []).append(a)
    assert all(a.norm == "Name" for a in by_kind["identifier"])
    assert by_kind["default_parameter"][0].norm == "Parameter"

def test_text_truncated_and_escaped():
    e = extract("m.py", b'x = "' + b"a" * 600 + b'"\ny = "l1\nl2"\n', "m")
    strings = [a for a in e.ast if a.kind == "string"]
    assert len(strings[0].text) == 512 and strings[1].text == '"l1\nl2"'   # escaping happens in graph.py, not here
```

And in `tests/test_scan.py`:

```python
def test_scan_passes_ast_through(repo):
    assert len(repo.ast) > 100 and any(d.label == "CHILD" for d in repo.ast_edges)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_extract_python.py tests/test_scan.py -v`
Expected: new tests FAIL (`Extraction` has no `ast`).

- [ ] **Step 3: Implement `syntax.py`, `PY_NORM`, the Python emission, and the passthrough**

Walk iteratively (explicit stack) rather than recursively; Django-scale files nest deep enough that recursion limits matter.

- [ ] **Step 4: Run the whole suite and a timing check**

Run: `.venv/bin/pytest -q && cd ~/Documents/f1-race-replay && time /Users/oenfadam/Documents/adr-as-code/.venv/bin/python -m adrgraph.cli build --db /tmp/f1-m2.lbug && cd -`
Expected: all pass; build prints a count including Ast nodes (add `graph.count('Ast')` to `build`'s output line) above 100,000; wall time under 10 s.

- [ ] **Step 5: Commit**

```bash
git add adrgraph tests
git commit -m "feat: syntax tier for Python with normalised kinds and DERIVED_FROM links"
```

---

### Task 4: `INHERITS` and `DECORATES`

**Files:**
- Modify: `adrgraph/extractors/python.py`
- Create: `tests/fixtures/pyrepo/src/views.py`
- Test: `tests/test_extract_python.py`, `tests/test_scan.py`

**Interfaces:**
- Produces: for each `class_definition`, one `RawRef(class_symbol_id, <base>, line, "inherits")` per named child of its `superclasses` field, where `<base>` is `_dotted(child)` or, when that is `None`, the child's text (so it resolves to `unresolved`). For each `decorated_definition`, one `RawRef(defined_symbol_id, <decorator>, line, "decorates")` per `decorator` child, where `<decorator>` is `_dotted` of the decorator's expression, or of its `function` field when the expression is a `call`. Methods and nested classes are covered because the walk already tracks the defined symbol.

- [ ] **Step 1: Write the fixture and failing tests**

`tests/fixtures/pyrepo/src/views.py`:
```python
import functools
from functools import lru_cache as cache
from src.contracts.c import Contract

def route(path):
    def deco(fn):
        return fn
    return deco

class Base:
    pass

class View(Base, Contract):
    @cache
    def get(self):
        pass

@route("/x")
@functools.wraps(route)
def handler():
    pass

class Plain:
    pass

class Dyn(make_base()):
    pass
```

Append to `tests/test_extract_python.py`:
```python
def test_inherits_and_decorates_refs():
    e = ex("src/views.py")
    rel = {(r.src_id.split("::")[1], r.name, r.relation) for r in e.refs if r.relation in ("inherits", "decorates")}
    assert ("src.views.View", "Base", "inherits") in rel and ("src.views.View", "Contract", "inherits") in rel
    assert ("src.views.View.get", "cache", "decorates") in rel          # method decorator, from the method
    assert ("src.views.handler", "route", "decorates") in rel           # call-form decorator uses the callee
    assert ("src.views.handler", "functools.wraps", "decorates") in rel
    assert ("src.views.Dyn", "make_base()", "inherits") in rel

def test_class_without_bases_has_no_inherits_edge():
    e = ex("src/views.py")
    assert not any(r.relation == "inherits" and r.src_id.endswith("src.views.Plain") for r in e.refs)
```

Append to `tests/test_scan.py`:
```python
def test_inherits_and_decorates_resolved(repo):
    e = {(d.label, d.src, d.dst) for d in repo.edges}
    assert ("INHERITS", "src/views.py::src.views.View", "src/views.py::src.views.Base") in e
    assert ("INHERITS", "src/views.py::src.views.View", "src/contracts/c.py::src.contracts.c.Contract") in e
    assert ("INHERITS", "src/views.py::src.views.Dyn", "unresolved::src.views.make_base()") in e
    assert ("DECORATES", "src/views.py::src.views.View.get", "unresolved::functools.lru_cache") in e   # alias resolved
    assert ("DECORATES", "src/views.py::src.views.handler", "src/views.py::src.views.route") in e
    assert ("DECORATES", "src/views.py::src.views.handler", "unresolved::functools.wraps") in e

def test_method_decorator_originates_from_method(repo):
    srcs = {d.src for d in repo.edges if d.label == "DECORATES" and d.dst == "unresolved::functools.lru_cache"}
    assert srcs == {"src/views.py::src.views.View.get"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_extract_python.py tests/test_scan.py -v`
Expected: new tests FAIL (no inherits/decorates refs).

- [ ] **Step 3: Implement in `python.py`**

Handle `decorated_definition` explicitly in the walk: collect its `decorator` children, recurse into `definition`, then emit the decorates refs for the symbol that recursion created. In the `class_definition` branch, read `child_by_field_name("superclasses")`.

- [ ] **Step 4: Run the whole suite** (the CLI tests scan `pyrepo`, which now has `views.py`; their assertions are unaffected because `views.py` imports nothing from `src/gateway` or `src/db`)

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add adrgraph/extractors/python.py tests
git commit -m "feat: INHERITS and DECORATES edges for Python"
```

---

### Task 5: Syntax tier for Terraform

**Files:**
- Modify: `adrgraph/extractors/terraform.py`
- Test: `tests/test_extract_terraform.py`

**Interfaces:**
- Produces: `TF_NORM = {"attribute": "Assign", "identifier": "Name", "string_lit": "String", "function_call": "Call", "numeric_lit": "Literal", "bool_lit": "Literal", "variable_expr": "Name", "get_attr": "Attribute"}`; blocks are not normalised. `extract` fills `ex.ast`/`ex.ast_edges` via `emit_syntax` and adds `DERIVED_FROM` Unit→root and each Symbol→its `block` (or `attribute` for locals entries).

- [ ] **Step 1: Write the failing test** (append to `tests/test_extract_terraform.py`)

```python
def test_terraform_syntax_tier():
    e = extract("main.tf", Path("tests/fixtures/tf/main.tf").read_bytes(), "main.tf")
    assert any(a.kind == "block" and a.norm == "" for a in e.ast)
    s = next(a for a in e.ast if a.kind == "string_lit" and a.text == '"aws_s3_bucket"')
    assert s.norm == "String"
    logs = next(x for x in e.symbols if x.name == "aws_s3_bucket.logs")
    link = next(d for d in e.edges if d.label == "DERIVED_FROM" and d.src == logs.id)
    assert link.dst.endswith(":block")
    suffix = next(x for x in e.symbols if x.name == "local.suffix")
    assert next(d for d in e.edges if d.label == "DERIVED_FROM" and d.src == suffix.id).dst.endswith(":attribute")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_extract_terraform.py -v`
Expected: FAIL (`e.ast` empty).

- [ ] **Step 3: Implement in `terraform.py`**

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add adrgraph/extractors/terraform.py tests/test_extract_terraform.py
git commit -m "feat: syntax tier for Terraform"
```

---

### Task 6: Selectors skip `Ast`; `except`; portability

**Files:**
- Modify: `adrgraph/selectors.py`, `adrgraph/adr.py`, `adrgraph/rules.py`
- Test: `tests/test_selectors.py`, `tests/test_rules.py`, `tests/test_adr.py`

**Interfaces:**
- `compile_selector`: when `kind` is absent, prepend the fragment `label({var}) <> 'Ast'`; `kind: ast` compiles to `label({var}) = 'Ast'` (and `name` then matches `{var}.text`). Allowed selector keys unchanged.
- `adr.Rule` gains `lang: str | None` (frontmatter `lang`) and the shape spec may contain `except: list[dict]`.
- `rules.compile_rule`: `except` allowed on all three shapes (not on `cypher`); must be a list of selector dicts else `RuleError`; each compiles with prefix `x{i}` on the subject variable (`a` for only/never, `e` for must) and is appended as `AND NOT (<frag>)`. `bound_ids` applies the same exclusions. `_KEYS` and validation updated accordingly.
- `rules.portability(rule: Rule) -> str`: `"semantic"` for shapes or Cypher without the substring `:Ast`; else `"grammar"` if the Cypher contains `.kind` or `kind:`; else `"normalised"`. For `"grammar"` with `rule.lang` set, the string is `f"grammar ({rule.lang})"`, else `"grammar (unspecified)"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_selectors.py`:
```python
def test_selectors_skip_ast_unless_asked(tmp_path):
    from adrgraph.model import AstNode
    g = Graph(str(tmp_path / "g.lbug"))
    g.load([Unit("src/a.py", "src/a.py", "a", "python", "file")], [], [], [],
           ast=[AstNode("src/a.py#0:1:identifier", "src/a.py", "identifier", "Name", "python", 1, 1, 0, 1, "x", "")])
    def ids(sel):
        frag, params = compile_selector(sel, "n", "s")
        return sorted(r["id"] for r in g.query(f"MATCH (n) WHERE {frag} RETURN n.id AS id", params))
    assert ids({"path": "src/**"}) == ["src/a.py"]
    assert ids({"kind": "ast", "name": "x"}) == ["src/a.py#0:1:identifier"]
    g.close()
```

Append to `tests/test_rules.py`:
```python
def test_except_on_must_and_never(layered):
    bad = rule("must", {"every": {"kind": "function"}, "has": {"path": "src/log.py"}, "via": "CALLS",
                        "except": [{"name": "run"}, {"path": "src/log.py"}]})
    assert [x.node_id for x in evaluate(layered, bad)] == ["src/contracts/c.py::c.call"]
    assert bound_ids(layered, bad) == ["src/contracts/c.py::c.call", "src/handlers/h.py::h.view"]
    n = rule("never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/contracts/**"}, "via": "IMPORTS", "except": [{"kind": "unit"}]})
    assert evaluate(layered, n) == []

def test_except_validation():
    with pytest.raises(RuleError, match="ADR-1/r.*pth"):
        compile_rule(rule("never", {"from": {}, "to": {}, "via": "CALLS", "except": [{"pth": "x"}]}))
    with pytest.raises(RuleError, match="except"):
        compile_rule(rule("never", {"from": {}, "to": {}, "via": "CALLS", "except": {"path": "x"}}))

def test_portability():
    from adrgraph.rules import portability
    assert portability(rule("never", {"from": {}, "to": {}, "via": "CALLS"})) == "semantic"
    assert portability(rule("cypher", "MATCH (s:Symbol) RETURN s.id AS node_id")) == "semantic"
    assert portability(rule("cypher", "MATCH (a:Ast {norm:'Decorator'}) RETURN a.id AS node_id")) == "normalised"
    assert portability(rule("cypher", "MATCH (a:Ast {kind:'decorator'}) RETURN a.id AS node_id")) == "grammar (unspecified)"
    r = rule("cypher", "MATCH (a:Ast) WHERE a.kind = 'decorator' RETURN a.id AS node_id"); r.lang = "python"
    assert portability(r) == "grammar (python)"
```

Append to `tests/test_adr.py` a fixture-less test that a rule with `lang: python` loads with `r.lang == "python"` and one without has `r.lang is None`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_selectors.py tests/test_rules.py tests/test_adr.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the whole suite and the self-check** (the self-check confirms the `Ast` exclusion left adrgraph's own compliance at 100%)

Run: `.venv/bin/pytest -q && .venv/bin/python -m adrgraph.cli check --exclude tests/fixtures | head -1`
Expected: all pass; `overall compliance: 100.0%`.

- [ ] **Step 5: Commit**

```bash
git add adrgraph/selectors.py adrgraph/adr.py adrgraph/rules.py tests
git commit -m "feat: selectors skip the syntax tier; except lists; rule portability"
```

---

### Task 7: Findings that explain themselves

**Files:**
- Modify: `adrgraph/rules.py`, `adrgraph/check.py`, `adrgraph/cli.py`
- Test: `tests/test_rules.py`, `tests/test_cli.py`

**Interfaces:**
- `Violation` gains `path_nodes: tuple[str, ...] = ()`. `Finding` gains the same. JSON output includes `path_nodes` per finding (empty list when direct).
- Direct `only`/`never` compile to `MATCH (a)-[r:VIA]->(b) ... RETURN ..., CASE WHEN r.line > 0 THEN r.line ELSE a.line END AS line, ...`. The `DISTINCT` on `node_id` stays; `evaluate` keeps the first row per node after ordering by `line`.
- Transitive `only`/`never` compile to `MATCH p = (a)-[:VIA* SHORTEST 1..10 ...]->(b) ... RETURN a.id AS node_id, a.path AS path, list_transform(rels(p), r -> r.line)[1] AS line, list_transform(nodes(p), x -> x.id) AS path_nodes`; `evaluate` builds `message = "reaches " + path_nodes[-1] + " via " + " -> ".join(path_nodes[1:])` and sets `Violation.path_nodes`. If the first hop's line is `0`, `line` falls back to `a.line`.
- `must` is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rules.py` (the `layered` fixture in `conftest.py` gets `line=` on its edges: IMPORTS h→c line 2, c→gateway line 1, x→gateway line 1; CALLS view→call line 5, call→run line 3, run→view line 2, view→info line 6):
```python
def test_direct_import_violation_reports_import_line(layered):
    v = evaluate(layered, rule("never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/contracts/**"}, "via": "IMPORTS"}))
    assert [(x.node_id, x.line) for x in v] == [("src/handlers/h.py", 2)]

def test_transitive_violation_explains_path(layered):
    v = evaluate(layered, rule("never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/db/**"}, "via": "CALLS", "transitive": True}))
    assert v[0].path_nodes == ("src/handlers/h.py::h.view", "src/contracts/c.py::c.call", "src/db/q.py::q.run")
    assert v[0].message == "reaches src/db/q.py::q.run via src/contracts/c.py::c.call -> src/db/q.py::q.run"
    assert v[0].line == 5
```

In `tests/test_cli.py`, change the first assertion of `test_check_text_fails_with_findings` to expect `src/other/x.py:1` still (its import is on line 1) and add: `assert "ADR-0001/no-handler-calls-db  reaches src/db/q.py::src.db.q.run via src/db/q.py::src.db.q.run" in out`, and in the JSON test assert every finding has a `path_nodes` key.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_rules.py tests/test_cli.py -v`
Expected: new assertions FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add adrgraph/rules.py adrgraph/check.py adrgraph/cli.py tests
git commit -m "feat: findings report the import line and the violating path"
```

---

### Task 8: ADR relations, scope, and the new audit checks

**Files:**
- Modify: `adrgraph/adr.py`, `adrgraph/graph.py` (DEPENDS_ON/CONFLICTS_WITH edges from decisions in `load`), `adrgraph/check.py`, `adrgraph/audit.py`, `adrgraph/cli.py`
- Test: `tests/test_adr.py`, `tests/test_check.py`, `tests/test_audit.py`, `tests/test_graph.py`

**Interfaces:**
- `Decision` gains `depends_on: list[str]`, `conflicts_with: list[str]`, `scope: list[dict]` (all default empty; frontmatter keys of the same names; `scope` entries must be dicts else `AdrError`).
- `graph.load` adds `DEPENDS_ON` and `CONFLICTS_WITH` edges for each decision, dropping targets that don't exist (audit reports them).
- `check.bind_scopes(graph, decisions) -> dict[str, list[str]]`: decision id → node ids matched by any `scope` selector (union, sorted). `cli.build` loads these as `BINDS` from the Decision node, alongside rule binds.
- `audit.run_audit` adds:
  - `dependency` (error): an accepted decision whose `depends_on` names a missing decision or one whose status is not `accepted`. Message names the target and its status.
  - `declared_conflict` (error): two decisions both `accepted` where either lists the other in `conflicts_with`. One finding per pair, on the lexically smaller id.
  - `empty_scope` (warn, error with `--strict`): an accepted decision with a `scope` selector matching zero nodes. One finding per selector, message includes the selector.
  - A decision naming itself in `depends_on` or `conflicts_with` is reported as `dependency`/`declared_conflict` with message `"... names itself"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adr.py` a test that a file with `depends_on: [ADR-1]`, `conflicts_with: [ADR-2]`, `scope: [{path: "src/**"}]` loads those three fields, and one where `scope: "src/**"` raises `AdrError` matching `scope`.

Append to `tests/test_audit.py`:
```python
def test_dependency_and_declared_conflict(layered):
    a = dec("ADR-1", "accepted", []); a.depends_on = ["ADR-2", "ADR-9"]
    b = dec("ADR-2", "proposed", []); b.conflicts_with = ["ADR-3"]
    c = dec("ADR-3", "accepted", []); c.conflicts_with = []
    fs = run_audit(layered, [a, b, c], TODAY)
    assert checks(fs) == [("dependency", "ADR-1", ""), ("dependency", "ADR-1", "")]
    msgs = sorted(f.message for f in fs)
    assert "ADR-2" in msgs[0] and "proposed" in msgs[0] and "ADR-9" in msgs[1]
    b.status = "accepted"
    assert ("declared_conflict", "ADR-2", "") in checks(run_audit(layered, [a, b, c], TODAY))

def test_empty_scope_and_self_reference(layered):
    d = dec("ADR-1", "accepted", []); d.scope = [{"path": "src/handlers/**"}, {"path": "nowhere/**"}]; d.depends_on = ["ADR-1"]
    fs = run_audit(layered, [d], TODAY)
    assert checks(fs) == [("dependency", "ADR-1", ""), ("empty_scope", "ADR-1", "")]
    assert "names itself" in next(f for f in fs if f.check == "dependency").message
    assert "nowhere" in next(f for f in fs if f.check == "empty_scope").message
```

Append to `tests/test_check.py`:
```python
def test_bind_scopes(layered):
    d = dec("ADR-7", "accepted", []); d.scope = [{"path": "src/db/**"}, {"path": "src/log.py", "kind": "unit"}]
    from adrgraph.check import bind_scopes
    assert bind_scopes(layered, [d]) == {"ADR-7": ["src/db/q.py", "src/db/q.py::q.run", "src/log.py"]}
```

Append to `tests/test_graph.py` a test that loading two decisions where one `depends_on` the other yields one `DEPENDS_ON` edge, and that `BINDS` from a Decision to a Unit loads.

Append to `tests/test_cli.py` a test that, with a `scope` on the pyrepo ADR fixture pointing at `src/handlers/**`, `adrgraph query "MATCH (d:Decision)-[:BINDS]->(n) RETURN count(*) AS c"` returns at least 1.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_adr.py tests/test_audit.py tests/test_check.py tests/test_graph.py tests/test_cli.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add adrgraph tests
git commit -m "feat: ADR depends_on, conflicts_with and scope, with audit checks"
```

---

### Task 9: CLI output, README, dogfood ADR, acceptance on the f1 fork

**Files:**
- Modify: `adrgraph/cli.py`, `README.md`
- Create: `docs/adr/0004-core-owns-normalised-kinds.md`
- Outside this repo: four ADR files and `.adrgraph/baseline.json` in `~/Documents/f1-race-replay` (the user's fork), committed there.

**Interfaces:**
- `audit` text output ends with one summary line: `N rules: a semantic, b normalised, c grammar (lang, ...)` built from `rules.portability`; omitted when there are no rules. `check --format json` adds `"portability"` to each `per_rule` entry.
- `build` output line includes the `Ast` count.

- [ ] **Step 1: Write the failing CLI test**

Append to `tests/test_cli.py`: with the pyrepo fixture, `audit` text output's last line matches `r"^\d+ rules: \d+ semantic, \d+ normalised, \d+ grammar"`, and `check --format json` has `per_rule[...]["portability"] == "semantic"` for `ADR-0001/gateway-only-via-contracts`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the CLI changes, then write the dogfood ADR**

`docs/adr/0004-core-owns-normalised-kinds.md`: `status: accepted`, `scope: [{path: "adrgraph/model.py"}]`, `depends_on: [ADR-0001]`, no rules; Context/Decision/Consequences explaining that `NORM_KINDS` and `TEXT_NORMS` are owned by the core and extractors only map onto them, and that a `WRITES`-based rule replaces the prose once that edge exists.

- [ ] **Step 4: Update README**

Sections to add or change: "The graph" (two tiers, `Ast` properties, `CHILD`/`NEXT`/`DERIVED_FROM`, the normalised vocabulary with the full `NORM_KINDS` list, `TEXT_NORMS`), the ADR frontmatter example (`depends_on`, `conflicts_with`, `scope`, `except`, `lang`), the `audit` check list (nine checks and the portability line), "Findings" (import line, path), the four shipped queries from the spec, and a "Performance" paragraph with the f1 and Django numbers from the spec.

- [ ] **Step 5: Run the suite and the self-check**

Run: `.venv/bin/pytest -q && .venv/bin/python -m adrgraph.cli check --exclude tests/fixtures && .venv/bin/python -m adrgraph.cli audit --strict --exclude tests/fixtures`
Expected: all pass; compliance 100%; audit prints no findings and the portability line `5 rules: 5 semantic, 0 normalised, 0 grammar`.

- [ ] **Step 6: Commit**

```bash
git add adrgraph/cli.py README.md docs/adr/0004-core-owns-normalised-kinds.md tests/test_cli.py
git commit -m "feat: portability summary, Ast count, docs and dogfood scope ADR"
```

- [ ] **Step 7: Acceptance on the f1 fork**

In `~/Documents/f1-race-replay`, rebuild the wheel and reinstall it with pipx (`pipx install --force /Users/oenfadam/Documents/adr-as-code/dist/adrgraph-0.1.0-py3-none-any.whl` after `python -m build --wheel`), then add frontmatter:

- `0004-use-pyside6-for-menus-and-insights.md`: `id: ADR-0004`, `status: accepted`, one `only` rule `pyside-only-in-ui`: from `{path: "src/gui/**"}`, to `{kind: unit, name: "PySide6*"}`, via `IMPORTS`, with `except: [{path: "src/insights/**"}]` so the insights package is not reported as a violator (a `from` selector is a single map and globs have no alternation). Expected: fails on `main.py` and `src/services/stream.py` only.
- `0005-stream-telemetry-over-local-tcp.md`: `id: ADR-0005`, `only` from `{path: "src/services/stream.py"}` to `{kind: unit, name: "socket"}` via `IMPORTS`. Expected: passes.
- `0006-build-insights-on-pit-wall-window-base-class.md`: `id: ADR-0006`, `must every {path: "src/insights/**", kind: class} except [{name: "_*"}, {name: "StintBar"}, {name: "LapAxisWidget"}] has {name: "*PitWallWindow"} via INHERITS`. Expected: exactly one violation, `TelemetryStreamViewer`.
- `0002`, `0003`, `0007`: `id`, `status: accepted`, and a `scope` (`src/interfaces/**`; `src/f1_data.py`; `src/interfaces/race_replay.py` respectively). No rules.

Run: `adrgraph check` then `adrgraph audit`.
Expected: `check` exits 1 with the two baselined ADR-0001 findings (now at their real import lines, not `:1`), the ADR-0004 findings on `main.py` and `src/services/stream.py`, and one ADR-0006 finding naming `TelemetryStreamViewer`; `audit` exits 0 and ends with `4 rules: 4 semantic, 0 normalised, 0 grammar` (ADR-0001's single rule plus one each for 0004, 0005, 0006). Record the result in the task's commit message. Then `adrgraph check --write-baseline` and commit the fork (`git add docs/adr .adrgraph/baseline.json && git commit && git push`), which runs the pre-push hook as a final confirmation.

- [ ] **Step 8: Bump version and tag**

In `adrgraph/__init__.py` set `__version__ = "0.2.0"`; commit `chore: 0.2.0`. Do not tag or publish; that waits on PyPI setup.
