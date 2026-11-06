"""Trails + decisions + metrics -> one self-contained HTML page. Inline CSS, no scripts."""
import html as h

from adrgraph.adr import Decision
from adrgraph.check import Metrics, pct
from adrgraph.rules import portability
from adrgraph.trail import Trail

_CSS = """
body{font:14px/1.5 system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#222}
h1{font-size:20px}h2{font-size:16px;margin-top:32px;border-bottom:1px solid #ddd;padding-bottom:4px}
table{border-collapse:collapse}td,th{padding:3px 10px;border-bottom:1px solid #eee;text-align:left}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;background:#eee;margin-left:6px}
.error{background:#fde2e2}.warn{background:#fff3cd}.baselined{background:#e8e8e8}.fixed{background:#dff5e1}
section.finding{border:1px solid #ddd;border-radius:6px;padding:12px 16px;margin:12px 0}
section.finding h3{margin:0 0 8px;font-size:14px}
ol.trail{margin:0;padding-left:20px}ol.trail li{margin:6px 0}ol.trail h4{margin:0;font-size:13px}
pre{background:#f6f6f6;padding:8px;border-radius:4px;overflow:auto;font-size:12px}mark{background:#fde2e2}
section.adr{margin:12px 0}section.adr ul{columns:2;font-size:12px}code{font-size:12px}
"""


def _step_html(step) -> str:
    d = step.detail
    body = ""
    if step.kind == "decision":
        body = f"<p>{h.escape(d['title'])} <code>{h.escape(d['path'])}</code></p>"
        if d.get("decision_text"):
            body += f"<p><em>{h.escape(d['decision_text'])}</em></p>"
    elif step.kind == "rule":
        body = f"<p><code>{h.escape(d['shape'])}</code> {h.escape(str(d['spec']))} <span class='badge'>{h.escape(d['severity'])}</span><span class='badge'>{h.escape(d['portability'])}</span></p>"
    elif step.kind == "node":
        body = f"<p><code>{h.escape(d['path'])}:{d['line']}</code> is {h.escape(d['why'])}</p>"
        if step.excerpt:
            ex = step.excerpt
            rows = []
            for i, line in enumerate(ex.lines):
                n = ex.start + i
                text = f"{n:>4}  {h.escape(line)}"
                rows.append(f"<mark>{text}</mark>" if n == ex.highlight else text)
            body += "<pre>" + "\n".join(rows) + "</pre>"
        else:
            body += "<p>(source unavailable)</p>"
    elif step.kind == "edge":
        if d["missing"]:
            body = f"<p>no <code>{h.escape(d['label'])}</code> edge to a matching node"
            body += (" (existing: " + ", ".join(h.escape(e["target_id"]) for e in d["existing"]) + ")" if d["existing"] else "") + "</p>"
        else:
            body = f"<p><code>{h.escape(d['label'])}</code> at line {d['line']} → <code>{h.escape(str(d['target_id']))}</code> ({h.escape(str(d['target_kind']))})</p>"
    elif step.kind == "path":
        body = "<p>" + " → ".join(f"<code>{h.escape(n['id'])}</code>" for n in d["nodes"]) + "</p>"
    elif step.kind == "syntax":
        body = f"<p><code>{h.escape(d['kind'])}</code> {h.escape(d['id'])}" + (f", normalised <code>{h.escape(d['norm'])}</code>" if d.get("norm") else "") + "</p>"
    elif step.kind == "context":
        gov = ", ".join(f"{h.escape(g['decision'])} ({g['result']})" for g in d["governed_by"])
        body = f"<p>governed by {gov}" + ("; baselined" if d["baselined"] else "") + "</p>"
    return f"<li><h4>{h.escape(step.kind)}</h4>{body}</li>"


def render_html(trails: list[Trail], decisions: list[Decision], metrics: Metrics, binds: dict[str, list[str]]) -> str:
    counts: dict[str, dict[str, int]] = {d.id: {} for d in decisions}
    for t in trails:
        c = counts.setdefault(t.finding.decision, {})
        c[t.finding.severity] = c.get(t.finding.severity, 0) + 1
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>adrgraph report</title><style>{_CSS}</style></head><body>",
           "<h1>adrgraph report</h1>", "<h2>Summary</h2>",
           "<table><tr><th>ADR</th><th>title</th><th>status</th><th>compliance</th><th>findings</th></tr>"]
    for d in decisions:
        c = counts.get(d.id, {})
        summary = ", ".join(f"{n} {sev}" for sev, n in sorted(c.items())) or "none"
        out.append(f"<tr><td>{h.escape(d.id)}</td><td>{h.escape(d.title)}</td><td>{h.escape(d.status)}</td>"
                   f"<td>{pct(metrics.per_adr.get(d.id))}</td><td>{h.escape(summary)}</td></tr>")
    out.append("</table>")
    out.append(f"<h2>Findings ({len(trails)})</h2>")
    if not trails:
        out.append("<p>no findings</p>")
    for t in trails:
        f = t.finding
        out.append(f"<section class=\"finding\"><h3>{h.escape(f.decision)} / {h.escape(f.rule)}"
                   f"<span class='badge {h.escape(f.severity)}'>{h.escape(f.severity)}</span> "
                   f"<code>{h.escape(f.path)}:{f.line}</code></h3><ol class='trail'>")
        out += [_step_html(s) for s in t.steps]
        out.append("</ol></section>")
    out.append("<h2>ADRs</h2>")
    for d in decisions:
        out.append(f"<section class=\"adr\"><h3>{h.escape(d.id)}  {h.escape(d.title)}<span class='badge'>{h.escape(d.status)}</span></h3>")
        if d.rules:
            out.append("<ul>" + "".join(f"<li><code>{h.escape(r.id)}</code> {h.escape(r.shape)} <span class='badge'>{h.escape(portability(r))}</span></li>" for r in d.rules) + "</ul>")
        nodes = binds.get(d.id, [])
        if nodes:
            out.append(f"<p>binds {len(nodes)} node{'s' if len(nodes) != 1 else ''}</p><ul>" + "".join(f"<li><code>{h.escape(n)}</code></li>" for n in nodes[:200]) + "</ul>")
        out.append("</section>")
    out.append("</body></html>")
    return "\n".join(out)
