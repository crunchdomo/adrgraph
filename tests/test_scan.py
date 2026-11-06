import pytest
from adrgraph.scan import scan, module_name


@pytest.fixture
def repo(monkeypatch):
    monkeypatch.chdir("tests/fixtures/pyrepo")
    return scan(["."])


def test_module_name():
    assert module_name(".", "src/a/b.py") == "src.a.b" and module_name(".", "src/a/__init__.py") == "src.a"


def test_imports_resolved_and_external(repo):
    e = {(d.label, d.src, d.dst) for d in repo.edges}
    assert ("IMPORTS", "src/handlers/h.py", "src/contracts/c.py") in e
    assert ("IMPORTS", "src/handlers/h.py", "src/db/q.py") in e
    assert ("IMPORTS", "src/handlers/h.py", "logging") in e
    ext = next(u for u in repo.units if u.id == "logging")
    assert ext.kind == "external" and ext.name == "logging"
    assert ("CONTAINS", "src/contracts/__init__.py", "src/contracts/c.py") in e


def test_calls_resolved(repo):
    e = {(d.label, d.src, d.dst) for d in repo.edges}
    assert ("CALLS", "src/handlers/h.py::src.handlers.h.view", "src/contracts/c.py::src.contracts.c.call") in e
    assert ("CALLS", "src/handlers/h.py::src.handlers.h.leak", "src/db/q.py::src.db.q.run") in e
    assert ("CALLS", "src/handlers/h.py", "src/contracts/c.py::src.contracts.c.warm") in e
    assert ("CALLS", "src/handlers/h.py::src.handlers.h.view", "unresolved::logging.info") in e
    assert any(s.id == "unresolved::logging.info" and s.kind == "unresolved" for s in repo.symbols)


def test_ambiguous_roots_warn(tmp_path, monkeypatch):
    for r in ("r1", "r2"):
        (tmp_path / r / "pkg").mkdir(parents=True)
        (tmp_path / r / "pkg" / "m.py").write_text("x = 1\n")
    (tmp_path / "r1" / "pkg" / "u.py").write_text("import pkg.m\n")
    monkeypatch.chdir(tmp_path)
    res = scan(["r1", "r2"])
    assert any("ambiguous module pkg.m" in w for w in res.warnings)
    assert ("IMPORTS", "r1/pkg/u.py", "pkg.m") in {(d.label, d.src, d.dst) for d in res.edges}


def test_excludes(tmp_path, monkeypatch):
    (tmp_path / ".venv").mkdir(); (tmp_path / ".venv" / "x.py").write_text("")
    (tmp_path / "gen").mkdir(); (tmp_path / "gen" / "y.py").write_text("")
    (tmp_path / "ok.py").write_text("")
    monkeypatch.chdir(tmp_path)
    assert [u.id for u in scan(["."], excludes=(".venv", "gen/**")).units] == ["ok.py"]
