"""vetter's decisions on the corpus with a policy (the stock one by
default), against each case's `expect`:

- ALLOWED: a bypass vetter allows (expect deny or ask): the failure that
  matters;
- weaker: expect deny, vetter asks (still stopped, a person decides);
- noise: a harmless command (expect allow) vetter asks about or denies.

    python -m tools.corpus.decide_corpus [--policy FILE] [-v]

The gpt-obfuscated.toml cases hide a harmless payload (touch /tmp/pwned):
they're decided with the policy plus a rule denying it, so what's measured
is whether vetter sees it.
"""

import argparse
import sys

from tools.corpus import corpus
from vetter import engine
from vetter.cli import STOCK
from vetter.places import project_root
from vetter.policy.language import ORDER, TEST_PLACES

# (the gpt batches' harmless payloads, denied: first match, before the
# policy's rules, which `use` puts after it)
PAYLOAD_POLICY = ('policy corpus\ndeny "the corpus payload" write exactly /tmp/pwned, '
                  '~/AppData/Local/Temp/pwned.txt\nuse stock\n')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default=str(STOCK))
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args(argv)
    text = open(args.policy).read()
    p = engine.call("load_text", text, args.policy)
    with_payload = engine.call("load_text", PAYLOAD_POLICY, "corpus.vet")
    counts = {"right": 0, "ALLOWED": 0, "weaker": 0, "stricter": 0, "noise": 0}
    for c in corpus.load():
        if c["shell"] not in ("bash", "powershell", "cmd"):
            continue
        pol = with_payload if c["file"].endswith("gpt-obfuscated.toml") else p
        cwd, home = TEST_PLACES["windows" if c["shell"] in ("powershell", "cmd") else "posix"]
        d = engine.call("check", pol, c["command"].strip("\n"), c["shell"], cwd, home, project_root(cwd, home), None)
        exp, got = c["expect"], d.decision
        if got == exp:
            kind = "right"
        elif exp == "allow":
            kind = "noise"
        elif got == "allow":
            kind = "ALLOWED"
        elif ORDER[got] < ORDER[exp]:
            kind = "weaker"
        else:
            kind = "stricter"
        counts[kind] += 1
        if args.v or kind in ("ALLOWED", "noise", "weaker"):
            print(f"{kind:8s} {c['id']}: expect {exp}, got {got}: {d.reason[:110]}")
    total = sum(counts.values())
    print(f"\n{total} cases: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 1 if counts["ALLOWED"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
