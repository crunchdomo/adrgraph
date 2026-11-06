import re
import pytest
from adrgraph.selectors import glob_to_regex, compile_selector, SelectorError
from adrgraph.graph import Graph
from adrgraph.model import Unit, Symbol


@pytest.mark.parametrize("glob,hit,miss", [
    ("src/**", "src/a/b.py", "lib/a.py"),
    ("src/*.py", "src/a.py", "src/a/b.py"),
    ("**/client.py", "client.py", "src/client2.py"),
    ("aws_s3_bucket.*", "aws_s3_bucket.logs", "aws_s3_bucket_policy.p"),
    ("tree_sitter*", "tree_sitter_python", "tree_sit"),
])
def test_glob(glob, hit, miss):
    r = re.compile(glob_to_regex(glob))
    assert r.fullmatch(hit) and not r.fullmatch(miss)


def test_unknown_key():
    with pytest.raises(SelectorError, match="pth"):
        compile_selector({"pth": "x"}, "n", "a")


def test_selector_against_graph(tmp_path):
    g = Graph(str(tmp_path / "g.lbug"))
    g.load([Unit("src/a.py", "src/a.py", "a", "python", "file"), Unit("os", "os", "os", "python", "external")],
           [Symbol("src/a.py::a.f", "f", "a.f", "function", "python", "src/a.py", 1, 2, "function_definition"),
            Symbol("src/a.py::a.K", "K", "a.K", "class", "python", "src/a.py", 3, 4, "class_definition")], [], [])

    def ids(sel):
        frag, params = compile_selector(sel, "n", "s")
        return sorted(r["id"] for r in g.query(f"MATCH (n) WHERE {frag} RETURN n.id AS id", params))

    assert ids({"path": "src/**"}) == ["src/a.py", "src/a.py::a.K", "src/a.py::a.f"]
    assert ids({"path": "src/**", "kind": "function"}) == ["src/a.py::a.f"]
    assert ids({"kind": "unit", "name": "os*"}) == ["os"]
    assert ids({"name": "a.f"}) == ["src/a.py::a.f"]
    assert ids({}) == ["os", "src/a.py", "src/a.py::a.K", "src/a.py::a.f"]
    g.close()
