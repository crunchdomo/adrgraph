"""ADR-level checks: orphan rules, stale rules, dangling supersession, overdue reviews, contradictions."""
import datetime
from dataclasses import dataclass

from adrgraph.adr import Decision, Rule
from adrgraph.check import matched_ids
from adrgraph.graph import Graph
from adrgraph.rules import evaluate

_SELECTOR_KEYS = {"only": ("from", "to"), "never": ("from", "to"), "must": ("every", "has")}


@dataclass(frozen=True)
class AuditFinding:
    check: str
    severity: str
    decision: str
    rule: str
    message: str


def _via(rule: Rule) -> set[str]:
    via = rule.spec["via"]
    return {via} if isinstance(via, str) else set(via)


def run_audit(graph: Graph, decisions: list[Decision], today: datetime.date, strict: bool = False) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    soft = "error" if strict else "warn"
    by_id = {d.id: d for d in decisions}
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

    accepted = [(d, r) for d in decisions if d.status == "accepted" for r in d.rules]
    for d, m in accepted:
        if m.shape != "must":
            continue
        every, has = set(bound(d, m, "every")), set(bound(d, m, "has"))
        inbound = m.spec.get("direction", "out") == "in"
        for d2, other in accepted:
            if other.shape not in ("never", "only") or not (_via(m) & _via(other)):
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
