from srcgraph.model import Edge, Unit
from adrgraph.adr import Decision, Rule
from adrgraph.schema import open_graph, load_adrs, rule_key


def unit_rows():
    us = [Unit("src/a.py", "src/a.py", "a", "python", "file"), Unit("src/b.py", "src/b.py", "b", "python", "file")]
    return [{**vars(u), "line": 1} for u in us]


def test_rules_and_binds(tmp_path):
    g = open_graph(str(tmp_path / "g.lbug"))
    d = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], "docs/adr/1.md",
                 [Rule("r", "ADR-1", "never", {}, "error", "")])
    g.load_nodes("Unit", unit_rows())
    load_adrs(g, [d])
    assert g.count("Decision") == 1 and g.count("Rule") == 1
    assert g.query("MATCH (d:Decision)-[:HAS_RULE]->(r:Rule) RETURN r.id AS r") == [{"r": rule_key("ADR-1", "r")}]
    g.load_edges([Edge("BINDS", "ADR-1/r", "src/a.py")])   # a later pass, endpoints already loaded
    assert g.query("MATCH (r:Rule)-[:BINDS]->(n) RETURN n.id AS n") == [{"n": "src/a.py"}]
    g.close()


def test_decision_relations_and_scope_binds(tmp_path):
    g = open_graph(str(tmp_path / "g.lbug"))
    a = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], "a.md", [])
    b = Decision("ADR-2", "t", "accepted", "", "2026-01-01", None, ["ADR-1"], "b.md", [])
    b.depends_on = ["ADR-1"]; b.conflicts_with = ["ADR-9"]   # ADR-9 does not exist: dropped, audit reports it
    g.load_nodes("Unit", unit_rows())
    load_adrs(g, [a, b])
    g.load_edges([Edge("BINDS", "ADR-2", "src/a.py")])
    assert g.query("MATCH (x:Decision)-[:DEPENDS_ON]->(y:Decision) RETURN x.id AS x, y.id AS y") == [{"x": "ADR-2", "y": "ADR-1"}]
    assert g.query("MATCH (x:Decision)-[:SUPERSEDES]->(y:Decision) RETURN y.id AS y") == [{"y": "ADR-1"}]
    assert g.query("MATCH ()-[:CONFLICTS_WITH]->() RETURN count(*) AS c") == [{"c": 0}]
    assert g.query("MATCH (d:Decision)-[:BINDS]->(u:Unit) RETURN d.id AS d, u.id AS u") == [{"d": "ADR-2", "u": "src/a.py"}]
    g.close()
