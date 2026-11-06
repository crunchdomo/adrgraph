"""Evaluate every active rule, apply severity and baseline, compute metrics."""
from dataclasses import dataclass, field, replace

from srcgraph.graph import Graph

from adrgraph.adr import Decision
from adrgraph.baseline import Key
from adrgraph.schema import rule_key
from adrgraph.rules import Violation, bound_ids, evaluate, matched_ids


@dataclass
class RuleMetrics:
    bound: int | None
    violations: int


@dataclass
class Metrics:
    per_rule: dict[str, RuleMetrics] = field(default_factory=dict)
    per_adr: dict[str, float | None] = field(default_factory=dict)
    overall: float | None = None
    fixed: int = 0
    new: int = 0


@dataclass
class CheckResult:
    findings: list[Violation]
    metrics: Metrics
    failed: bool
    current: set[Key]


def bind(graph: Graph, decisions: list[Decision]) -> dict[str, list[str]]:
    return {rule_key(d.id, r.id): bound_ids(graph, r) or [] for d in decisions for r in d.rules}


def bind_scopes(graph: Graph, decisions: list[Decision]) -> dict[str, list[str]]:
    """Decision id -> every node its `scope` selectors match (rules or not)."""
    return {d.id: sorted({n for sel in d.scope for n in matched_ids(graph, sel)}) for d in decisions if d.scope}


def decision_binds(graph: Graph, decisions: list[Decision]) -> dict[str, list[str]]:
    """Decision id -> every node bound by its rules or its scope (rule keys contain '/', decision ids do not)."""
    out: dict[str, set[str]] = {}
    for key, nodes in {**bind(graph, decisions), **bind_scopes(graph, decisions)}.items():
        out.setdefault(key.split("/", 1)[0], set()).update(nodes)
    return {k: sorted(v) for k, v in out.items()}


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _compliance(rules: list[RuleMetrics]) -> float | None:
    bound = sum(m.bound for m in rules if m.bound)
    if not bound:
        return None
    return 1 - sum(m.violations for m in rules if m.bound) / bound


def run_check(graph: Graph, decisions: list[Decision], baseline: set[Key]) -> CheckResult:
    findings: list[Violation] = []
    metrics = Metrics()
    current: set[Key] = set()
    bound = bind(graph, decisions)
    for d in decisions:
        if d.status not in ("accepted", "proposed"):
            continue
        adr_rules = []
        for r in d.rules:
            key = rule_key(d.id, r.id)
            violations = evaluate(graph, r)
            severity = "warn" if d.status == "proposed" else r.severity
            for v in violations:
                k = (d.id, r.id, v.node_id)
                current.add(k)
                findings.append(replace(v, severity="baselined" if k in baseline else severity))
            rm = RuleMetrics(len(bound[key]) if r.shape != "cypher" else None, len(violations))
            metrics.per_rule[key] = rm
            adr_rules.append(rm)
        metrics.per_adr[d.id] = _compliance(adr_rules)
    for d, r, n in sorted(baseline - current):
        findings.append(Violation(d, r, n, "", 0, "no longer violated", severity="fixed"))
    metrics.overall = _compliance(list(metrics.per_rule.values()))
    metrics.fixed = sum(f.severity == "fixed" for f in findings)
    metrics.new = sum(f.severity in ("error", "warn") for f in findings)
    findings.sort(key=lambda f: (f.path, f.line, f.decision, f.rule, f.node_id))
    return CheckResult(findings, metrics, any(f.severity == "error" for f in findings), current)
