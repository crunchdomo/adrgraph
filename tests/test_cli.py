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
    assert "warn      src/handlers/h.py:10  ADR-0001/no-handler-calls-db  reaches src/db/q.py::src.db.q.run via src/db/q.py::src.db.q.run" in out
    assert "overall compliance:" in out and "baseline: 0 fixed" in out


def test_write_baseline_then_pass(cwd, tmp_path, capsys):
    b = str(tmp_path / "b.json")
    code, out, _ = run(capsys, "check", "--db", str(tmp_path / "g.lbug"), "--baseline", b, "--write-baseline")
    assert code == 0 and out.startswith("wrote ")
    code, out, _ = run(capsys, "check", "--db", str(tmp_path / "g.lbug"), "--baseline", b, "--format", "json")
    data = json.loads(out)
    assert code == 0 and data["failed"] is False and all(f["severity"] in ("baselined", "warn") for f in data["findings"])
    assert all("path_nodes" in f for f in data["findings"])


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


@pytest.mark.parametrize("body,needle", [
    ("rules:\n  - id: r\n    never: {from: {}, via: CALLS}\n", "ADR-1/r"),            # missing `to`
    ("rules:\n  - id: r\n    never: {from: {pth: x}, to: {}, via: CALLS}\n", "ADR-1/r"),  # bad selector key
    ("review_date: soon\n", "review_date"),
    ("rules: [\n", "x.md"),                                                        # YAML syntax error
])
def test_malformed_adr_exits_2_naming_the_culprit(tmp_path, monkeypatch, capsys, body, needle):
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "x.md").write_text(f"---\nid: ADR-1\ntitle: t\nstatus: accepted\n{body}---\n")
    monkeypatch.chdir(tmp_path)
    for cmd in ("check", "audit"):
        code, _, err = run(capsys, cmd, "--db", str(tmp_path / "g.lbug"))
        assert code == 2 and needle in err and "Traceback" not in err
