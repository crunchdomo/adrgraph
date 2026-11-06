"""Load ADR markdown files (YAML frontmatter + prose) into Decision and Rule records."""
import glob
import os
from dataclasses import dataclass, field

import frontmatter

STATUSES = {"proposed", "accepted", "superseded", "deprecated"}
SHAPES = ("only", "never", "must", "cypher")
SEVERITIES = {"error", "warn"}


class AdrError(Exception):
    pass


@dataclass
class Rule:
    id: str
    decision: str
    shape: str
    spec: dict | str
    severity: str
    description: str


@dataclass
class Decision:
    id: str
    title: str
    status: str
    owner: str
    date: str
    review_date: str | None
    supersedes: list[str]
    path: str
    rules: list[Rule] = field(default_factory=list)


def _rule(raw: dict, decision_id: str, path: str) -> Rule:
    if not isinstance(raw, dict) or "id" not in raw:
        raise AdrError(f"{path}: every rule needs an id")
    shapes = [s for s in SHAPES if s in raw]
    if len(shapes) != 1:
        raise AdrError(f"{path}: rule {raw['id']} must have exactly one of {', '.join(SHAPES)}")
    severity = raw.get("severity", "error")
    if severity not in SEVERITIES:
        raise AdrError(f"{path}: rule {raw['id']} severity must be one of {sorted(SEVERITIES)}")
    return Rule(str(raw["id"]), decision_id, shapes[0], raw[shapes[0]], severity, str(raw.get("description", "")))


def _decision(path: str) -> Decision | None:
    meta = frontmatter.load(path).metadata
    if "id" not in meta:
        return None
    did = str(meta["id"])
    for key in ("title", "status"):
        if key not in meta:
            raise AdrError(f"{path}: {did} is missing {key}")
    if meta["status"] not in STATUSES:
        raise AdrError(f"{path}: {did} status must be one of {sorted(STATUSES)}")
    rules = [_rule(r, did, path) for r in meta.get("rules") or []]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise AdrError(f"{path}: {did} has duplicate rule ids")
    supersedes = meta.get("supersedes") or []
    return Decision(
        id=did,
        title=str(meta["title"]),
        status=meta["status"],
        owner=str(meta.get("owner", "")),
        date=str(meta.get("date", "")),
        review_date=str(meta["review_date"]) if meta.get("review_date") else None,
        supersedes=[str(s) for s in supersedes],
        path=path,
        rules=rules,
    )


def load_adrs(dirs: list[str]) -> list[Decision]:
    decisions: dict[str, Decision] = {}
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.md"))):
            dec = _decision(path)
            if dec is None:
                continue
            if dec.id in decisions:
                raise AdrError(f"{path}: duplicate decision id {dec.id} (also in {decisions[dec.id].path})")
            decisions[dec.id] = dec
    return sorted(decisions.values(), key=lambda x: x.id)
