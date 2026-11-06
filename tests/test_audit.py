import datetime
from adrgraph.adr import Decision, Rule
from adrgraph.audit import run_audit


def dec(id, status, rules, supersedes=(), review=None):
    return Decision(id, "t", status, "", "2026-01-01", review, list(supersedes), f"docs/adr/{id}.md", rules)


def never(rid, frm, to, via="CALLS"):
    return Rule(rid, "D", "never", {"from": frm, "to": to, "via": via}, "error", "")


def must(rid, every, has, via="CALLS", direction="out"):
    return Rule(rid, "D", "must", {"every": every, "has": has, "via": via, "direction": direction}, "error", "")


def checks(findings):
    return sorted((f.check, f.decision, f.rule) for f in findings)


TODAY = datetime.date(2026, 11, 5)


def test_orphan_and_overdue(layered):
    fs = run_audit(layered, [dec("ADR-1", "accepted", [never("o", {"path": "nowhere/**"}, {"path": "src/**"})], review="2026-01-01")], TODAY)
    assert checks(fs) == [("orphan", "ADR-1", "o"), ("overdue", "ADR-1", "")]
    assert all(f.severity == "warn" for f in fs)
    assert all(f.severity == "error" for f in run_audit(layered, [dec("ADR-1", "accepted", [], review="2026-01-01")], TODAY, strict=True))


def test_stale_and_dangling(layered):
    old = dec("ADR-1", "superseded", [never("s", {"path": "src/handlers/**"}, {"path": "src/contracts/**"})])
    new = dec("ADR-2", "accepted", [], supersedes=["ADR-1", "ADR-9"])
    fs = run_audit(layered, [old, new], TODAY)
    assert checks(fs) == [("dangling", "ADR-2", ""), ("stale", "ADR-1", "s")]
    dangling = next(f for f in fs if f.check == "dangling")
    assert dangling.severity == "error" and "ADR-9" in dangling.message
    still = dec("ADR-3", "accepted", [], supersedes=["ADR-2"])
    assert ("dangling", "ADR-3", "") in checks(run_audit(layered, [old, new, still], TODAY))


def test_contradiction_only_when_no_permitted_target(layered):
    m = must("m", {"path": "src/handlers/**", "kind": "function"}, {"path": "src/log.py"})
    n_total = never("n", {"path": "src/handlers/**"}, {"path": "src/log.py"})
    n_partial = never("n", {"path": "src/handlers/**"}, {"path": "src/db/**"})
    assert checks(run_audit(layered, [dec("ADR-1", "accepted", [m, n_total])], TODAY)) == [("contradiction", "ADR-1", "m")]
    assert checks(run_audit(layered, [dec("ADR-1", "accepted", [m, n_partial])], TODAY)) == []
    only_blocks = Rule("o", "D", "only", {"from": {"path": "src/contracts/**"}, "to": {"path": "src/log.py"}, "via": "CALLS"}, "error", "")
    assert checks(run_audit(layered, [dec("ADR-1", "accepted", [m, only_blocks])], TODAY)) == [("contradiction", "ADR-1", "m")]
    other_via = never("n", {"path": "src/handlers/**"}, {"path": "src/log.py"}, via="IMPORTS")
    assert checks(run_audit(layered, [dec("ADR-1", "accepted", [m, other_via])], TODAY)) == []


def test_dependency_and_declared_conflict(layered):
    a = dec("ADR-1", "accepted", []); a.depends_on = ["ADR-2", "ADR-9"]
    b = dec("ADR-2", "proposed", []); b.conflicts_with = ["ADR-3"]
    c = dec("ADR-3", "accepted", []); c.conflicts_with = []
    fs = run_audit(layered, [a, b, c], TODAY)
    assert checks(fs) == [("dependency", "ADR-1", ""), ("dependency", "ADR-1", "")]
    msgs = sorted(f.message for f in fs)
    assert "ADR-2" in msgs[0] and "proposed" in msgs[0] and "ADR-9" in msgs[1]
    b.status = "accepted"
    assert ("declared_conflict", "ADR-2", "") in checks(run_audit(layered, [a, b, c], TODAY))


def test_empty_scope_and_self_reference(layered):
    d = dec("ADR-1", "accepted", []); d.scope = [{"path": "src/handlers/**"}, {"path": "nowhere/**"}]; d.depends_on = ["ADR-1"]
    fs = run_audit(layered, [d], TODAY)
    assert checks(fs) == [("dependency", "ADR-1", ""), ("empty_scope", "ADR-1", "")]
    assert "names itself" in next(f for f in fs if f.check == "dependency").message
    assert "nowhere" in next(f for f in fs if f.check == "empty_scope").message


def test_never_with_absent_target_is_not_orphan(layered):
    # "never import X" is obeyed precisely when X is absent from the graph; only `from` can be orphaned.
    obeyed = never("n", {"path": "src/handlers/**"}, {"name": "tree_sitter*"})
    assert checks(run_audit(layered, [dec("ADR-1", "accepted", [obeyed])], TODAY)) == []
    no_subject = never("m", {"path": "nowhere/**"}, {"name": "tree_sitter*"})
    assert checks(run_audit(layered, [dec("ADR-1", "accepted", [no_subject])], TODAY)) == [("orphan", "ADR-1", "m")]
