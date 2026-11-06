"""LadybugDB-backed property graph: schema, bulk load, query. The only module that imports ladybug."""
import os
from collections import defaultdict

import ladybug

from adrgraph.adr import Decision
from adrgraph.model import Edge, Symbol, Unit

NODE_TABLES = {
    "Unit": "id STRING, path STRING, name STRING, lang STRING, kind STRING, line INT64, PRIMARY KEY(id)",
    "Symbol": "id STRING, name STRING, qualified STRING, kind STRING, lang STRING, path STRING, "
              "line INT64, end_line INT64, ast_kind STRING, PRIMARY KEY(id)",
    "Decision": "id STRING, title STRING, status STRING, owner STRING, date STRING, review_date STRING, "
                "path STRING, PRIMARY KEY(id)",
    "Rule": "id STRING, decision STRING, rule_id STRING, shape STRING, cypher STRING, severity STRING, "
            "description STRING, PRIMARY KEY(id)",
}
REL_TABLES = {
    "CONTAINS": [("Unit", "Unit"), ("Unit", "Symbol"), ("Symbol", "Symbol")],
    "IMPORTS": [("Unit", "Unit")],
    "CALLS": [("Symbol", "Symbol"), ("Unit", "Symbol")],
    "REFERENCES": [("Symbol", "Symbol"), ("Symbol", "Unit"), ("Unit", "Symbol"), ("Unit", "Unit")],
    "HAS_RULE": [("Decision", "Rule")],
    "SUPERSEDES": [("Decision", "Decision")],
    "BINDS": [("Rule", "Unit"), ("Rule", "Symbol")],
}
_COLS = {t: [c.split()[0] for c in ddl.split(", ") if not c.startswith("PRIMARY")] for t, ddl in NODE_TABLES.items()}


def rule_key(decision_id: str, rule_id: str) -> str:
    return f"{decision_id}/{rule_id}"


class Graph:
    def __init__(self, path: str):
        for p in (path, path + ".wal"):
            if os.path.exists(p):
                os.remove(p)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = ladybug.Database(path)
        self._conn = ladybug.Connection(self._db)
        for table, ddl in NODE_TABLES.items():
            self._conn.execute(f"CREATE NODE TABLE {table}({ddl})")
        for label, pairs in REL_TABLES.items():
            spec = ", ".join(f"FROM {a} TO {b}" for a, b in pairs)
            self._conn.execute(f"CREATE REL TABLE {label}({spec})")

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        result = self._conn.execute(cypher, params or {})
        cols = result.get_column_names()
        rows = []
        while result.has_next():
            rows.append(dict(zip(cols, result.get_next())))
        result.close()
        return rows

    def count(self, label: str) -> int:
        return self.query(f"MATCH (n:{label}) RETURN count(*) AS c")[0]["c"]

    def load(self, units: list[Unit], symbols: list[Symbol], decisions: list[Decision],
             edges: list[Edge], binds: list[tuple[str, str]] = ()) -> None:
        rows = {
            "Unit": [{"id": u.id, "path": u.path, "name": u.name, "lang": u.lang, "kind": u.kind, "line": 1} for u in units],
            "Symbol": [vars(s) for s in symbols],
            "Decision": [{"id": d.id, "title": d.title, "status": d.status, "owner": d.owner, "date": d.date,
                          "review_date": d.review_date or "", "path": d.path} for d in decisions],
            "Rule": [{"id": rule_key(d.id, r.id), "decision": d.id, "rule_id": r.id, "shape": r.shape, "cypher": "",
                      "severity": r.severity, "description": r.description} for d in decisions for r in d.rules],
        }
        table_of: dict[str, str] = {}
        for table, items in rows.items():
            for item in items:
                table_of[item["id"]] = table
            if items:
                props = ", ".join(f"{c}: r.{c}" for c in _COLS[table])
                self._conn.execute(f"UNWIND $rows AS r CREATE (:{table} {{{props}}})", {"rows": items})

        all_edges = list(edges)
        for d in decisions:
            all_edges += [Edge("HAS_RULE", d.id, rule_key(d.id, r.id)) for r in d.rules]
            all_edges += [Edge("SUPERSEDES", d.id, s) for s in d.supersedes]
        all_edges += [Edge("BINDS", r, n) for r, n in binds]

        grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for e in all_edges:
            src, dst = table_of.get(e.src), table_of.get(e.dst)
            if src and dst and (src, dst) in REL_TABLES[e.label]:
                grouped[(e.label, src, dst)].append({"a": e.src, "b": e.dst})
        for (label, src, dst), items in grouped.items():
            self._conn.execute(
                f"UNWIND $e AS e MATCH (a:{src} {{id: e.a}}), (b:{dst} {{id: e.b}}) CREATE (a)-[:{label}]->(b)",
                {"e": items})

    def close(self) -> None:
        self._conn.close()
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
