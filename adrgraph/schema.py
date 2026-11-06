"""adrgraph's own graph tables, added to a srcgraph Graph through its schema-extension API."""
from srcgraph.graph import Graph
from srcgraph.model import Edge

from adrgraph.adr import Decision

ADR_NODE_TABLES = {
    "Decision": "id STRING, title STRING, status STRING, owner STRING, date STRING, review_date STRING, "
                "path STRING, PRIMARY KEY(id)",
    "Rule": "id STRING, decision STRING, rule_id STRING, shape STRING, cypher STRING, severity STRING, "
            "description STRING, PRIMARY KEY(id)",
}
ADR_REL_TABLES = {
    "HAS_RULE": ([("Decision", "Rule")], []),
    "SUPERSEDES": ([("Decision", "Decision")], []),
    "DEPENDS_ON": ([("Decision", "Decision")], []),
    "CONFLICTS_WITH": ([("Decision", "Decision")], []),
    "BINDS": ([("Rule", "Unit"), ("Rule", "Symbol"), ("Decision", "Unit"), ("Decision", "Symbol")], []),
}


def rule_key(decision_id: str, rule_id: str) -> str:
    return f"{decision_id}/{rule_id}"


def open_graph(path: str) -> Graph:
    """A fresh graph at `path` with adrgraph's tables added."""
    return Graph(path, node_tables=ADR_NODE_TABLES, rel_tables=ADR_REL_TABLES)


def load_adrs(graph: Graph, decisions: list[Decision]) -> None:
    graph.load_nodes("Decision", [{"id": d.id, "title": d.title, "status": d.status, "owner": d.owner, "date": d.date,
                                   "review_date": d.review_date or "", "path": d.path} for d in decisions])
    graph.load_nodes("Rule", [{"id": rule_key(d.id, r.id), "decision": d.id, "rule_id": r.id, "shape": r.shape,
                               "cypher": "", "severity": r.severity, "description": r.description}
                              for d in decisions for r in d.rules])
    edges: list[Edge] = []
    for d in decisions:
        edges += [Edge("HAS_RULE", d.id, rule_key(d.id, r.id)) for r in d.rules]
        edges += [Edge("SUPERSEDES", d.id, s) for s in d.supersedes]
        edges += [Edge("DEPENDS_ON", d.id, s) for s in d.depends_on]
        edges += [Edge("CONFLICTS_WITH", d.id, s) for s in d.conflicts_with]
    graph.load_edges(edges)  # targets that do not exist are dropped; audit reports them
