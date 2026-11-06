"""Compile rule shapes (only / never / must) to Cypher and evaluate them. Raw cypher rules pass through."""
from dataclasses import dataclass

from srcgraph.graph import Graph
from srcgraph.model import EDGE_LABELS
from srcgraph.selectors import SelectorError, compile_selector

from adrgraph.adr import Rule

MAX_HOPS = 10
_RETURN = "RETURN DISTINCT {a}.id AS node_id, {a}.path AS path, {a}.line AS line, {msg} AS message"
# Direct edge rules also return the edge's own line; transitive rules return the path and its first hop's line.
_RETURN_EDGE = ("RETURN DISTINCT {a}.id AS node_id, {a}.path AS path, {a}.line AS line, r.line AS edge_line, "
                "{msg} AS message")
_RETURN_PATH = ("RETURN {a}.id AS node_id, {a}.path AS path, {a}.line AS line, "
                "list_transform(rels(p), r -> r.line)[1] AS edge_line, "
                "list_transform(nodes(p), x -> x.id) AS path_nodes, {msg} AS message")
_REQUIRED = ("only", "never", "must", "cypher")
_KEYS = {
    "only": {"from", "to", "via", "transitive", "except"},
    "never": {"from", "to", "via", "transitive", "except"},
    "must": {"every", "has", "via", "direction", "except"},
}
_SUBJECT = {"only": "from", "never": "from", "must": "every"}
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
    path_nodes: tuple[str, ...] = ()


def matched_ids(graph: Graph, selector: dict, excepts: list[dict] = ()) -> list[str]:
    frag, params = compile_selector(selector, "n", "s")
    for i, ex in enumerate(excepts):
        xf, xp = compile_selector(ex, "n", f"x{i}")
        frag += f" AND NOT ({xf})"
        params.update(xp)
    return sorted(r["id"] for r in graph.query(f"MATCH (n) WHERE {frag} RETURN n.id AS id", params))


def _excepts(rule: Rule) -> list[dict]:
    """The validated `except` list of a shape rule (empty for cypher rules)."""
    if rule.shape == "cypher":
        return []
    ex = rule.spec.get("except", [])
    if not isinstance(ex, list) or not all(isinstance(x, dict) for x in ex):
        raise RuleError(f"{rule.decision}/{rule.id}: except must be a list of selector maps")
    return ex


def _except_fragment(rule: Rule, var: str) -> tuple[str, dict]:
    """`AND NOT (...)` clauses excluding the rule's except selectors from the subject variable."""
    frag, params = "", {}
    for i, ex in enumerate(_excepts(rule)):
        xf, xp = compile_selector(ex, var, f"x{i}")
        frag += f" AND NOT ({xf})"
        params.update(xp)
    return frag, params


def portability(rule: Rule) -> str:
    """How far the rule travels across languages: semantic, normalised, or grammar (lang)."""
    if rule.shape != "cypher" or ":Ast" not in rule.spec:
        return "semantic"
    if ".kind" in rule.spec or "kind:" in rule.spec:
        return f"grammar ({rule.lang})" if rule.lang else "grammar (unspecified)"
    return "normalised"


def bound_ids(graph: Graph, rule: Rule) -> list[str] | None:
    """The population a rule is measured against; every violator is a member of it."""
    if rule.shape == "cypher":
        return None
    if rule.shape in ("never", "must"):
        return matched_ids(graph, rule.spec[_SUBJECT[rule.shape]], _excepts(rule))
    rel, params = _relation(rule)
    t, pt = compile_selector(rule.spec["to"], "b", "t")
    xf, xp = _except_fragment(rule, "a")
    rows = graph.query(f"MATCH (a){rel}(b) WHERE ({t}){xf} RETURN DISTINCT a.id AS id", {**params, **pt, **xp})
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
        return f"-[r:{via}]->", {}
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
        xf, xp = _except_fragment(rule, "e" if rule.shape == "must" else "a")
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
            q = (f"MATCH (e) WHERE ({e}){xf} AND NOT EXISTS {{ MATCH (e){arrow}(h) WHERE ({h}) }} "
                 + _RETURN.format(a="e", msg=f"'has no {via} edge {'to' if direction == 'out' else 'from'} a matching node'"))
            return q, {**pe, **ph, **xp}

        for key in ("from", "to"):
            if not isinstance(spec[key], dict):
                raise err(f"'{key}' must be a selector map")
        f, pf = compile_selector(spec["from"], "a", "f")
        t, pt = compile_selector(spec["to"], "b", "t")
        rel, pr = _relation(rule)
        cond = f"NOT ({f})" if rule.shape == "only" else f"({f})"
        transitive = bool(spec.get("transitive", False))
        head = "MATCH p = (a)" if transitive else "MATCH (a)"
        ret = (_RETURN_PATH if transitive else _RETURN_EDGE).format(a="a", msg="'reaches ' + b.id")
        q = f"{head}{rel}(b) WHERE {cond}{xf} AND ({t}) " + ret
        return q, {**pf, **pr, **pt, **xp}
    except SelectorError as exc:
        raise err(str(exc)) from exc


def evaluate(graph: Graph, rule: Rule) -> list[Violation]:
    cypher, params = compile_rule(rule)
    try:
        rows = graph.query(cypher, params)
    except RuntimeError as exc:
        raise RuleError(f"{rule.decision}/{rule.id}: query failed: {exc}") from exc
    for row in rows:
        for col in ("node_id", "path", "line", "message"):
            if col not in row:
                raise RuleError(f"{rule.decision}/{rule.id}: query must return {col}")
    # Several rows per node (one per edge or path): keep the one with the lowest line.
    rows.sort(key=lambda r: (r["node_id"], int(r.get("edge_line") or r["line"] or 0)))
    seen, out = set(), []
    for row in rows:
        if row["node_id"] in seen:
            continue
        seen.add(row["node_id"])
        line = int(row.get("edge_line") or row["line"] or 0)
        path_nodes = tuple(row.get("path_nodes") or ())
        message = str(row["message"])
        if path_nodes:
            message = f"reaches {path_nodes[-1]} via {' -> '.join(path_nodes[1:])}"
        out.append(Violation(rule.decision, rule.id, row["node_id"], row["path"] or "", line, message, path_nodes))
    return sorted(out, key=lambda v: (v.path, v.line, v.node_id))
