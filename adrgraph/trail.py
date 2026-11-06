"""Provenance trails: the chain from a decision to the syntax node behind one finding.

Everything a trail shows is already in the graph, the decisions, the check result and the source
files; `build_trail` only reads. Renderers (text, html, json) consume the Trail."""
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

from srcgraph.graph import Graph

from adrgraph.adr import Decision, Rule
from adrgraph.rules import Violation, portability, via_labels

EXCERPT_CONTEXT = 3
WHY = {
    "only": "outside the from set and not excepted",
    "never": "in the from set",
    "must": "in the every set with no matching edge",
    "cypher": "returned by the rule's query",
}
_EDGE_NORMS = {"IMPORTS": "Import", "CALLS": "Call"}


@dataclass(frozen=True)
class Excerpt:
    path: str
    start: int            # 1-based first line shown
    lines: list[str]
    highlight: int        # the line to mark


@dataclass(frozen=True)
class Step:
    kind: str             # decision | rule | node | edge | path | syntax | context
    title: str
    detail: dict
    excerpt: Excerpt | None


@dataclass(frozen=True)
class Trail:
    finding: Violation
    steps: tuple[Step, ...]


def trail_dict(trail: Trail) -> dict:
    """Plain dict, for `check --trails` and `explain --format json`."""
    return {"finding": asdict(trail.finding), "steps": [asdict(s) for s in trail.steps]}


def decision_text(markdown: str) -> str | None:
    """The first paragraph under a `## Decision` heading, or None."""
    m = re.search(r"^##[ \t]+Decision[ \t]*$\n+(.+?)(?:\n[ \t]*\n|\n#|\Z)", markdown, re.M | re.S)
    return " ".join(m[1].split()) or None if m else None


def excerpt(read_source: Callable[[str], list[str] | None], path: str, line: int) -> Excerpt | None:
    lines = read_source(path) if path else None
    if not lines or line < 1:
        return None
    start = max(1, line - EXCERPT_CONTEXT)
    end = min(len(lines), line + EXCERPT_CONTEXT)
    return Excerpt(path, start, lines[start - 1:end], min(line, len(lines)))


def build_trail(graph: Graph, decisions: list[Decision], finding: Violation, findings: list[Violation],
                baseline_path: str | None, read_source: Callable[[str], list[str] | None]) -> Trail:
    decision = next(d for d in decisions if d.id == finding.decision)
    rule = next(r for r in decision.rules if r.id == finding.rule)
    adr_lines = read_source(decision.path)
    steps = [
        Step("decision", f"{decision.id}  {decision.title}",
             {"id": decision.id, "title": decision.title, "status": decision.status, "path": decision.path,
              "decision_text": decision_text("\n".join(adr_lines)) if adr_lines else None}, None),
        Step("rule", f"rule {rule.id}",
             {"id": rule.id, "shape": rule.shape, "spec": rule.spec, "severity": rule.severity,
              "portability": portability(rule), "fixed": finding.severity == "fixed"}, None),
    ]
    if finding.severity != "fixed":
        steps += _node_steps(graph, rule, finding, read_source)
    steps.append(_context_step(graph, finding, findings, baseline_path))
    return Trail(finding, tuple(steps))


def _node_steps(graph: Graph, rule: Rule, finding: Violation, read_source) -> list[Step]:
    rows = graph.query("MATCH (n) WHERE n.id = $id RETURN label(n) AS label, n.kind AS kind, n.path AS path, n.line AS line",
                       {"id": finding.node_id})
    node = rows[0] if rows else {"label": "?", "kind": "?", "path": finding.path, "line": finding.line}
    steps = [Step("node", f"violates  {finding.path}:{finding.line}",
                  {"id": finding.node_id, "label": node["label"], "kind": node["kind"], "path": node["path"],
                   "line": finding.line, "why": WHY[rule.shape]},
                  excerpt(read_source, finding.path, finding.line))]
    if rule.shape == "cypher":
        return steps
    labels = "|".join(via_labels(rule))
    if finding.path_nodes:
        ids = list(finding.path_nodes)
        info = {r["id"]: r for r in graph.query(
            "MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, label(n) AS label, n.path AS path", {"ids": ids})}
        steps.append(Step("path", "path", {"nodes": [{"id": i, "label": info.get(i, {}).get("label", "?"),
                                                      "path": info.get(i, {}).get("path", "")} for i in ids]}, None))
    elif rule.shape == "must":
        arrow = f"-[r:{labels}]->" if rule.spec.get("direction", "out") == "out" else f"<-[r:{labels}]-"
        existing = graph.query(
            f"MATCH (a){arrow}(b) WHERE a.id = $id RETURN b.id AS target_id, label(b) AS target_kind, r.line AS line LIMIT 10",
            {"id": finding.node_id})
        steps.append(Step("edge", f"missing  {labels}", {"label": labels, "line": finding.line, "target_id": None,
                                                        "target_kind": None, "missing": True,
                                                        "existing": [dict(e) for e in existing]}, None))
    else:
        target = finding.message.split("reaches ", 1)[-1].split(" via ")[0]
        rows = graph.query(f"MATCH (a)-[r:{labels}]->(b) WHERE a.id = $id AND b.id = $t RETURN label(b) AS k, r.line AS line, b.kind AS bk",
                           {"id": finding.node_id, "t": target})
        kind = (rows[0]["bk"] if rows and rows[0]["k"] == "Unit" else (rows[0]["k"] if rows else "?"))
        steps.append(Step("edge", f"{labels} → {target}", {"label": labels, "line": rows[0]["line"] if rows else finding.line,
                                                           "target_id": target, "target_kind": kind, "missing": False,
                                                           "existing": []}, None))
    derived = graph.query("MATCH (n)-[:DERIVED_FROM]->(a:Ast) WHERE n.id = $id RETURN a.id AS id, a.kind AS kind, a.norm AS norm, a.line AS line, a.end_line AS end_line",
                          {"id": finding.node_id})
    if derived:
        detail = dict(derived[0])
        if not finding.path_nodes and rule.shape != "must":
            norm = _EDGE_NORMS.get(labels)
            if norm:
                # Any depth under the node's subtree: Ast nodes carry path and line, and the root's byte
                # range bounds the subtree without walking it.
                on_line = graph.query(
                    "MATCH (n)-[:DERIVED_FROM]->(root:Ast) WHERE n.id = $id "
                    "MATCH (x:Ast) WHERE x.path = root.path AND x.line = $line AND x.norm = $norm "
                    "AND x.start_byte >= root.start_byte AND x.end_byte <= root.end_byte "
                    "RETURN x.id AS id, x.kind AS kind, x.norm AS norm, x.line AS line ORDER BY x.start_byte LIMIT 1",
                    {"id": finding.node_id, "line": steps[-1].detail["line"], "norm": norm})
                if on_line:
                    detail["edge_syntax"] = dict(on_line[0])
        steps.append(Step("syntax", f"derived from  Ast {detail['kind']}", detail, None))
    return steps


def _context_step(graph: Graph, finding: Violation, findings: list[Violation], baseline_path: str | None) -> Step:
    governed = set()
    if finding.node_id and finding.severity != "fixed":
        # Only decisions that check evaluates (accepted, and proposed as warnings) can pass or fail.
        for r in graph.query("MATCH (d:Decision)-[:BINDS]->(n) WHERE n.id = $id AND d.status IN ['accepted', 'proposed'] RETURN d.id AS d",
                             {"id": finding.node_id}):
            governed.add(r["d"])
        for r in graph.query("MATCH (d:Decision)-[:HAS_RULE]->(r:Rule)-[:BINDS]->(n) WHERE n.id = $id AND d.status IN ['accepted', 'proposed'] RETURN d.id AS d",
                             {"id": finding.node_id}):
            governed.add(r["d"])
    governed.add(finding.decision)
    failing = {f.decision for f in findings if f.node_id == finding.node_id and f.severity in ("error", "warn", "baselined")}
    return Step("context", "context",
                {"governed_by": [{"decision": d, "result": "fails" if d in failing else "passes"} for d in sorted(governed)],
                 "baselined": finding.severity == "baselined",
                 "baseline_path": baseline_path if finding.severity == "baselined" else None}, None)
