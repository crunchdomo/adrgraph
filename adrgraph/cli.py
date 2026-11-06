"""adrgraph command line: build, check, audit, query."""
import argparse
import datetime
import json
import sys
from dataclasses import asdict

from adrgraph import __version__
from adrgraph.adr import AdrError, Decision, load_adrs
from adrgraph.audit import run_audit
from adrgraph.baseline import load_baseline, save_baseline
from adrgraph.check import bind, run_check
from adrgraph.graph import Graph
from adrgraph.rules import RuleError
from adrgraph.scan import DEFAULT_EXCLUDES, scan
from adrgraph.selectors import SelectorError

DB = ".adrgraph/graph.lbug"
BASELINE = ".adrgraph/baseline.json"


def build(adr_dirs: list[str], src_roots: list[str], excludes: tuple[str, ...], db_path: str
          ) -> tuple[Graph, list[Decision], list[str]]:
    decisions = load_adrs(adr_dirs)
    result = scan(src_roots, excludes)
    graph = Graph(db_path)
    graph.load(result.units, result.symbols, decisions, result.edges)
    binds = [(key, node) for key, nodes in bind(graph, decisions).items() for node in nodes]
    graph.load([], [], [], [], binds=binds)
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
    a = sub.add_parser("audit", help="check the ADRs against each other")
    common(a)
    a.add_argument("--format", choices=["text", "json"], default="text")
    a.add_argument("--strict", action="store_true", help="treat warnings as errors")
    q = sub.add_parser("query", help="run Cypher against the last built graph")
    q.add_argument("--db", default=DB)
    q.add_argument("--format", choices=["text", "json"], default="text")
    q.add_argument("cypher")
    return p


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


def _check_json(result) -> dict:
    m = result.metrics
    return {"findings": [asdict(f) for f in result.findings],
            "metrics": {"overall": m.overall, "per_adr": m.per_adr,
                        "per_rule": {k: asdict(v) for k, v in m.per_rule.items()}, "fixed": m.fixed, "new": m.new},
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
                  f"{graph.count('Decision')} decisions, {graph.count('Rule')} rules", file=out)
            return 0
        if args.command == "check":
            result = run_check(graph, decisions, load_baseline(args.baseline))
            if args.write_baseline:
                save_baseline(args.baseline, result.current)
                print(f"wrote {args.baseline} ({len(result.current)} violations)", file=out)
                return 0
            if args.format == "json":
                print(json.dumps(_check_json(result), indent=2), file=out)
            else:
                _print_check(result, out)
            return 1 if result.failed else 0
        findings = run_audit(graph, decisions, datetime.date.today(), strict=args.strict)
        if args.format == "json":
            print(json.dumps([asdict(f) for f in findings], indent=2), file=out)
        else:
            for f in findings:
                print(f"{f.severity:<9} {f.check:<13} {f.decision}/{f.rule}  {f.message}", file=out)
        return 1 if any(f.severity == "error" for f in findings) else 0
    finally:
        graph.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args, sys.stdout, sys.stderr)
    except (AdrError, RuleError, SelectorError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
