"""Findings overlay for srcgraph's explorer: the routes `adrgraph serve` mounts next to srcgraph's own."""
from srcgraph.graph import Graph
from srcgraph.source import Source

from adrgraph.adr import Decision
from adrgraph.check import CheckResult, decision_binds
from adrgraph.trail import build_trail, trail_dict


def overlay_routes(graph: Graph, decisions: list[Decision], result: CheckResult, baseline_path: str, source: Source) -> dict:
    """`/api/findings`: every finding with its trail. `/api/decisions`: decisions with rules and bound node ids."""
    trails = [trail_dict(build_trail(graph, decisions, f, result.findings, baseline_path, source.lines)) for f in result.findings]
    binds = decision_binds(graph, decisions)
    decs = [{"id": d.id, "title": d.title, "status": d.status, "path": d.path,
             "rules": [{"id": r.id, "shape": r.shape, "severity": r.severity, "description": r.description} for r in d.rules],
             "binds": binds.get(d.id, [])} for d in decisions]
    return {"/api/findings": lambda p: trails, "/api/decisions": lambda p: decs}
