"""Paths (vetter/paths.py) as recorded (tests/golden), on generated
inputs; globs (vetter/glob.py) against fnmatch.fnmatchcase."""

import fnmatch
import random

from golden import UPDATE, load_golden, save_golden
from vetter import glob, paths


def test_paths_as_recorded():
    cases = load_golden("paths")
    got = []
    for c in cases:
        p, q = c["in"]
        got.append([paths.is_windows(p), paths.to_slashes(p), paths.is_abs(p), paths.norm(p), paths.program_name(p),
                    paths.join(q, p), paths.join(None, p), paths.same(p, q), paths.inside(p, q)])
    if UPDATE:
        save_golden("paths", [{"in": c["in"], "out": g} for c, g in zip(cases, got)])
        return
    for c, g in zip(cases, got):
        assert g == c["out"], c["in"]


GLOB_CHARS = ["*", "?", "[", "]", "!", "-", "a", "b", "c", "/", ".", "z"]


def test_glob_same_as_fnmatch():
    rnd = random.Random(11)
    for _ in range(50000):
        pattern = "".join(rnd.choice(GLOB_CHARS) for _ in range(rnd.randint(0, 7)))
        name = "".join(rnd.choice(["a", "b", "c", "/", ".", "-", "[", "]", "z", "!"]) for _ in range(rnd.randint(0, 7)))
        assert glob.match(name, pattern) == fnmatch.fnmatchcase(name, pattern), (name, pattern)
    for name, pattern in [("/home/u/project/build/x", "/home/u/project/*"), ("a.github.com", "*.github.com"),
                          ("github.com", "*.github.com"), ("x/__pycache__/y", "*/__pycache__/*")]:
        assert glob.match(name, pattern) == fnmatch.fnmatchcase(name, pattern)
