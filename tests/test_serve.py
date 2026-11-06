import json
import os
import threading
import urllib.request

import pytest
from srcgraph.serve import make_server
from srcgraph.source import Source

from adrgraph.baseline import load_baseline
from adrgraph.check import run_check
from adrgraph.cli import build
from adrgraph.serve import overlay_routes


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    cwd = os.getcwd()
    os.chdir("tests/fixtures/pyrepo")
    graph, decisions, _ = build(["docs/adr"], ["."], (), str(tmp_path_factory.mktemp("db") / "g.lbug"))
    result = run_check(graph, decisions, load_baseline("nope.json"))
    srv = make_server(graph, Source("."), port=0, routes=overlay_routes(graph, decisions, result, "nope.json", Source(".")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    graph.close()
    os.chdir(cwd)


def get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return json.loads(r.read())


def test_findings_route_serves_trails(server):
    trails = get(server, "/api/findings")
    f = next(t for t in trails if t["finding"]["node_id"] == "src/other/x.py")
    assert f["finding"]["severity"] == "error" and f["steps"][0]["kind"] == "decision"
    assert any(s["kind"] == "context" for s in f["steps"])


def test_decisions_route_lists_rules_and_binds(server):
    decs = get(server, "/api/decisions")
    d = next(x for x in decs if x["id"] == "ADR-0001")
    assert d["status"] == "accepted" and {r["id"] for r in d["rules"]} >= {"gateway-only-via-contracts"}
    assert "src/other/x.py" in d["binds"]


def test_base_routes_still_work_under_the_overlay(server):
    assert get(server, "/api/node?id=src/other/x.py")["label"] == "Unit"
