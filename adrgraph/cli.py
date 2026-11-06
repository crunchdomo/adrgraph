"""adrgraph command line: build, check, audit, query."""
import argparse
import datetime
import json
import os
import sys
from dataclasses import asdict

from srcgraph.graph import Graph
from srcgraph.model import Edge
from srcgraph.scan import DEFAULT_EXCLUDES, scan
from srcgraph.selectors import SelectorError, compile_selector

from adrgraph import __version__
from adrgraph.adr import AdrError, Decision, load_adrs
from adrgraph.audit import run_audit
from adrgraph.baseline import load_baseline, save_baseline
from adrgraph.check import bind, bind_scopes, run_check
from adrgraph.render.html import render_html
from adrgraph.render.json import trail_dict
from adrgraph.render.text import render_text
from adrgraph.rules import RuleError, compile_rule, portability
from adrgraph.schema import load_adrs as load_adr_graph, open_graph
from adrgraph.trail import build_trail
from srcgraph.source import Source

DB = ".adrgraph/graph.lbug"
BASELINE = ".adrgraph/baseline.json"


def build(adr_dirs: list[str], src_roots: list[str], excludes: tuple[str, ...], db_path: str
          ) -> tuple[Graph, list[Decision], list[str]]:
    decisions = load_adrs(adr_dirs)
    for d in decisions:
        for r in d.rules:
            compile_rule(r)  # fail fast with decision/rule in the message, before any scanning
        for sel in d.scope:
            try:
                compile_selector(sel, "n", "s")
            except SelectorError as exc:
                raise AdrError(f"{d.path}: {d.id} scope: {exc}") from exc
    result = scan(src_roots, excludes)
    graph = open_graph(db_path)
    graph.load_code(result)
    load_adr_graph(graph, decisions)
    binds = [(key, node) for key, nodes in bind(graph, decisions).items() for node in nodes]
    binds += [(did, node) for did, nodes in bind_scopes(graph, decisions).items() for node in nodes]
    graph.load_edges([Edge("BINDS", src, dst) for src, dst in binds])
    return graph, decisions, result.warnings


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="adrgraph", description="Enforce ADRs against a knowledge graph of your code.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--adr", action="append", help="ADR directory (repeatable; default docs/adr)")
        sp.add_argument("--src", action="append", help="source root (repeatable; default .)")
        sp.add_argument("--exclude", action="append", default=[], help="extra exclude name or glob (repeatable)")
        sp.add_argument("--db", default=DB, help=f"graph database file (default {DB})")

    common(sub.add_parser("build", help="build the graph database"))
    c = sub.add_parser("check", help="evaluate ADR rules against the code")
    common(c)
    c.add_argument("--format", choices=["text", "json"], default="text")
    c.add_argument("--baseline", default=BASELINE)
    c.add_argument("--write-baseline", action="store_true", help="record current violations as the baseline")
    c.add_argument("--trails", action="store_true", help="with --format json: include the provenance trail per finding")
    rp = sub.add_parser("report", help="write a self-contained HTML report")
    common(rp)
    rp.add_argument("-o", "--output", default=".adrgraph/report.html")
    rp.add_argument("--baseline", default=BASELINE)
    a = sub.add_parser("audit", help="check the ADRs against each other")
    common(a)
    a.add_argument("--format", choices=["text", "json"], default="text")
    a.add_argument("--strict", action="store_true", help="treat warnings as errors")
    e = sub.add_parser("explain", help="show the provenance trail behind a finding")
    common(e)
    e.add_argument("target", help="path:line, or ADR-ID/rule-id")
    e.add_argument("decision", nargs="?", help="restrict path:line to one decision id")
    e.add_argument("--format", choices=["text", "json"], default="text")
    e.add_argument("--baseline", default=BASELINE)
    q = sub.add_parser("query", help="run Cypher against the last built graph")
    q.add_argument("--db", default=DB)
    q.add_argument("--format", choices=["text", "json"], default="text")
    q.add_argument("cypher")
    return p


def _select_findings(findings, target: str, decision: str | None):
    """path:line [decision] or ADR-ID/rule-id."""
    if "/" in target and ":" not in target.rsplit("/", 1)[-1] and not target.endswith(".py"):
        did, _, rid = target.partition("/")
        if not target.startswith("ADR") and ":" in target:
            pass
        matched = [f for f in findings if f.decision == did and f.rule == rid]
        if matched:
            return matched
    path, _, line = target.rpartition(":")
    if not line.isdigit():
        return []
    matched = [f for f in findings if f.path == path and f.line == int(line)]
    return [f for f in matched if decision is None or f.decision == decision]


def _colour(text: str, out) -> str:
    """Red for the violates line and the highlighted source line, only on a TTY."""
    if not getattr(out, "isatty", lambda: False)():
        return text
    lines = []
    for line in text.splitlines():
        if line.startswith("violates  ") or "      ← " in line:
            line = f"\x1b[31m{line}\x1b[0m"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _print_check(result, out) -> None:
    for f in result.findings:
        print(f"{f.severity:<9} {f.path}:{f.line}  {f.decision}/{f.rule}  {f.message}", file=out)
    if result.findings:
        print(file=out)
    m = result.metrics
    print(f"overall compliance: {_pct(m.overall)}", file=out)
    for adr, value in m.per_adr.items():
        rules = [k for k in m.per_rule if k.startswith(adr + "/")]
        violations = sum(m.per_rule[k].violations for k in rules)
        print(f"{adr}: {_pct(value)} ({len(rules)} rules, {violations} violation{'s' if violations != 1 else ''})", file=out)
    print(f"baseline: {m.fixed} fixed, {m.new} new", file=out)


def _portability_summary(decisions) -> str:
    """One line: `N rules: a semantic, b normalised, c grammar (lang, ...)`; empty when there are no rules."""
    kinds = [portability(r) for d in decisions for r in d.rules]
    if not kinds:
        return ""
    grammar = sorted({k[len("grammar ("):-1] for k in kinds if k.startswith("grammar")})
    g = f"{sum(k.startswith('grammar') for k in kinds)} grammar" + (f" ({', '.join(grammar)})" if grammar else "")
    return (f"{len(kinds)} rules: {kinds.count('semantic')} semantic, {kinds.count('normalised')} normalised, {g}")


def _check_json(result, decisions, trails=None) -> dict:
    m = result.metrics
    port = {f"{d.id}/{r.id}": portability(r) for d in decisions for r in d.rules}
    findings = [asdict(f) for f in result.findings]
    if trails is not None:
        for f, t in zip(findings, trails):
            f["trail"] = trail_dict(t)
    return {"findings": findings,
            "metrics": {"overall": m.overall, "per_adr": m.per_adr,
                        "per_rule": {k: {**asdict(v), "portability": port.get(k)} for k, v in m.per_rule.items()},
                        "fixed": m.fixed, "new": m.new},
            "failed": result.failed}


def _run(args, out, err) -> int:
    if args.command == "query":
        graph = Graph.open(args.db)
        try:
            rows = graph.query(args.cypher)
        finally:
            graph.close()
        if args.format == "json":
            print(json.dumps(rows, indent=2, default=str), file=out)
        elif rows:
            cols = list(rows[0])
            print("\t".join(cols), file=out)
            for r in rows:
                print("\t".join(str(r[c]) for c in cols), file=out)
        return 0

    excludes = DEFAULT_EXCLUDES + tuple(args.exclude)
    graph, decisions, warnings = build(args.adr or ["docs/adr"], args.src or ["."], excludes, args.db)
    for w in warnings:
        print(f"warning: {w}", file=err)
    try:
        if args.command == "build":
            print(f"built {args.db}: {graph.count('Unit')} units, {graph.count('Symbol')} symbols, "
                  f"{graph.count('Ast')} syntax nodes, {graph.count('Decision')} decisions, {graph.count('Rule')} rules", file=out)
            return 0
        if args.command == "explain":
            result = run_check(graph, decisions, load_baseline(args.baseline))
            matched = _select_findings(result.findings, args.target, args.decision)
            if not matched:
                print(f"no finding at {args.target}", file=err)
                return 1
            source = Source(".")
            trails = [build_trail(graph, decisions, f, result.findings, args.baseline, source.lines) for f in matched]
            if args.format == "json":
                print(json.dumps([trail_dict(t) for t in trails], indent=2), file=out)
            else:
                for t in trails:
                    print(_colour(render_text(t), out), file=out)
            return 0
        if args.command == "check":
            result = run_check(graph, decisions, load_baseline(args.baseline))
            if args.write_baseline:
                save_baseline(args.baseline, result.current)
                print(f"wrote {args.baseline} ({len(result.current)} violations)", file=out)
                return 0
            if args.format == "json":
                trails = None
                if args.trails:
                    source = Source(".")
                    trails = [build_trail(graph, decisions, f, result.findings, args.baseline, source.lines) for f in result.findings]
                print(json.dumps(_check_json(result, decisions, trails), indent=2), file=out)
            else:
                _print_check(result, out)
            return 1 if result.failed else 0
        if args.command == "report":
            result = run_check(graph, decisions, load_baseline(args.baseline))
            source = Source(".")
            trails = [build_trail(graph, decisions, f, result.findings, args.baseline, source.lines) for f in result.findings]
            binds = {}
            for key, nodes in bind(graph, decisions).items():
                binds.setdefault(key.split("/", 1)[0], []).extend(nodes)
            for did, nodes in bind_scopes(graph, decisions).items():
                binds.setdefault(did, []).extend(nodes)
            binds = {k: sorted(set(v)) for k, v in binds.items()}
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(render_html(trails, decisions, result.metrics, binds))
            print(f"wrote {args.output} ({len(trails)} findings)", file=out)
            return 0
        findings = run_audit(graph, decisions, datetime.date.today(), strict=args.strict)
        if args.format == "json":
            print(json.dumps([asdict(f) for f in findings], indent=2), file=out)
        else:
            for f in findings:
                print(f"{f.severity:<9} {f.check:<13} {f.decision}/{f.rule}  {f.message}", file=out)
            summary = _portability_summary(decisions)
            if summary:
                print(summary, file=out)
        return 1 if any(f.severity == "error" for f in findings) else 0
    finally:
        graph.close()


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "check" and args.trails and args.format != "json":
        parser.error("--trails requires --format json")
    try:
        return _run(args, sys.stdout, sys.stderr)
    except (AdrError, RuleError, SelectorError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
