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


def matched_ids(graph: Graph, selector: dict) -> list[str]:
    frag, params = compile_selector(selector, "n", "s")
    return sorted(r["id"] for r in graph.query(f"MATCH (n) WHERE {frag} RETURN n.id AS id", params))


def bound_ids(graph: Graph, rule: Rule) -> list[str] | None:
    """The population a rule is measured against; every violator is a member of it."""
    if rule.shape == "cypher":
        return None
    if rule.shape == "never":
        return matched_ids(graph, rule.spec["from"])
    if rule.shape == "must":
        return matched_ids(graph, rule.spec["every"])
    rel, params = _relation(rule)
    t, pt = compile_selector(rule.spec["to"], "b", "t")
    rows = graph.query(f"MATCH (a){rel}(b) WHERE ({t}) RETURN DISTINCT a.id AS id", {**params, **pt})
    return sorted(r["id"] for r in rows)


def _via(spec: dict, err) -> str:
    via = spec["via"]
    labels = [via] if isinstance(via, str) else via
    if not isinstance(labels, list) or not labels or not all(isinstance(x, str) for x in labels):
        raise err("via must be an edge label or a list of edge labels")
    for label in labels:
        if label not in EDGE_LABELS:
            raise err(f"unknown edge label '{label}' in via (allowed: {', '.join(sorted(EDGE_LABELS))})")
    return "|".join(labels)


def _relation(rule: Rule) -> tuple[str, dict]:
    """The relationship pattern for an only/never rule (direct, or shortest paths when transitive)."""
    err = lambda msg: RuleError(f"{rule.decision}/{rule.id}: {msg}")
    via = _via(rule.spec, err)
    transitive = rule.spec.get("transitive", False)
    if not isinstance(transitive, bool):
        raise err("transitive must be true or false")
    if not transitive:
        return f"-[:{via}]->", {}
    if rule.shape == "only":
        n, pn = compile_selector(rule.spec["from"], "n", "n")
        return f"-[:{via}* SHORTEST 1..{MAX_HOPS} (r, n | WHERE NOT ({n}))]->", pn
    return f"-[:{via}* SHORTEST 1..{MAX_HOPS}]->", {}


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
            for key in ("every", "has"):
                if not isinstance(spec[key], dict):
                    raise err(f"'{key}' must be a selector map")
            e, pe = compile_selector(spec["every"], "e", "e")
            h, ph = compile_selector(spec["has"], "h", "h")
            arrow = f"-[:{via}]->" if direction == "out" else f"<-[:{via}]-"
            q = (f"MATCH (e) WHERE ({e}) AND NOT EXISTS {{ MATCH (e){arrow}(h) WHERE ({h}) }} "
                 + _RETURN.format(a="e", msg=f"'has no {via} edge {'to' if direction == 'out' else 'from'} a matching node'"))
            return q, {**pe, **ph}

        for key in ("from", "to"):
            if not isinstance(spec[key], dict):
                raise err(f"'{key}' must be a selector map")
        f, pf = compile_selector(spec["from"], "a", "f")
        t, pt = compile_selector(spec["to"], "b", "t")
        rel, pr = _relation(rule)
        cond = f"NOT ({f})" if rule.shape == "only" else f"({f})"
        q = f"MATCH (a){rel}(b) WHERE {cond} AND ({t}) " + _RETURN.format(a="a", msg="'reaches ' + b.id")
        return q, {**pf, **pr, **pt}
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
