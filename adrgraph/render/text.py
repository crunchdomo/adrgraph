"""Trail -> fixed-width text for the terminal. No colour codes here; the CLI adds them on a TTY."""
from adrgraph.trail import Trail


def _spec_line(detail: dict) -> str:
    spec, shape = detail["spec"], detail["shape"]
    if shape == "cypher":
        return "cypher"
    via = spec["via"] if isinstance(spec["via"], str) else "|".join(spec["via"])
    if shape == "must":
        return f"must every {spec['every']} has {spec['has']} via {via}"
    verb = "may reach" if shape == "only" else "never reaches"
    return f"{shape} {spec['from']} {verb} {spec['to']} via {via}" + (" transitive" if spec.get("transitive") else "")


def render_text(trail: Trail) -> str:
    out = []
    by_kind = {s.kind: s for s in trail.steps}
    d, r = by_kind["decision"], by_kind["rule"]
    out.append(f"{d.detail['id']}  {d.detail['title']}            {d.detail['path']}".rstrip())
    if d.detail.get("decision_text"):
        first = d.detail["decision_text"].splitlines()[0]
        out.append(f'  Decision: "{first}"')
    out.append(f"  rule {r.detail['id']}   {_spec_line(r.detail)}   [{r.detail['severity']}, {r.detail['portability']}]")
    if r.detail["shape"] != "cypher" and r.detail["spec"].get("except"):
        out.append(f"       except {r.detail['spec']['except']}")
    if r.detail.get("fixed"):
        out.append("  fixed: no longer violated")
    out.append("")
    node = by_kind.get("node")
    if node is not None:
        out.append(f"violates  {node.detail['path']}:{node.detail['line']}   ({node.detail['why']})")
        edge, path = by_kind.get("edge"), by_kind.get("path")
        note = ""
        if edge is not None and not edge.detail["missing"]:
            note = f"      ← {edge.detail['label']} → {edge.detail['target_id']}" + (
                " (external)" if edge.detail.get("target_kind") == "external" else "")
        ex = node.excerpt
        if ex is None:
            out.append("   (source unavailable)")
        else:
            width = len(str(ex.start + len(ex.lines)))
            for i, line in enumerate(ex.lines):
                n = ex.start + i
                out.append(f"  {n:>{width}} │ {line}" + (note if n == ex.highlight else ""))
        out.append("")
        if path is not None:
            nodes = path.detail["nodes"]
            out.append(f"path  {nodes[0]['id']}")
            for n in nodes[1:]:
                out.append(f"      -> {n['id']}   ({n['label']} {n['path']})".rstrip())
            out.append("")
        if edge is not None and edge.detail["missing"]:
            out.append(f"missing  {edge.detail['label']} → {r.detail['spec'].get('has')}")
            if edge.detail["existing"]:
                for e in edge.detail["existing"]:
                    out.append(f"existing  {edge.detail['label']} → {e['target_id']} (line {e['line']})")
            else:
                out.append("existing  none")
            out.append("")
    syn = by_kind.get("syntax")
    if syn is not None:
        norm = f"  norm={syn.detail['norm']}" if syn.detail.get("norm") else ""
        out.append(f"derived from  Ast {syn.detail['kind']}  {syn.detail['id']}{norm}")
        if syn.detail.get("edge_syntax"):
            es = syn.detail["edge_syntax"]
            out.append(f"edge syntax   Ast {es['kind']}  {es['id']}  norm={es['norm']}")
    ctx = by_kind["context"].detail
    others = [g for g in ctx["governed_by"] if g["decision"] != trail.finding.decision]
    if others:
        out.append("also governed by  " + ", ".join(f"{g['decision']} ({g['result']})" for g in others))
    out.append(f"baselined  {'yes' if ctx['baselined'] else 'no'}" + (f"  ({ctx['baseline_path']})" if ctx["baselined"] and ctx["baseline_path"] else ""))
    return "\n".join(out) + "\n"
