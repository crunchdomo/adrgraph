"""Compile rule shapes (only / never / must) to Cypher and evaluate them. Raw cypher rules pass through."""
from dataclasses import dataclass

from adrgraph.adr import Rule
from adrgraph.graph import Graph
from adrgraph.model import EDGE_LABELS
from adrgraph.selectors import SelectorError, compile_selector

MAX_HOPS = 10
_RETURN = "RETURN DISTINCT {a}.id AS node_id, {a}.path AS path, {a}.line AS line, {msg} AS message"
_REQUIRED = ("only", "never", "must", "cypher")
_KEYS = {
    "only": {"from", "to", "via", "transitive"},
    "never": {"from", "to", "via", "transitive"},
    "must": {"every", "has", "via", "direction"},
}
_NEEDED = {"only": ("from", "to", "via"), "never": ("from", "to", "via"), "must": ("every", "has", "via")}


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Violation:
    decision: str
    rule: str
    node_id: str
    path: str
    line: int
    message: str


def bound_selector(rule: Rule) -> dict | None:
    if rule.shape == "cypher":
        return None
    return rule.spec[{"only": "to", "never": "from", "must": "every"}[rule.shape]]


def _via(spec: dict, err) -> str:
    via = spec["via"]
    labels = [via] if isinstance(via, str) else list(via)
    for label in labels:
        if label not in EDGE_LABELS:
            raise err(f"unknown edge label '{label}' in via (allowed: {', '.join(sorted(EDGE_LABELS))})")
    return "|".join(labels)


def compile_rule(rule: Rule) -> tuple[str, dict]:
    if rule.shape == "cypher":
        return rule.spec, {}

    def err(msg: str) -> RuleError:
        return RuleError(f"{rule.decision}/{rule.id}: {msg}")

    spec = rule.spec if isinstance(rule.spec, dict) else {}
    for key in spec:
        if key not in _KEYS[rule.shape]:
            raise err(f"unknown key '{key}' for shape {rule.shape}")
    for key in _NEEDED[rule.shape]:
        if key not in spec:
            raise err(f"shape {rule.shape} needs '{key}'")
    via = _via(spec, err)
    try:
        if rule.shape == "must":
            direction = spec.get("direction", "out")
            if direction not in ("out", "in"):
                raise err("direction must be 'out' or 'in'")
            e, pe = compile_selector(spec["every"], "e", "e")
            h, ph = compile_selector(spec["has"], "h", "h")
            arrow = f"-[:{via}]->" if direction == "out" else f"<-[:{via}]-"
            q = (f"MATCH (e) WHERE ({e}) AND NOT EXISTS {{ MATCH (e){arrow}(h) WHERE ({h}) }} "
                 + _RETURN.format(a="e", msg=f"'has no {via} edge {'to' if direction == 'out' else 'from'} a matching node'"))
            return q, {**pe, **ph}

        f, pf = compile_selector(spec["from"], "a", "f")
        t, pt = compile_selector(spec["to"], "b", "t")
        transitive = bool(spec.get("transitive", False))
        if rule.shape == "only" and transitive:
            n, pn = compile_selector(spec["from"], "n", "n")
            rel = f"-[:{via}*1..{MAX_HOPS} (r, n | WHERE NOT ({n}))]->"
            pf = {**pf, **pn}
        else:
            rel = f"-[:{via}*1..{MAX_HOPS}]->" if transitive else f"-[:{via}]->"
        cond = f"NOT ({f})" if rule.shape == "only" else f"({f})"
        q = f"MATCH (a){rel}(b) WHERE {cond} AND ({t}) " + _RETURN.format(a="a", msg="'reaches ' + b.id")
        return q, {**pf, **pt}
    except SelectorError as exc:
        raise err(str(exc)) from exc


def evaluate(graph: Graph, rule: Rule) -> list[Violation]:
    cypher, params = compile_rule(rule)
    try:
        rows = graph.query(cypher, params)
    except RuntimeError as exc:
        raise RuleError(f"{rule.decision}/{rule.id}: query failed: {exc}") from exc
    seen, out = set(), []
    for row in rows:
        for col in ("node_id", "path", "line", "message"):
            if col not in row:
                raise RuleError(f"{rule.decision}/{rule.id}: query must return {col}")
        if row["node_id"] in seen:
            continue
        seen.add(row["node_id"])
        out.append(Violation(rule.decision, rule.id, row["node_id"], row["path"] or "", int(row["line"] or 0), str(row["message"])))
    return sorted(out, key=lambda v: (v.path, v.line, v.node_id))
