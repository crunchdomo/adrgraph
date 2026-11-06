"""Baseline file: known violations that check reports as `baselined` instead of failing."""
import json
import os

Key = tuple[str, str, str]  # (decision, rule, node_id)


def load_baseline(path: str) -> set[Key]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {(v["decision"], v["rule"], v["node_id"]) for v in data.get("violations", [])}


def save_baseline(path: str, keys: set[Key]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rows = [{"decision": d, "rule": r, "node_id": n} for d, r, n in sorted(keys)]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "violations": rows}, fh, indent=2)
        fh.write("\n")
