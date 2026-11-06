"""Trail -> plain dict, for `check --trails` and the explorer overlay."""
from dataclasses import asdict

from adrgraph.trail import Trail


def trail_dict(trail: Trail) -> dict:
    return {"finding": asdict(trail.finding), "steps": [asdict(s) for s in trail.steps]}
