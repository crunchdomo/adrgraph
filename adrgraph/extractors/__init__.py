"""Extractor registry: file extension -> extract(rel_path, source, module_name) -> Extraction."""
from collections.abc import Callable

from adrgraph.extractors import python
from adrgraph.model import Extraction

EXTRACTORS: dict[str, Callable[[str, bytes, str], Extraction]] = {
    ".py": python.extract,
}
