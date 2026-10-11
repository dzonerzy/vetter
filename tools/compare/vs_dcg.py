"""The bypass corpus through dcg (destructive_command_guard), the incumbent:
its decision on each case (`dcg test`, which runs nothing) against the
corpus' expectation. A bypass dcg allows is a miss; a harmless command it
denies, a needless prompt.

    python -m tools.compare.vs_dcg --dcg PATH [--config dcg.toml] [-v]

dcg blocks destructive commands, and the gpt-* cases' payload (touch) isn't
one: --config with a pack that blocks touch the way dcg blocks rm -rf (its
reading is what's measured then: plain `touch x` is denied, `echo touch`
allowed).
"""

import argparse
import json
import subprocess
import sys

from tools.corpus import corpus


def dcg_decision(dcg, command, config=None):
    extra = ["--config", config] if config else []
    r = subprocess.run([dcg, "test", "--stdin", "--format", "json"] + extra, input=command,
                       capture_output=True, text=True, errors="replace")
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        return "error", r.stderr.strip()[:200]
    return out.get("decision", "?"), out.get("rule_id") or out.get("reason") or ""


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dcg", required=True)
    ap.add_argument("--config")
    ap.add_argument("-v", action="store_true", help="every case, not only the misses")
    args = ap.parse_args(argv)

    missed = []
    needless = []
    by_file = {}
    for c in corpus.load():
        if c["shell"] != "bash":
            continue
        decision, why = dcg_decision(args.dcg, c["command"], args.config)
        blocked = decision in ("deny", "ask")
        f = by_file.setdefault(c["file"], [0, 0])
        f[1] += 1
        if c["expect"] == "allow":
            ok = not blocked
            if not ok:
                needless.append((c, decision, why))
        else:
            ok = blocked
            if not ok:
                missed.append((c, decision, why))
        f[0] += ok
        if args.v:
            print(f"{'ok  ' if ok else 'MISS'} {c['id']:44s} dcg: {decision:6s} {why[:70]}")

    print("\nper file (dcg right / cases):")
    for f, (ok, n) in sorted(by_file.items()):
        print(f"  {ok:3d}/{n:<3d} {f}")
    total = sum(n for _, n in by_file.values())
    print(f"\ndcg lets through {len(missed)} of {total - sum(1 for c in corpus.load() if c['expect'] == 'allow')} bypasses"
          f" and blocks {len(needless)} harmless commands")
    if not args.v:
        for c, decision, _ in missed:
            print(f"  missed: {c['id']}: {c['command'][:90]!r}")
        for c, decision, why in needless:
            print(f"  blocked harmless: {c['id']}: {why[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
