import pytest
from srcgraph.model import Edge, Unit, Symbol
from adrgraph.adr import Decision, Rule
from adrgraph.rules import evaluate
from adrgraph.schema import open_graph
from adrgraph.suggest import suggest


def U(path):
    return {**vars(Unit(path, path, path[:-3].replace("/", "."), "python", "file")), "line": 1}


def X(name):
    return {**vars(Unit(name, name, name, "python", "external")), "line": 0}


def C(path, name):
    return Symbol(f"{path}::{name}", name, name, "class", "python", path, 1, 2, "class_definition")


@pytest.fixture
def repo(tmp_path):
    """src/data imports fastf1 (3 edges), src/gui imports PySide6 (2), one file imports requests, everyone imports os,
    numpy is imported from two unrelated dirs. src/insights classes mostly subclass Base; src/mixed do not."""
    g = open_graph(str(tmp_path / "s.lbug"))
    files = ["src/data/a.py", "src/data/b.py", "src/gui/w.py", "src/gui/m.py", "src/y.py", "src/other/z.py",
             "src/base.py", "src/insights/a.py", "src/insights/b.py", "src/insights/c.py", "src/mixed/m.py", "src/views/v.py",
             "tests/t.py"]
    g.load_nodes("Unit", [U(f) for f in files] + [X(n) for n in ("fastf1.core", "fastf1.api", "PySide6.QtWidgets", "requests", "os", "numpy")])
    classes = [C("src/base.py", "Base"), C("src/base.py", "Other"), C("src/insights/a.py", "A"), C("src/insights/b.py", "B"),
               C("src/insights/c.py", "_C"), C("src/insights/c.py", "Odd"), C("src/mixed/m.py", "M1"), C("src/mixed/m.py", "M2"),
               C("src/views/v.py", "V")]
    g.load_nodes("Symbol", [vars(c) for c in classes])
    imports = [("src/data/a.py", "fastf1.core"), ("src/data/a.py", "fastf1.api"), ("src/data/b.py", "fastf1.core"),
               ("src/gui/w.py", "PySide6.QtWidgets"), ("src/gui/m.py", "PySide6.QtWidgets"), ("src/y.py", "requests"),
               ("src/data/a.py", "numpy"), ("src/other/z.py", "numpy")] + [(f, "os") for f in files]
    inherits = [("src/insights/a.py::A", "src/base.py::Base"), ("src/insights/b.py::B", "src/base.py::Base"),
                ("src/mixed/m.py::M1", "src/base.py::Base"), ("src/mixed/m.py::M2", "src/base.py::Other"),
                ("src/views/v.py::V", "src/base.py::Base")]
    g.load_edges([Edge("IMPORTS", a, b, line=1) for a, b in imports] + [Edge("INHERITS", a, b, line=1) for a, b in inherits])
    yield g
    g.close()


def by_shape(cands, shape):
    return [c for c in cands if c.shape == shape]


def test_only_candidates_collapse_importers_and_skip_stdlib_and_root(repo):
    only = by_shape(suggest(repo), "only")
    assert [(c.spec["to"]["name"], c.spec["from"]["path"], c.strength) for c in only] == [
        ("fastf1*", "src/data/**", 3), ("PySide6*", "src/gui/**", 2)]
    assert all(c.spec["via"] == "IMPORTS" and c.spec["to"]["kind"] == "unit" for c in only)


def test_only_single_importer_is_a_file_selector_below_default_floor(repo):
    only = by_shape(suggest(repo, min_strength=1), "only")
    assert ("requests*", "src/y.py", 1) in [(c.spec["to"]["name"], c.spec["from"]["path"], c.strength) for c in only]
    assert "numpy*" not in [c.spec["to"]["name"] for c in only]   # common dir src/ holds most units: no boundary


def test_must_candidate_excepts_private_and_minority_nonconformers(repo):
    must = by_shape(suggest(repo), "must")
    assert len(must) == 1
    c = must[0]
    assert c.spec == {"every": {"path": "src/insights/**", "kind": "class"}, "except": [{"name": "_*"}, {"name": "Odd"}],
                      "has": {"name": "*Base"}, "via": "INHERITS"}
    assert c.strength == 2


def test_candidates_hold_on_the_graph(repo):
    for c in suggest(repo, min_strength=1):
        assert evaluate(repo, Rule(c.rule_id, "ADR-0", c.shape, c.spec, "error", "")) == []


def test_covered_candidates_are_skipped_unless_asked(repo):
    existing = Rule("gw", "ADR-1", "only", {"from": {"path": "x"}, "to": {"kind": "unit", "name": "fastf1*"}, "via": "IMPORTS"}, "error", "")
    d = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], "docs/adr/1.md", [existing])
    names = [c.spec["to"]["name"] for c in by_shape(suggest(repo, [d]), "only")]
    assert names == ["PySide6*"]
    names = [c.spec["to"]["name"] for c in by_shape(suggest(repo, [d], include_covered=True), "only")]
    assert names == ["fastf1*", "PySide6*"]


def test_candidates_carry_title_and_rule_id(repo):
    titles = {c.rule_id: c.title for c in suggest(repo)}
    assert titles == {"fastf1-only-via-src-data": "Only src/data/** may import fastf1",
                      "pyside6-only-via-src-gui": "Only src/gui/** may import PySide6",
                      "src-insights-classes-inherit-base": "Every class in src/insights/** inherits Base"}
