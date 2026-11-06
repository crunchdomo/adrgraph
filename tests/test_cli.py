import json
import pytest
from adrgraph.cli import main


@pytest.fixture
def cwd(monkeypatch):
    monkeypatch.chdir("tests/fixtures/pyrepo")


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_check_text_fails_with_findings(cwd, tmp_path, capsys):
    code, out, err = run(capsys, "check", "--db", str(tmp_path / "g.lbug"), "--baseline", str(tmp_path / "b.json"))
    assert code == 1
    assert "error     src/other/x.py:1  ADR-0001/gateway-only-via-contracts  reaches src/gateway/client.py" in out
    assert "warn      src/handlers/h.py:9  ADR-0001/no-handler-calls-db" in out
    assert "overall compliance:" in out and "baseline: 0 fixed" in out


def test_write_baseline_then_pass(cwd, tmp_path, capsys):
    b = str(tmp_path / "b.json")
    code, out, _ = run(capsys, "check", "--db", str(tmp_path / "g.lbug"), "--baseline", b, "--write-baseline")
    assert code == 0 and out.startswith("wrote ")
    code, out, _ = run(capsys, "check", "--db", str(tmp_path / "g.lbug"), "--baseline", b, "--format", "json")
    data = json.loads(out)
    assert code == 0 and data["failed"] is False and all(f["severity"] in ("baselined", "warn") for f in data["findings"])


def test_audit_and_query(cwd, tmp_path, capsys):
    db = str(tmp_path / "g.lbug")
    code, out, _ = run(capsys, "audit", "--db", db, "--format", "json")
    assert code == 0 and isinstance(json.loads(out), list)
    code, out, _ = run(capsys, "query", "--db", db, "MATCH (u:Unit {kind:'external'}) RETURN u.name AS n ORDER BY n")
    assert code == 0 and out.splitlines()[0] == "n" and "logging" in out


def test_bad_adr_exits_2(tmp_path, monkeypatch, capsys):
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "x.md").write_text("---\nid: ADR-1\ntitle: t\nstatus: accepted\nrules:\n  - id: r\n    never: {from: {}, to: {}, via: FLIES}\n---\n")
    monkeypatch.chdir(tmp_path)
    code, _, err = run(capsys, "check", "--db", str(tmp_path / "g.lbug"))
    assert code == 2 and "ADR-1/r" in err and "FLIES" in err
