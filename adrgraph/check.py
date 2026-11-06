"""Evaluate every active rule, apply severity and baseline, compute metrics."""
from dataclasses import dataclass, field

from adrgraph.adr import Decision
from adrgraph.baseline import Key
from adrgraph.graph import Graph, rule_key
from adrgraph.rules import bound_ids, evaluate

SEVERITIES = ("error", "warn", "baselined", "fixed")


@dataclass(frozen=True)
class Finding:
    severity: str
    decision: str
    rule: str
    node_id: str
    path: str
    line: int
    message: str


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
    findings: list[Finding]
    metrics: Metrics
    failed: bool
    current: set[Key]


def bind(graph: Graph, decisions: list[Decision]) -> dict[str, list[str]]:
    return {rule_key(d.id, r.id): bound_ids(graph, r) or [] for d in decisions for r in d.rules}


def _compliance(rules: list[RuleMetrics]) -> float | None:
    bound = sum(m.bound for m in rules if m.bound)
    if not bound:
        return None
    return 1 - sum(m.violations for m in rules if m.bound) / bound


def run_check(graph: Graph, decisions: list[Decision], baseline: set[Key]) -> CheckResult:
    findings: list[Finding] = []
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
                findings.append(Finding("baselined" if k in baseline else severity, d.id, r.id, v.node_id, v.path, v.line, v.message))
            rm = RuleMetrics(len(bound[key]) if r.shape != "cypher" else None, len(violations))
            metrics.per_rule[key] = rm
            adr_rules.append(rm)
        metrics.per_adr[d.id] = _compliance(adr_rules)
    for d, r, n in sorted(baseline - current):
        findings.append(Finding("fixed", d, r, n, "", 0, "no longer violated"))
    metrics.overall = _compliance(list(metrics.per_rule.values()))
    metrics.fixed = sum(f.severity == "fixed" for f in findings)
    metrics.new = sum(f.severity in ("error", "warn") for f in findings)
    findings.sort(key=lambda f: (f.path, f.line, f.decision, f.rule, f.node_id))
    return CheckResult(findings, metrics, any(f.severity == "error" for f in findings), current)
