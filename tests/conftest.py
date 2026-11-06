import pytest
from adrgraph.graph import Graph
from adrgraph.model import Unit, Symbol, Edge


def U(path, name):
    return Unit(path, path, name, "python", "file")


def S(path, qualified, line):
    return Symbol(f"{path}::{qualified}", qualified.split(".")[-1], qualified, "function", "python", path, line, line + 1, "function_definition")


@pytest.fixture
def layered(tmp_path):
    """Layered app: handlers -> contracts -> gateway, with a db layer and a logger."""
    g = Graph(str(tmp_path / "layered.lbug"))
    units = [U("src/handlers/h.py", "handlers.h"), U("src/contracts/c.py", "contracts.c"),
             U("src/gateway/client.py", "gateway.client"), U("src/other/x.py", "other.x"),
             U("src/db/q.py", "db.q"), U("src/log.py", "log")]
    view, run, info, call = (S("src/handlers/h.py", "h.view", 3), S("src/db/q.py", "q.run", 1),
                             S("src/log.py", "log.info", 1), S("src/contracts/c.py", "c.call", 2))
    edges = [Edge("IMPORTS", "src/handlers/h.py", "src/contracts/c.py", line=2),
             Edge("IMPORTS", "src/contracts/c.py", "src/gateway/client.py", line=1),
             Edge("IMPORTS", "src/other/x.py", "src/gateway/client.py", line=1),
             Edge("CALLS", view.id, call.id, line=5), Edge("CALLS", call.id, run.id, line=3),
             Edge("CALLS", run.id, view.id, line=2), Edge("CALLS", view.id, info.id, line=6)]
    g.load(units, [view, run, info, call], [], edges)
    yield g
    g.close()
