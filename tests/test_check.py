import pytest
from adrgraph.adr import Decision, Rule
from adrgraph.check import run_check, bind
from adrgraph.baseline import load_baseline, save_baseline

ONLY = Rule("gw", "ADR-1", "only", {"from": {"path": "src/contracts/**"}, "to": {"path": "src/gateway/client.py"}, "via": "IMPORTS"}, "error", "")
NEVER_T = Rule("db", "ADR-1", "never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/db/**"}, "via": "CALLS", "transitive": True}, "warn", "")
ORPHAN = Rule("orphan", "ADR-2", "never", {"from": {"path": "nowhere/**"}, "to": {"path": "src/**"}, "via": "CALLS"}, "error", "")


def dec(id, status, rules):
    return Decision(id, "t", status, "", "2026-01-01", None, [], f"docs/adr/{id}.md", rules)


def test_severities_and_metrics(layered):
    r = run_check(layered, [dec("ADR-1", "accepted", [ONLY, NEVER_T]), dec("ADR-2", "proposed", [Rule("x", "ADR-2", "never", NEVER_T.spec, "error", "")])], set())
    sev = {(f.rule, f.node_id): f.severity for f in r.findings}
    assert sev[("gw", "src/other/x.py")] == "error"
    assert sev[("db", "src/handlers/h.py::h.view")] == "warn"
    assert sev[("x", "src/handlers/h.py::h.view")] == "warn"      # proposed -> warn
    assert r.failed
    # only: bound = distinct nodes reaching `to` (c.py, x.py) -> 2, 1 violation
    assert r.metrics.per_rule["ADR-1/gw"].bound == 2 and r.metrics.per_rule["ADR-1/gw"].violations == 1
    # ADR-1: gw 2 bound / 1 violation; db bound 2 (h.py unit + h.view) / 1 violation -> 1 - 2/4
    assert r.metrics.per_adr["ADR-1"] == pytest.approx(0.5) and r.metrics.per_adr["ADR-2"] == pytest.approx(0.5)
    assert r.metrics.overall == pytest.approx(0.5) and r.metrics.new == 3 and r.metrics.fixed == 0


def test_skipped_statuses_and_orphan(layered):
    r = run_check(layered, [dec("ADR-1", "superseded", [ONLY]), dec("ADR-2", "accepted", [ORPHAN])], set())
    assert r.findings == [] and not r.failed
    assert r.metrics.per_rule["ADR-2/orphan"].bound == 0 and r.metrics.per_adr["ADR-2"] is None and r.metrics.overall is None


def test_baseline_roundtrip_and_ratchet(layered, tmp_path):
    ds = [dec("ADR-1", "accepted", [ONLY])]
    first = run_check(layered, ds, set())
    p = str(tmp_path / "baseline.json")
    save_baseline(p, first.current)
    assert load_baseline(p) == {("ADR-1", "gw", "src/other/x.py")}
    second = run_check(layered, ds, load_baseline(p) | {("ADR-1", "gw", "gone.py")})
    assert sorted(f.severity for f in second.findings) == ["baselined", "fixed"]
    assert not second.failed and second.metrics.fixed == 1 and second.metrics.new == 0


def test_bind(layered):
    b = bind(layered, [dec("ADR-1", "accepted", [ONLY, Rule("c", "ADR-1", "cypher", "MATCH (n) RETURN n", "error", "")])])
    assert b == {"ADR-1/gw": ["src/contracts/c.py", "src/other/x.py"], "ADR-1/c": []}


def test_only_compliance_never_negative(layered):
    # 1-node `to`, 2 reachers, 1 violator: compliance must be 0.5, not negative
    r = run_check(layered, [dec("ADR-1", "accepted", [ONLY])], set())
    assert 0 <= r.metrics.overall <= 1 and r.metrics.overall == pytest.approx(0.5)


def test_missing_baseline_is_empty(tmp_path):
    assert load_baseline(str(tmp_path / "none.json")) == set()


def test_bind_scopes(layered):
    d = dec("ADR-7", "accepted", []); d.scope = [{"path": "src/db/**"}, {"path": "src/log.py", "kind": "unit"}]
    from adrgraph.check import bind_scopes
    assert bind_scopes(layered, [d]) == {"ADR-7": ["src/db/q.py", "src/db/q.py::q.run", "src/log.py"]}
