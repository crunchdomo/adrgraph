from adrgraph.graph import Graph
from adrgraph.model import Unit, Symbol, Edge
from adrgraph.adr import Decision, Rule


def units():
    return [Unit("src/a.py", "src/a.py", "a", "python", "file"), Unit("src/b.py", "src/b.py", "b", "python", "file")]


def test_load_and_query(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"))
    s = Symbol("src/b.py::b.f", "f", "b.f", "function", "python", "src/b.py", 3, 5, "function_definition")
    d = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], "docs/adr/1.md",
                 [Rule("r", "ADR-1", "never", {}, "error", "")])
    g.load(units(), [s], [d], [Edge("IMPORTS", "src/a.py", "src/b.py"), Edge("CALLS", "src/a.py", "src/b.py::b.f"),
                             Edge("CALLS", "src/a.py", "missing::x")], binds=[("ADR-1/r", "src/b.py::b.f")])
    assert g.count("Unit") == 2 and g.count("Symbol") == 1 and g.count("Rule") == 1
    rows = g.query("MATCH (a)-[:CALLS]->(b:Symbol) RETURN a.id AS src, b.id AS dst")
    assert rows == [{"src": "src/a.py", "dst": "src/b.py::b.f"}]
    assert g.query("MATCH (r:Rule)-[:BINDS]->(n) RETURN r.id AS r, n.id AS n") == [{"r": "ADR-1/r", "n": "src/b.py::b.f"}]
    assert g.query("MATCH (u:Unit) WHERE u.path =~ $re RETURN count(*) AS c", {"re": "src/a\\.py"}) == [{"c": 1}]
    g.close()


def test_reopen_is_fresh(tmp_path):
    p = str(tmp_path / "g.lbug")
    g = Graph(p); g.load(units(), [], [], []); g.close()
    g = Graph(p); assert g.count("Unit") == 0; g.close()


def test_binds_can_be_loaded_after_nodes(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"))
    d = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], "docs/adr/1.md",
                 [Rule("r", "ADR-1", "never", {}, "error", "")])
    g.load(units(), [], [d], [])
    g.load([], [], [], [], binds=[("ADR-1/r", "src/a.py")])
    assert g.query("MATCH (r:Rule)-[:BINDS]->(n) RETURN n.id AS n") == [{"n": "src/a.py"}]
    g.close()


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
