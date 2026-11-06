"""LadybugDB-backed property graph: schema, bulk load via COPY FROM, query. The only module that imports ladybug."""
import csv
import os
import tempfile
from collections import defaultdict

import ladybug

from adrgraph.adr import Decision
from adrgraph.model import AstNode, Edge, Symbol, Unit

NODE_TABLES = {
    "Unit": "id STRING, path STRING, name STRING, lang STRING, kind STRING, line INT64, PRIMARY KEY(id)",
    "Symbol": "id STRING, name STRING, qualified STRING, kind STRING, lang STRING, path STRING, "
              "line INT64, end_line INT64, ast_kind STRING, PRIMARY KEY(id)",
    "Decision": "id STRING, title STRING, status STRING, owner STRING, date STRING, review_date STRING, "
                "path STRING, PRIMARY KEY(id)",
    "Rule": "id STRING, decision STRING, rule_id STRING, shape STRING, cypher STRING, severity STRING, "
            "description STRING, PRIMARY KEY(id)",
    "Ast": "id STRING, path STRING, kind STRING, norm STRING, lang STRING, line INT64, end_line INT64, "
           "start_byte INT64, end_byte INT64, text STRING, field STRING, PRIMARY KEY(id)",
}
_REF_PAIRS = [("Symbol", "Symbol"), ("Symbol", "Unit"), ("Unit", "Symbol"), ("Unit", "Unit")]
# label -> (from/to pairs, extra property columns)
REL_TABLES = {
    "CONTAINS": ([("Unit", "Unit"), ("Unit", "Symbol"), ("Symbol", "Symbol")], ["line"]),
    "IMPORTS": ([("Unit", "Unit")], ["line"]),
    "CALLS": ([("Symbol", "Symbol"), ("Unit", "Symbol")], ["line"]),
    "REFERENCES": (_REF_PAIRS, ["line"]),
    "INHERITS": ([("Symbol", "Symbol")], ["line"]),
    "DECORATES": ([("Symbol", "Symbol")], ["line"]),
    "READS": (_REF_PAIRS, ["line"]),
    "WRITES": (_REF_PAIRS, ["line"]),
    "TYPE_OF": (_REF_PAIRS, ["line"]),
    "OVERRIDES": (_REF_PAIRS, ["line"]),
    "DERIVED_FROM": ([("Unit", "Ast"), ("Symbol", "Ast")], []),
    "CHILD": ([("Ast", "Ast")], ["field"]),
    "NEXT": ([("Ast", "Ast")], []),
    "HAS_RULE": ([("Decision", "Rule")], []),
    "SUPERSEDES": ([("Decision", "Decision")], []),
    "DEPENDS_ON": ([("Decision", "Decision")], []),
    "CONFLICTS_WITH": ([("Decision", "Decision")], []),
    "BINDS": ([("Rule", "Unit"), ("Rule", "Symbol"), ("Decision", "Unit"), ("Decision", "Symbol")], []),
}
_COLS = {t: [c.split()[0] for c in ddl.split(", ") if not c.startswith("PRIMARY")] for t, ddl in NODE_TABLES.items()}
_PROP_TYPES = {"line": "INT64", "field": "STRING"}


def rule_key(decision_id: str, rule_id: str) -> str:
    return f"{decision_id}/{rule_id}"


def escape(s: str) -> str:
    """CSV string cell: LadybugDB's parallel reader rejects quoted newlines."""
    return s.replace("\r", "\\r").replace("\n", "\\n")


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
        for label, (pairs, props) in REL_TABLES.items():
            spec = ", ".join(f"FROM {a} TO {b}" for a, b in pairs)
            cols = "".join(f", {p} {_PROP_TYPES[p]}" for p in props)
            self._conn.execute(f"CREATE REL TABLE {label}({spec}{cols})")

    @classmethod
    def open(cls, path: str) -> "Graph":
        """Open an existing database without rebuilding the schema."""
        if not os.path.exists(path):
            raise RuntimeError(f"{path} does not exist; run `adrgraph build` first")
        g = cls.__new__(cls)
        g._db = ladybug.Database(path)
        g._conn = ladybug.Connection(g._db)
        return g

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

    def load(self, units: list[Unit], symbols: list[Symbol], decisions: list[Decision], edges: list[Edge],
             binds: list[tuple[str, str]] = (), ast: list[AstNode] = (), ast_edges: list[Edge] = ()) -> None:
        rows = {
            "Unit": [{"id": u.id, "path": u.path, "name": u.name, "lang": u.lang, "kind": u.kind, "line": 1} for u in units],
            "Symbol": [vars(s) for s in symbols],
            "Decision": [{"id": d.id, "title": d.title, "status": d.status, "owner": d.owner, "date": d.date,
                          "review_date": d.review_date or "", "path": d.path} for d in decisions],
            "Rule": [{"id": rule_key(d.id, r.id), "decision": d.id, "rule_id": r.id, "shape": r.shape, "cypher": "",
                      "severity": r.severity, "description": r.description} for d in decisions for r in d.rules],
            "Ast": [vars(a) for a in ast],
        }
        table_of: dict[str, str] = {}
        for table, items in rows.items():
            for item in items:
                table_of[item["id"]] = table
        ast_field = {a.id: a.field for a in ast}

        all_edges = list(edges) + list(ast_edges)
        for d in decisions:
            all_edges += [Edge("HAS_RULE", d.id, rule_key(d.id, r.id)) for r in d.rules]
            all_edges += [Edge("SUPERSEDES", d.id, s) for s in d.supersedes]
            all_edges += [Edge("DEPENDS_ON", d.id, s) for s in getattr(d, "depends_on", [])]
            all_edges += [Edge("CONFLICTS_WITH", d.id, s) for s in getattr(d, "conflicts_with", [])]
        all_edges += [Edge("BINDS", r, n) for r, n in binds]

        unknown = {i for e in all_edges for i in (e.src, e.dst) if i not in table_of}
        if unknown:
            for row in self.query("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, label(n) AS t", {"ids": sorted(unknown)}):
                table_of[row["id"]] = row["t"]

        grouped: dict[tuple[str, str, str], list[list]] = defaultdict(list)
        for e in all_edges:
            src, dst = table_of.get(e.src), table_of.get(e.dst)
            pairs, props = REL_TABLES[e.label]
            if src and dst and (src, dst) in pairs:
                extra = [e.line if p == "line" else ast_field.get(e.dst, "") for p in props]
                grouped[(e.label, src, dst)].append([e.src, e.dst, *extra])

        with tempfile.TemporaryDirectory() as tmp:
            for table, items in rows.items():
                if not items:
                    continue
                path = os.path.join(tmp, f"{table}.csv")
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    for item in items:
                        w.writerow([escape(v) if isinstance(v, str) else v for v in (item[c] for c in _COLS[table])])
                self._conn.execute(f"COPY {table} FROM '{path}'")
            for (label, src, dst), items in grouped.items():
                path = os.path.join(tmp, f"{label}_{src}_{dst}.csv")
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    for item in items:
                        w.writerow([escape(v) if isinstance(v, str) else v for v in item])
                self._conn.execute(f"COPY {label} FROM '{path}' (from='{src}', to='{dst}')")

    def close(self) -> None:
        self._conn.close()
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
