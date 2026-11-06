import pytest
from adrgraph.adr import load_adrs, AdrError

FIX = "tests/fixtures/adr"


def test_loads_decisions_and_skips_non_adr_files():
    ds = load_adrs([FIX])
    assert [d.id for d in ds] == ["ADR-0001", "ADR-0002"]
    d = ds[0]
    assert d.status == "accepted" and d.date == "2026-11-05" and d.review_date == "2027-05-01"
    assert [r.id for r in d.rules] == ["gateway-only-via-contracts", "no-handler-calls-db", "custom"]
    assert d.rules[0].shape == "only" and d.rules[0].severity == "error"
    assert d.rules[1].severity == "warn"
    assert d.rules[2].shape == "cypher" and d.rules[2].severity == "warn"
    assert d.rules[2].decision == "ADR-0001"
    assert ds[1].review_date is None and ds[1].supersedes == []


def test_duplicate_decision_id_is_error(tmp_path):
    for n in ("a.md", "b.md"):
        (tmp_path / n).write_text("---\nid: ADR-9\ntitle: t\nstatus: accepted\n---\n")
    with pytest.raises(AdrError, match="ADR-9"):
        load_adrs([str(tmp_path)])


def test_rule_with_two_shapes_is_error(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nid: ADR-9\ntitle: t\nstatus: accepted\nrules:\n  - id: r\n    only: {}\n    never: {}\n---\n")
    with pytest.raises(AdrError, match="a.md"):
        load_adrs([str(tmp_path)])


def test_bad_status_is_error(tmp_path):
    (tmp_path / "a.md").write_text("---\nid: ADR-9\ntitle: t\nstatus: maybe\n---\n")
    with pytest.raises(AdrError, match="status"):
        load_adrs([str(tmp_path)])


def test_rule_lang(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nid: ADR-9\ntitle: t\nstatus: accepted\nrules:\n  - id: r\n    lang: python\n    cypher: MATCH (a:Ast) RETURN a.id\n  - id: s\n    cypher: MATCH (a:Ast) RETURN a.id\n---\n")
    rules = load_adrs([str(tmp_path)])[0].rules
    assert rules[0].lang == "python" and rules[1].lang is None


def test_relations_and_scope(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nid: ADR-3\ntitle: t\nstatus: accepted\ndepends_on: [ADR-1]\nconflicts_with: [ADR-2]\nscope:\n  - { path: \"src/**\" }\n---\n")
    d = load_adrs([str(tmp_path)])[0]
    assert d.depends_on == ["ADR-1"] and d.conflicts_with == ["ADR-2"] and d.scope == [{"path": "src/**"}]


def test_scope_must_be_a_list_of_maps(tmp_path):
    (tmp_path / "a.md").write_text("---\nid: ADR-3\ntitle: t\nstatus: accepted\nscope: src/**\n---\n")
    with pytest.raises(AdrError, match="scope"):
        load_adrs([str(tmp_path)])
