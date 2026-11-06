from srcgraph.model import Edge
from adrgraph.adr import Decision, Rule
from adrgraph.check import bind, run_check
from adrgraph.render.text import render_text
from adrgraph.schema import load_adrs
from adrgraph.trail import build_trail

ONLY = Rule("gw", "ADR-1", "only", {"from": {"path": "src/contracts/**"}, "to": {"path": "src/gateway/client.py"}, "via": "IMPORTS"}, "error", "")
NEVER_T = Rule("db", "ADR-1", "never", {"from": {"path": "src/handlers/**"}, "to": {"path": "src/db/**"}, "via": "CALLS", "transitive": True}, "warn", "")


def trail_for(layered, tmp_path, rule, read=None):
    (tmp_path / "src" / "other").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "handlers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "other" / "x.py").write_text("from src.gateway import client\n")
    (tmp_path / "src" / "handlers" / "h.py").write_text("".join(f"line {i}\n" for i in range(1, 11)))
    (tmp_path / "ADR-1.md").write_text("## Decision\n\nGateway via contracts.\n")
    d = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], str(tmp_path / "ADR-1.md"), [rule])
    load_adrs(layered, [d])
    layered.load_edges([Edge("BINDS", k, n) for k, ns in bind(layered, [d]).items() for n in ns])
    result = run_check(layered, [d], set())
    reader = read or (lambda p: (tmp_path / p).read_text().splitlines() if (tmp_path / p).exists() else None)
    return build_trail(layered, [d], result.findings[0], result.findings, None, reader)


def test_render_text_only_trail(layered, tmp_path):
    text = render_text(trail_for(layered, tmp_path, ONLY))
    lines = text.splitlines()
    assert lines[0].startswith("ADR-1  t") and lines[0].endswith("ADR-1.md")
    assert '  Decision: "Gateway via contracts."' in lines
    assert any(l.startswith("  rule gw   only") and "[error, semantic]" in l for l in lines)
    assert "violates  src/other/x.py:1   (outside the from set and not excepted)" in lines
    assert any(l.endswith("← IMPORTS → src/gateway/client.py") and "from src.gateway import client" in l for l in lines)
    assert any(l.startswith("derived from  Ast") for l in lines) or not any("derived" in l for l in lines)
    assert "\x1b[" not in text


def test_render_text_transitive_has_path_lines(layered, tmp_path):
    text = render_text(trail_for(layered, tmp_path, NEVER_T))
    assert "path  src/handlers/h.py::h.view" in text and "-> src/contracts/c.py::c.call" in text


def test_render_text_source_unavailable(layered, tmp_path):
    text = render_text(trail_for(layered, tmp_path, ONLY, read=lambda p: None))
    assert "(source unavailable)" in text


def test_render_html_structure(layered, tmp_path):
    from adrgraph.render.html import render_html
    from adrgraph.check import Metrics
    t = trail_for(layered, tmp_path, ONLY)
    d = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], "a.md", [ONLY])
    html = render_html([t], [d], Metrics(per_adr={"ADR-1": 0.5}), {"ADR-1": ["src/gateway/client.py"]})
    assert "<title>adrgraph report</title>" in html and "<script" not in html
    assert html.count('class="finding"') == 1 and html.count('class="adr"') == 1
    assert "<mark>" in html and "from src.gateway import client" in html


def test_report_with_no_findings():
    from adrgraph.render.html import render_html
    from adrgraph.check import Metrics
    d = Decision("ADR-1", "t", "accepted", "", "2026-01-01", None, [], "a.md", [])
    html = render_html([], [d], Metrics(), {})
    assert "no findings" in html and html.count('class="adr"') == 1
