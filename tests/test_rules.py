import pytest
from adrgraph.adr import Rule
from adrgraph.rules import compile_rule, evaluate, RuleError, bound_selector


def rule(shape, spec, rid="r"):
    return Rule(rid, "ADR-1", shape, spec, "error", "")


def test_only_direct(layered):
    v = evaluate(layered, rule("only", {"from": {"path": "src/contracts/**"}, "to": {"path": "src/gateway/client.py"}, "via": "IMPORTS"}))
    assert [x.node_id for x in v] == ["src/other/x.py"]
    assert v[0].path == "src/other/x.py" and v[0].line == 1 and "src/gateway/client.py" in v[0].message


def test_only_transitive_exempts_paths_through_from(layered):
    v = evaluate(layered, rule("only", {"from": {"path": "src/contracts/**"}, "to": {"path": "src/gateway/client.py"}, "via": "IMPORTS", "transitive": True}))
    assert [x.node_id for x in v] == ["src/other/x.py"]   # h.py reaches gateway only through contracts


def test_never_transitive_with_cycle_terminates_and_dedupes(layered):
    v = evaluate(layered, rule("never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/db/**"}, "via": "CALLS", "transitive": True}))
    assert [x.node_id for x in v] == ["src/handlers/h.py::h.view"]


def test_never_direct_passes(layered):
    assert evaluate(layered, rule("never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/db/**"}, "via": "CALLS"})) == []


def test_must_out_and_in(layered):
    ok = rule("must", {"every": {"path": "src/handlers/**", "kind": "function"}, "has": {"path": "src/log.py"}, "via": "CALLS"})
    assert evaluate(layered, ok) == []
    bad = rule("must", {"every": {"kind": "function"}, "has": {"path": "src/log.py"}, "via": "CALLS"})
    assert sorted(x.node_id for x in evaluate(layered, bad)) == ["src/contracts/c.py::c.call", "src/db/q.py::q.run", "src/log.py::log.info"]
    inbound = rule("must", {"every": {"path": "src/db/**", "kind": "function"}, "has": {"path": "src/contracts/**"}, "via": "CALLS", "direction": "in"})
    assert evaluate(layered, inbound) == []


def test_multi_via(layered):
    v = evaluate(layered, rule("never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/contracts/**"}, "via": ["IMPORTS", "CALLS"]}))
    assert sorted(x.node_id for x in v) == ["src/handlers/h.py", "src/handlers/h.py::h.view"]


def test_raw_cypher(layered):
    v = evaluate(layered, rule("cypher", "MATCH (s:Symbol) WHERE s.name = 'run' RETURN s.id AS node_id, s.path AS path, s.line AS line, 'no' AS message"))
    assert [x.node_id for x in v] == ["src/db/q.py::q.run"]
    with pytest.raises(RuleError, match="node_id"):
        evaluate(layered, rule("cypher", "MATCH (s:Symbol) RETURN s.id AS id"))


@pytest.mark.parametrize("shape,spec,msg", [
    ("never", {"from": {}, "to": {}, "via": "FLIES"}, "FLIES"),
    ("never", {"from": {"pth": "x"}, "to": {}, "via": "CALLS"}, "pth"),
    ("must", {"every": {}, "has": {}, "via": "CALLS", "transitive": True}, "transitive"),
    ("only", {"from": {}, "via": "CALLS"}, "to"),
])
def test_rule_errors(shape, spec, msg):
    with pytest.raises(RuleError, match=msg):
        compile_rule(rule(shape, spec))


def test_bound_selector():
    assert bound_selector(rule("only", {"from": {"a": 1}, "to": {"b": 2}, "via": "X"})) == {"b": 2}
    assert bound_selector(rule("cypher", "MATCH (n) RETURN n")) is None
