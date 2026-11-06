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


def test_multi_name_import():
    e = extract("m.py", b"import os, src.gateway.client as gc, sys\n", "m")
    assert [(i.module, i.alias) for i in e.imports] == [("os", None), ("src.gateway.client", "gc"), ("sys", None)]


def test_non_call_attribute_reference():
    e = extract("m.py", b"from src.gateway import client\nsession = client.session\n\nclass K:\n    def m(self):\n        return self.x.y\n", "m")
    assert [(r.src_id, r.name, r.relation) for r in e.refs] == [("m.py", "client.session", "references")]


def test_attribute_chains_do_not_corrupt_memory(tmp_path):
    """Regression: reading node.start_point once per reference (thousands of Point objects)
    corrupts the heap in py-tree-sitter 0.26 and crashes the interpreter at exit (SIGSEGV/SIGBUS).
    Must run in a subprocess because the crash is at teardown."""
    import os, subprocess, sys
    lines = ["import os", "class C:", "    def m(self):", "        pass", ""]
    for i in range(2000):
        lines += [f'v{i} = os.path.join("a", str({i})).strip().lower()',
                  f'os.environ.get("K{i}").x.y.z()', f"w{i} = sys.argv.count.__doc__"]
    src = tmp_path / "trigger.py"
    src.write_text("\n".join(lines) + "\n")
    # Keep only the refs: an Extraction kept alive until exit masks the crash.
    code = ("from adrgraph.extractors.python import extract\n"
            f"refs = extract('t.py', open({str(src)!r}, 'rb').read(), 't').refs\n"
            "assert any(r.name == 'os.environ.get' and r.relation == 'calls' for r in refs)\n"
            "assert any(r.name == 'sys.argv.count.__doc__' and r.relation == 'references' for r in refs)\n")
    proc = subprocess.run([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                          cwd=str(tmp_path), env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr[-500:]}"
