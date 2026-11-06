from pathlib import Path
from adrgraph.extractors import EXTRACTORS
from adrgraph.extractors.python import extract


def ex(rel):
    return extract(rel, Path("tests/fixtures/pyrepo", rel).read_bytes(), rel[:-3].replace("/", ".").removesuffix(".__init__"))


def test_registry():
    assert EXTRACTORS[".py"] is extract


def test_unit_and_symbols():
    e = ex("src/contracts/c.py")
    assert e.units[0].name == "src.contracts.c" and e.units[0].kind == "module"
    assert {(s.qualified, s.kind) for s in e.symbols} == {
        ("src.contracts.c.Contract", "class"), ("src.contracts.c.Contract.send", "method"),
        ("src.contracts.c.call", "function"), ("src.contracts.c.warm", "function")}
    send = next(s for s in e.symbols if s.name == "send")
    assert send.id == "src/contracts/c.py::src.contracts.c.Contract.send" and send.line == 4 and send.ast_kind == "function_definition"
    assert ("CONTAINS", "src/contracts/c.py::src.contracts.c.Contract", send.id) in {(d.label, d.src, d.dst) for d in e.edges}


def test_package_unit():
    assert ex("src/contracts/__init__.py").units[0].kind == "package"


def test_imports():
    e = ex("src/handlers/h.py")
    assert [(i.module, i.level, i.names, i.alias) for i in e.imports] == [
        ("logging", 0, (), None), ("src.contracts", 0, (("c", "c"),), None), ("src.db.q", 0, (("run", "db_run"),), None)]


def test_calls_including_module_scope():
    e = ex("src/handlers/h.py")
    assert {(r.src_id, r.name) for r in e.refs} == {
        ("src/handlers/h.py::src.handlers.h.view", "c.call"), ("src/handlers/h.py::src.handlers.h.view", "logging.info"),
        ("src/handlers/h.py::src.handlers.h.leak", "db_run"), ("src/handlers/h.py", "c.warm")}


def test_syntax_error_does_not_crash():
    e = ex("src/broken.py")
    assert e.units[0].path == "src/broken.py" and any(s.name == "ok" for s in e.symbols)
