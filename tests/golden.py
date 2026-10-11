"""The recorded expectations (tests/golden/*.json.gz): each case's inputs
and what vetter gave for them, recorded from the Python vetter that came
before the one in zrun's subset; `pytest --update-golden` records what
vetter gives now instead (after reviewing what changed)."""

import gzip
import json
import pathlib

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"

# (pytest --update-golden: conftest.py sets it)
UPDATE = []


def load_golden(name):
    with gzip.open(GOLDEN / f"{name}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def save_golden(name, cases):
    with gzip.open(GOLDEN / f"{name}.json.gz", "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(cases, f, ensure_ascii=False, separators=(",", ":"))


def plain(x):
    """Records' lists and tuples as lists, for comparing with JSON"""
    if isinstance(x, (list, tuple)):
        return [plain(y) for y in x]
    return x


def compare(name, cases, got):
    """got[i]: what vetter gives for cases[i]["in"]; with --update-golden,
    recorded as the expectation"""
    if UPDATE:
        save_golden(name, [{"in": c["in"], "out": plain(g)} for c, g in zip(cases, got)])
        return
    for c, g in zip(cases, got):
        assert plain(g) == c["out"], c["in"]
