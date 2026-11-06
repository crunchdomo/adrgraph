"""Mine the graph for invariants that already hold and offer them as rules (`adrgraph suggest`)."""
import datetime
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

from srcgraph.graph import Graph

from adrgraph.adr import Decision, Rule
from adrgraph.rules import evaluate

_TARGET = {"only": "to", "must": "has"}


@dataclass(frozen=True)
class Candidate:
    shape: str
    spec: dict
    strength: int     # backing edges (only) or conforming classes (must)
    title: str
    rule_id: str


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _only(graph: Graph) -> list[Candidate]:
    units = [r["p"] for r in graph.query("MATCH (u:Unit) WHERE u.kind <> 'external' RETURN u.path AS p")]
    rows = graph.query("MATCH (a:Unit)-[:IMPORTS]->(b:Unit) WHERE b.kind = 'external' RETURN a.path AS path, b.name AS name")
    by_pkg: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        pkg = r["name"].split(".")[0]
        if pkg not in sys.stdlib_module_names:
            by_pkg[pkg].append(r["path"])
    out = []
    for pkg, paths in by_pkg.items():
        files = sorted(set(paths))
        if len(files) == 1:
            sel = files[0]
        else:
            d = os.path.commonpath(files)
            # ponytail: a directory holding most of the code is not a boundary; tune if real repos disagree
            if not d or sum(p.startswith(d + "/") for p in units) * 2 > len(units):
                continue
            sel = f"{d}/**"
        spec = {"from": {"path": sel}, "to": {"kind": "unit", "name": f"{pkg}*"}, "via": "IMPORTS"}
        out.append(Candidate("only", spec, len(paths), f"Only {sel} may import {pkg}",
                             _slug(f"{pkg}-only-via-{sel.rstrip('/*')}")))
    return out


def _must(graph: Graph) -> list[Candidate]:
    rows = graph.query("MATCH (c:Symbol) WHERE c.kind = 'class' OPTIONAL MATCH (c)-[:INHERITS]->(b:Symbol) "
                       "RETURN c.path AS path, c.name AS name, b.name AS base")
    by_dir: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        if not r["name"].startswith("_"):
            by_dir[os.path.dirname(r["path"])][r["name"]].add(r["base"])
    out = []
    for d, classes in by_dir.items():
        bases = Counter(b for bs in classes.values() for b in bs if b)
        if not bases:
            continue
        base, n = sorted(bases.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        others = sorted(c for c, bs in classes.items() if base not in bs)
        if n <= len(others):
            continue   # a minority of conformers is not a convention
        short = base.rsplit(".", 1)[-1]
        spec = {"every": {"path": f"{d}/**", "kind": "class"}, "except": [{"name": "_*"}] + [{"name": o} for o in others],
                "has": {"name": f"*{short}"}, "via": "INHERITS"}
        out.append(Candidate("must", spec, n, f"Every class in {d}/** inherits {short}", _slug(f"{d}-classes-inherit-{short}")))
    return out


def _tf_must(graph: Graph) -> list[Candidate]:
    """Every Terraform resource of type A is referenced by some resource of type B."""
    rows = graph.query("MATCH (a:Symbol) WHERE a.kind = 'resource' OPTIONAL MATCH (b:Symbol)-[:REFERENCES]->(a) "
                       "WHERE b.kind = 'resource' RETURN a.name AS name, b.name AS by")
    rtype = lambda name: name.rsplit(".", 1)[0]
    by_type: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        by_type[rtype(r["name"])][r["name"]].add(rtype(r["by"]) if r["by"] else None)
    out = []
    for a, resources in by_type.items():
        for b in sorted(set.intersection(*resources.values()) - {None, a}):
            spec = {"every": {"kind": "resource", "name": f"{a}.*"}, "has": {"kind": "resource", "name": f"{b}.*"},
                    "via": "REFERENCES", "direction": "in"}
            out.append(Candidate("must", spec, len(resources), f"Every {a} is referenced by an {b}", _slug(f"{a}-has-{b}")))
    return out


def suggest(graph: Graph, decisions: list[Decision] = (), min_strength: int = 2, include_covered: bool = False) -> list[Candidate]:
    """Candidates that hold on the graph, strongest first. Covered = an active rule with the same shape and target."""
    covered = {(r.shape, str(r.spec.get(_TARGET.get(r.shape)))) for d in decisions if d.status in ("accepted", "proposed")
               for r in d.rules if r.shape in _TARGET}
    out = [c for c in _only(graph) + _must(graph) + _tf_must(graph)
           if c.strength >= min_strength and (include_covered or (c.shape, str(c.spec[_TARGET[c.shape]])) not in covered)
           and not evaluate(graph, Rule(c.rule_id, "ADR-0", c.shape, c.spec, "error", ""))]
    return sorted(out, key=lambda c: (-c.strength, c.rule_id))


def rule_yaml(c: Candidate, indent: str = "") -> str:
    """One rules-list entry. JSON is valid YAML, so the spec needs no YAML library."""
    return (f"{indent}- id: {c.rule_id}\n{indent}  description: {c.title}\n"
            f"{indent}  {c.shape}: {json.dumps(c.spec)}\n")


def write_draft(c: Candidate, adr_dir: str, number: int) -> str:
    """A proposed ADR holding one candidate rule; returns the path written."""
    path = os.path.join(adr_dir, f"{number:04d}-{c.rule_id}.md")
    body = (f"---\nid: ADR-{number:04d}\ntitle: {c.title}\nstatus: proposed\ndate: {datetime.date.today()}\nrules:\n"
            + rule_yaml(c, "  ") + f"---\n\n# {c.title}\n\n## Context\n\nTODO: why the code is shaped this way.\n\n"
            "## Decision\n\nTODO: the decision in one paragraph.\n\n## Consequences\n\nTODO: what this makes easier and harder.\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path
