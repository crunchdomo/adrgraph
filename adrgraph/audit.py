"""ADR-level checks: orphan rules, stale rules, dangling supersession, overdue reviews, contradictions."""
import datetime
from dataclasses import dataclass

from srcgraph.graph import Graph

from adrgraph.adr import Decision, Rule
from adrgraph.rules import evaluate, matched_ids, via_labels

# Selectors whose emptiness means the rule is mis-scoped. A `never` rule's `to` is left out: when the
# forbidden target is absent from the graph the rule is simply obeyed.
_SELECTOR_KEYS = {"only": ("from", "to"), "never": ("from",), "must": ("every", "has")}


@dataclass(frozen=True)
class AuditFinding:
    check: str
    severity: str
    decision: str
    rule: str
    message: str


def run_audit(graph: Graph, decisions: list[Decision], today: datetime.date, strict: bool = False) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    soft = "error" if strict else "warn"
    by_id = {d.id: d for d in decisions}
    conflicts_seen: set[tuple[str, str]] = set()
    sets: dict[tuple[str, str, str], list[str]] = {}

    def bound(d: Decision, r: Rule, key: str) -> list[str]:
        k = (d.id, r.id, key)
        if k not in sets:
            sets[k] = matched_ids(graph, r.spec[key])
        return sets[k]

    for d in decisions:
        active = d.status in ("accepted", "proposed")
        for r in d.rules:
            if active and r.shape in _SELECTOR_KEYS:
                for key in _SELECTOR_KEYS[r.shape]:
                    if not bound(d, r, key):
                        out.append(AuditFinding("orphan", soft, d.id, r.id, f"selector '{key}' matches no nodes"))
            if d.status in ("superseded", "deprecated"):
                n = len(evaluate(graph, r))
                if n:
                    out.append(AuditFinding("stale", soft, d.id, r.id, f"{d.status} decision's rule still finds {n} violation(s)"))
        for s in d.supersedes:
            if s not in by_id:
                out.append(AuditFinding("dangling", "error", d.id, "", f"supersedes unknown decision {s}"))
            elif by_id[s].status == "accepted":
                out.append(AuditFinding("dangling", "error", d.id, "", f"supersedes {s}, which is still accepted"))
        if d.status == "accepted" and d.review_date and datetime.date.fromisoformat(d.review_date) < today:
            out.append(AuditFinding("overdue", soft, d.id, "", f"review date {d.review_date} has passed"))
        if d.status != "accepted":
            continue
        for s in d.depends_on:
            if s == d.id:
                out.append(AuditFinding("dependency", "error", d.id, "", "depends_on names itself"))
            elif s not in by_id:
                out.append(AuditFinding("dependency", "error", d.id, "", f"depends on unknown decision {s}"))
            elif by_id[s].status != "accepted":
                out.append(AuditFinding("dependency", "error", d.id, "", f"depends on {s}, which is {by_id[s].status}"))
        for s in d.conflicts_with:
            if s == d.id:
                out.append(AuditFinding("declared_conflict", "error", d.id, "", "conflicts_with names itself"))
            elif s in by_id and by_id[s].status == "accepted":
                pair = tuple(sorted((d.id, s)))
                if pair not in conflicts_seen:
                    conflicts_seen.add(pair)
                    out.append(AuditFinding("declared_conflict", "error", pair[0], "",
                                            f"{d.id} declares a conflict with {s}; both are accepted"))
        for sel in d.scope:
            if not matched_ids(graph, sel):
                out.append(AuditFinding("empty_scope", soft, d.id, "", f"scope {sel} matches no nodes"))

    accepted = [(d, r) for d in decisions if d.status == "accepted" for r in d.rules]
    for d, m in accepted:
        if m.shape != "must":
            continue
        every, has = set(bound(d, m, "every")), set(bound(d, m, "has"))
        inbound = m.spec.get("direction", "out") == "in"
        for d2, other in accepted:
            if other.shape not in ("never", "only") or not (set(via_labels(m)) & set(via_labels(other))):
                continue
            frm, to = set(bound(d2, other, "from")), set(bound(d2, other, "to"))
            for e in sorted(every):
                # pairs the must needs: e -> h (out) or h -> e (in); the other rule forbids src -> dst
                if inbound:
                    forbidden = {h for h in has if (h in frm if other.shape == "never" else h not in frm) and e in to}
                else:
                    forbidden = to if (e in frm if other.shape == "never" else e not in frm) else set()
                if has and has <= forbidden:
                    out.append(AuditFinding("contradiction", "error", d.id, m.id,
                                            f"cannot be satisfied: every permitted target is forbidden by {d2.id}/{other.id}"))
                    break
    return sorted(out, key=lambda f: (f.decision, f.rule, f.check))
