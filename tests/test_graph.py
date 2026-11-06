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
