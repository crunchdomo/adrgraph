"""Shared graph vocabulary. Every extractor emits only these types."""
from dataclasses import dataclass, field

UNIT_KINDS = {"file", "package", "module", "external"}
SYMBOL_KINDS = {"function", "method", "class", "type", "variable", "resource", "module_call", "unresolved"}
EDGE_LABELS = {"CONTAINS", "IMPORTS", "CALLS", "REFERENCES"}


@dataclass(frozen=True)
class Unit:
    id: str
    path: str
    name: str
    lang: str
    kind: str


@dataclass(frozen=True)
class Symbol:
    id: str
    name: str
    qualified: str
    kind: str
    lang: str
    path: str
    line: int
    end_line: int
    ast_kind: str


@dataclass(frozen=True)
class Edge:
    label: str
    src: str
    dst: str


@dataclass(frozen=True)
class RawImport:
    """An import as written. `names` are (imported_name, local_alias) pairs for
    `from X import a as b`; `alias` is the local name for `import X as alias`;
    `level` is the number of leading dots."""
    unit_id: str
    module: str
    level: int
    line: int
    names: tuple[tuple[str, str], ...] = ()
    alias: str | None = None


@dataclass(frozen=True)
class RawRef:
    """A dotted name referenced from `src_id` (a Symbol id, or the Unit id at module scope)."""
    src_id: str
    name: str
    line: int
    call: bool


@dataclass
class Extraction:
    units: list[Unit] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    imports: list[RawImport] = field(default_factory=list)
    refs: list[RawRef] = field(default_factory=list)


def symbol_id(path: str, qualified: str) -> str:
    return f"{path}::{qualified}"


def unresolved_id(name: str) -> str:
    return f"unresolved::{name}"
