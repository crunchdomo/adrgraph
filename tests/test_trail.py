import json
import pytest
from srcgraph.model import Edge
from adrgraph.adr import Decision, Rule
from adrgraph.check import bind, bind_scopes, run_check
from adrgraph.schema import load_adrs
from adrgraph.rules import Violation
from adrgraph.trail import build_trail, decision_text, trail_dict

ONLY = Rule("gw", "ADR-1", "only", {"from": {"path": "src/contracts/**"}, "to": {"path": "src/gateway/client.py"}, "via": "IMPORTS"}, "error", "")
NEVER_T = Rule("db", "ADR-1", "never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/db/**"}, "via": "CALLS", "transitive": True}, "warn", "")
MUST_INH = Rule("inh", "ADR-1", "must", {"every": {"kind": "function"}, "has": {"path": "src/log.py"}, "via": "INHERITS"}, "error", "")


@pytest.fixture
def source_tree(tmp_path):
    (tmp_path / "src" / "other").mkdir(parents=True)
    (tmp_path / "src" / "handlers").mkdir(parents=True)
    (tmp_path / "src" / "other" / "x.py").write_text("from src.gateway import client\n")
    (tmp_path / "src" / "handlers" / "h.py").write_text("".join(f"line {i}\n" for i in range(1, 11)))
    (tmp_path / "ADR-1.md").write_text("---\nid: ADR-1\n---\n\n## Context\n\nStuff.\n\n## Decision\n\nGateway via contracts.\nSecond line.\n\n## Consequences\n")
    (tmp_path / "ADR-2.md").write_text("# no decision heading\n")
    return tmp_path


def reader(root):
    return lambda p: (root / p).read_text().splitlines() if (root / p).exists() else None


def dec(id, rules, path, status="accepted"):
    return Decision(id, f"title {id}", status, "", "2026-01-01", None, [], str(path), rules)


def graph_with(layered, decisions):
    load_adrs(layered, decisions)
    binds = [(k, n) for k, ns in bind(layered, decisions).items() for n in ns]
    binds += [(d, n) for d, ns in bind_scopes(layered, decisions).items() for n in ns]
    layered.load_edges([Edge("BINDS", a, b) for a, b in binds])
    return layered


def test_only_trail_steps(layered, source_tree):
    d = dec("ADR-1", [ONLY], source_tree / "ADR-1.md")
    g = graph_with(layered, [d])
    result = run_check(g, [d], set())
    f = result.findings[0]
    t = build_trail(g, [d], f, result.findings, None, reader(source_tree))
    kinds = [s.kind for s in t.steps]
    assert kinds[:4] == ["decision", "rule", "node", "edge"] and kinds[-1] == "context"
    assert t.steps[0].detail["decision_text"] == "Gateway via contracts. Second line."
    assert t.steps[1].detail["portability"] == "semantic" and t.steps[1].detail["fixed"] is False
    assert t.steps[2].detail["why"] == "outside the from set and not excepted"
    assert t.steps[2].excerpt.highlight == 1 and t.steps[2].excerpt.lines[0].startswith("from src.gateway")
    assert t.steps[3].detail["target_id"] == "src/gateway/client.py" and t.steps[3].detail["missing"] is False
    assert t.steps[-1].detail["governed_by"] == [{"decision": "ADR-1", "result": "fails"}]
    assert t.steps[-1].detail["baselined"] is False


def test_transitive_trail_has_path_step(layered, source_tree):
    d = dec("ADR-1", [NEVER_T], source_tree / "ADR-1.md")
    g = graph_with(layered, [d])
    result = run_check(g, [d], set())
    t = build_trail(g, [d], result.findings[0], result.findings, None, reader(source_tree))
    kinds = [s.kind for s in t.steps]
    assert "path" in kinds and "edge" not in kinds
    path = next(s for s in t.steps if s.kind == "path")
    assert [n["id"] for n in path.detail["nodes"]] == ["src/handlers/h.py::h.view", "src/contracts/c.py::c.call", "src/db/q.py::q.run"]
    node = next(s for s in t.steps if s.kind == "node")
    assert node.excerpt.highlight == 5 and node.excerpt.lines[node.excerpt.highlight - node.excerpt.start] == "line 5"


def test_must_trail_with_no_existing_edges(layered, source_tree):
    d = dec("ADR-1", [MUST_INH], source_tree / "ADR-1.md")
    g = graph_with(layered, [d])
    result = run_check(g, [d], set())
    f = next(x for x in result.findings if x.node_id == "src/handlers/h.py::h.view")
    t = build_trail(g, [d], f, result.findings, None, reader(source_tree))
    edge = next(s for s in t.steps if s.kind == "edge")
    assert edge.detail["missing"] is True and edge.detail["existing"] == [] and edge.detail["label"] == "INHERITS"
    assert next(s for s in t.steps if s.kind == "node").detail["why"] == "in the every set with no matching edge"


def test_trail_without_source(layered, source_tree):
    d = dec("ADR-1", [ONLY], source_tree / "ADR-1.md")
    g = graph_with(layered, [d])
    result = run_check(g, [d], set())
    t = build_trail(g, [d], result.findings[0], result.findings, None, lambda p: None)
    assert next(s for s in t.steps if s.kind == "node").excerpt is None
    assert t.steps[0].detail["decision_text"] is None


def test_decision_text_absent_is_fine(source_tree):
    assert decision_text((source_tree / "ADR-2.md").read_text()) is None
    assert decision_text((source_tree / "ADR-1.md").read_text()) == "Gateway via contracts. Second line."


def test_context_lists_other_decisions_and_baseline(layered, source_tree):
    d1 = dec("ADR-1", [ONLY], source_tree / "ADR-1.md")
    d2 = dec("ADR-2", [], source_tree / "ADR-2.md"); d2.scope = [{"path": "src/other/**"}]
    g = graph_with(layered, [d1, d2])
    key = ("ADR-1", "gw", "src/other/x.py")
    result = run_check(g, [d1, d2], {key})
    f = result.findings[0]
    assert f.severity == "baselined"
    t = build_trail(g, [d1, d2], f, result.findings, ".adrgraph/baseline.json", reader(source_tree))
    ctx = t.steps[-1].detail
    assert ctx["governed_by"] == [{"decision": "ADR-1", "result": "fails"}, {"decision": "ADR-2", "result": "passes"}]
    assert ctx["baselined"] is True and ctx["baseline_path"] == ".adrgraph/baseline.json"


def test_fixed_finding_trail(layered, source_tree):
    d = dec("ADR-1", [ONLY], source_tree / "ADR-1.md")
    g = graph_with(layered, [d])
    f = Violation("ADR-1", "gw", "gone.py", "", 0, "no longer violated", severity="fixed")
    t = build_trail(g, [d], f, [f], None, reader(source_tree))
    assert [s.kind for s in t.steps] == ["decision", "rule", "context"] and t.steps[1].detail["fixed"] is True


def test_trail_dict_roundtrip(layered, source_tree):
    d = dec("ADR-1", [ONLY], source_tree / "ADR-1.md")
    g = graph_with(layered, [d])
    result = run_check(g, [d], set())
    t = build_trail(g, [d], result.findings[0], result.findings, None, reader(source_tree))
    data = json.loads(json.dumps(trail_dict(t)))
    assert data["finding"]["node_id"] == "src/other/x.py" and data["steps"][0]["kind"] == "decision"


def test_context_lists_only_accepted_decisions(layered, source_tree):
    d1 = dec("ADR-1", [ONLY], source_tree / "ADR-1.md")
    old = dec("ADR-9", [], source_tree / "ADR-2.md", status="superseded"); old.scope = [{"path": "src/other/**"}]
    g = graph_with(layered, [d1, old])
    result = run_check(g, [d1, old], set())
    t = build_trail(g, [d1, old], result.findings[0], result.findings, None, reader(source_tree))
    assert [x["decision"] for x in t.steps[-1].detail["governed_by"]] == ["ADR-1"]


def test_edge_syntax_found_for_nested_import(tmp_path, monkeypatch):
    from srcgraph.scan import scan
    from adrgraph.schema import open_graph
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f():\n    try:\n        import os\n    except ImportError:\n        pass\n")
    (tmp_path / "ADR-1.md").write_text("## Decision\n\nNo os.\n")
    monkeypatch.chdir(tmp_path)
    g = open_graph(str(tmp_path / "g.lbug"))
    g.load_code(scan(["."]))
    d = dec("ADR-1", [Rule("no-os", "ADR-1", "never", {"from": {"path": "src/**"}, "to": {"name": "os"}, "via": "IMPORTS"}, "error", "")], tmp_path / "ADR-1.md")
    graph_with(g, [d])
    result = run_check(g, [d], set())
    assert result.findings[0].line == 3
    t = build_trail(g, [d], result.findings[0], result.findings, None, reader(tmp_path))
    syn = next(s for s in t.steps if s.kind == "syntax")
    assert syn.detail["edge_syntax"]["kind"] == "import_statement" and syn.detail["edge_syntax"]["line"] == 3
    g.close()
