"""The bypass corpus (corpus/): loading it, and checking it (every case
complete, ids unique, every bash command valid bash: `bash -n`).

    python -m tools.corpus.corpus          # check, print a summary
"""

import pathlib
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "corpus"
FIELDS = {"id", "shell", "command", "runs", "expect", "why", "source"}
DECISIONS = {"allow", "ask", "deny"}


def load(root=ROOT):
    """Every case, with the file it came from (`file`); a file's
    `[defaults]` fill what its cases don't say."""
    cases = []
    for path in sorted(root.rglob("*.toml")):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        defaults = data.get("defaults", {})
        for case in data.get("case", []):
            case = {**defaults, **case}
            case["file"] = str(path.relative_to(root))
            cases.append(case)
    return cases


def bash_accepts(command):
    """Does bash parse the command (without running it)?"""
    r = subprocess.run(["bash", "-n"], input=command, capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()


def check(cases):
    problems = []
    seen = set()
    for c in cases:
        missing = FIELDS - c.keys()
        if missing:
            problems.append(f"{c.get('id', '?')} ({c['file']}): missing {sorted(missing)}")
        if c.get("id") in seen:
            problems.append(f"{c['id']}: duplicate id")
        seen.add(c.get("id"))
        if c.get("expect") not in DECISIONS:
            problems.append(f"{c.get('id')}: expect must be one of {sorted(DECISIONS)}")
        if c.get("shell") == "bash":
            ok, err = bash_accepts(c["command"])
            if not ok:
                problems.append(f"{c['id']}: bash rejects it: {err}")
    return problems


if __name__ == "__main__":
    cases = load()
    problems = check(cases)
    by_file = {}
    for c in cases:
        by_file[c["file"]] = by_file.get(c["file"], 0) + 1
    for f, n in by_file.items():
        print(f"{n:3d}  {f}")
    print(f"{len(cases):3d}  cases")
    for p in problems:
        print("PROBLEM:", p)
    sys.exit(1 if problems else 0)
