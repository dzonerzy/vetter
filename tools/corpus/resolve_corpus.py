"""The resolver on the corpus: does it find what each case runs (`runs`)?

A program the case runs is found (by name), or the resolution has a part
it can't see (an Unknown, or a command name only running tells): then the
policy asks. A program neither found nor covered is a gap.

    python -m tools.corpus.resolve_corpus [-v] [ID...]
"""

import argparse
import posixpath
import sys

from tools.corpus import corpus
from vetter import engine
from vetter.policy.actions import execution_text
from vetter.shells.bash import resolve
from vetter.shells.bash.resolve import exec_name


def check(case):
    r = engine.run(resolve.resolve, case["command"].rstrip("\n"), "/home/user/project", "/home/user")
    found = {exec_name(e) for e in r.executions if exec_name(e)}
    dynamic_names = [e for e in r.executions if exec_name(e) is None and e.kind != "group" and e.kind != "redirect"]
    covered = bool(r.unknowns or dynamic_names)
    missing = [p for p in case["runs"] if posixpath.basename(p) not in found]
    return r, found, covered, missing


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", action="store_true")
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args(argv)
    cases = [c for c in corpus.load() if c["shell"] == "bash" and (not args.ids or c["id"] in args.ids)]
    gaps = 0
    static = 0
    for c in cases:
        r, found, covered, missing = check(c)
        if not missing:
            static += 1
        gap = missing and not covered
        gaps += bool(gap)
        if args.v or gap or args.ids:
            mark = "GAP " if gap else ("ok  " if not missing else "dyn ")
            print(f"{mark}{c['id']}: runs {c['runs']}")
            for e in r.executions:
                print(f"      {e.kind:8s} {execution_text(e)}")
            for u in r.unknowns:
                print(f"      unknown  {u.reason}")
            if missing:
                print(f"      not found: {missing}")
    print(f"\n{len(cases)} cases: all found statically {static}, the rest covered by unknowns, gaps {gaps}")
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
