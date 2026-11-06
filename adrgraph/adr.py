"""Load ADR markdown files (YAML frontmatter + prose) into Decision and Rule records."""
import datetime
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
    lang: str | None = None


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
    depends_on: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    scope: list[dict] = field(default_factory=list)


def _rule(raw: dict, decision_id: str, path: str) -> Rule:
    if not isinstance(raw, dict) or "id" not in raw:
        raise AdrError(f"{path}: every rule needs an id")
    shapes = [s for s in SHAPES if s in raw]
    if len(shapes) != 1:
        raise AdrError(f"{path}: rule {raw['id']} must have exactly one of {', '.join(SHAPES)}")
    severity = raw.get("severity", "error")
    if severity not in SEVERITIES:
        raise AdrError(f"{path}: rule {raw['id']} severity must be one of {sorted(SEVERITIES)}")
    return Rule(str(raw["id"]), decision_id, shapes[0], raw[shapes[0]], severity, str(raw.get("description", "")),
                lang=str(raw["lang"]) if raw.get("lang") else None)


def _date(meta: dict, key: str, path: str, did: str) -> str | None:
    value = meta.get(key)
    if value in (None, ""):
        return None
    try:
        datetime.date.fromisoformat(str(value))
    except ValueError:
        raise AdrError(f"{path}: {did} {key} must be an ISO date (YYYY-MM-DD), got {value!r}") from None
    return str(value)


def _decision(path: str) -> Decision | None:
    try:
        meta = frontmatter.load(path).metadata
    except Exception as exc:  # yaml.YAMLError and friends
        raise AdrError(f"{path}: cannot parse frontmatter: {exc}") from exc
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
    def id_list(key: str) -> list[str]:
        value = meta.get(key) or []
        if not isinstance(value, list):
            raise AdrError(f"{path}: {did} {key} must be a list of decision ids, got {value!r}")
        return [str(s) for s in value]

    supersedes = id_list("supersedes")
    scope = meta.get("scope") or []
    if not isinstance(scope, list) or not all(isinstance(x, dict) for x in scope):
        raise AdrError(f"{path}: {did} scope must be a list of selector maps")
    return Decision(
        id=did,
        title=str(meta["title"]),
        status=meta["status"],
        owner=str(meta.get("owner", "")),
        date=_date(meta, "date", path, did) or "",
        review_date=_date(meta, "review_date", path, did),
        supersedes=supersedes,
        path=path,
        rules=rules,
        depends_on=id_list("depends_on"),
        conflicts_with=id_list("conflicts_with"),
        scope=scope,
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
