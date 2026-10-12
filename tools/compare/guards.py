"""The corpus through other command guards, as their Claude Code hooks: what
each stops (deny or ask) of the attacks, what each stops of the harmless
commands. A guard that says nothing leaves the command to the agent's own
rules: for an attack, not stopped.

    python -m tools.compare.guards --dcg PATH --ccsn PATH [--shell bash] [-v]

(vs_dcg.py asks dcg through `dcg test`; this, each guard as the agent runs
it, its hook.)

Each runs with a scratch HOME (their logs and state there, not yours), the
corpus's /home/user that home, for every guard, vetter's too.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib

from tools.corpus import corpus
from vetter import engine
from vetter.cli import STOCK


def dcg_corpus(root):
    """dcg's own corpus (its tests/corpus/**/*.toml, its home turf): each
    case a bash command and what dcg's authors expect, deny or allow."""
    out = []
    for dirpath, _, names in sorted(os.walk(os.path.join(root, "tests", "corpus"))):
        for name in sorted(names):
            if not name.endswith(".toml"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                data = tomllib.load(f)
            for c in data.get("case", []):
                expect = c.get("expected_decision") or c.get("expected")
                if not isinstance(c.get("command"), str) or expect not in ("allow", "deny", "ask", "warn"):
                    continue
                out.append({"id": c.get("id") or c.get("description") or c["command"][:40], "shell": "bash",
                            "command": c["command"], "expect": "allow" if expect == "allow" else "deny",
                            "file": path})
    return out


def hook_request(command, shell, cwd):
    tool = "PowerShell" if shell == "powershell" else "Bash"
    return json.dumps({"session_id": "compare", "hook_event_name": "PreToolUse", "tool_name": tool,
                       "tool_input": {"command": command}, "cwd": cwd})


def hook_decision(argv, request, home, cwd):
    """deny / ask / allow, or pass: nothing said."""
    env = {"HOME": home, "PATH": os.environ.get("PATH", ""), "XDG_CONFIG_HOME": home + "/.config",
           "XDG_DATA_HOME": home + "/.local/share", "XDG_STATE_HOME": home + "/.local/state",
           "XDG_CACHE_HOME": home + "/.cache"}
    try:
        r = subprocess.run(argv, input=request, capture_output=True, text=True, timeout=30, env=env, cwd=cwd)
    except subprocess.TimeoutExpired:
        return "error"
    if r.returncode == 2:
        return "deny"
    text = r.stdout.strip()
    if text == "":
        return "pass"
    try:
        out = json.loads(text.splitlines()[-1])
    except ValueError:
        return "error"
    hso = out.get("hookSpecificOutput") or {}
    d = hso.get("permissionDecision") or out.get("decision")
    if d == "block":
        return "deny"
    return d if d in ("deny", "ask", "allow") else "pass"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dcg")
    ap.add_argument("--ccsn")
    ap.add_argument("--shell", default="bash")
    ap.add_argument("--dcg-corpus", help="dcg's source tree: its own corpus, not vetter's")
    ap.add_argument("--exclude", action="append", default=["gpt-obfuscated.toml"],
                    help="corpus files left out (gpt-obfuscated.toml: its payload, touch, harmless by design)")
    ap.add_argument("--work", default=os.path.expanduser("~/.cache/vetter-compare"))
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args(argv)
    home = os.path.join(args.work, "home")
    project = os.path.join(home, "project")
    shutil.rmtree(args.work, ignore_errors=True)
    os.makedirs(project)
    guards = {"vetter": None}
    if args.dcg:
        guards["dcg"] = [args.dcg]
    if args.ccsn:
        guards["cc-safety-net"] = [shutil.which("node") or "node", args.ccsn, "hook", "--claude-code"]
    p = engine.call("load_text", open(STOCK).read(), str(STOCK))
    # (per guard: attacks stopped / all, harmless stopped / all)
    score = {g: [0, 0, 0, 0] for g in guards}
    by_file = {}
    try:
        cases = dcg_corpus(args.dcg_corpus) if args.dcg_corpus else corpus.load()
        for c in cases:
            if c["shell"] != args.shell or os.path.basename(c["file"]) in args.exclude:
                continue
            command = c["command"].strip("\n").replace("/home/user", home)
            harmless = c["expect"] == "allow"
            got = {}
            for g, argv_ in guards.items():
                if argv_ is None:
                    got[g] = engine.call("check", p, command, args.shell, project, home, project, None).decision
                else:
                    got[g] = hook_decision(argv_, hook_request(command, args.shell, project), home, project)
                stopped = got[g] in ("deny", "ask")
                s = score[g]
                if harmless:
                    s[3] += 1
                    s[2] += 1 if stopped else 0
                else:
                    s[1] += 1
                    s[0] += 1 if stopped else 0
            f = os.path.basename(os.path.dirname(c["file"])) + "/" + os.path.basename(c["file"])
            row = by_file.setdefault(f, {g: [0, 0] for g in guards})
            for g in guards:
                row[g][1] += 1
                stopped = got[g] in ("deny", "ask")
                row[g][0] += 1 if stopped != harmless else 0
            if args.v:
                print(f"{c['id']:44s} expect {c['expect']:5s} " + " ".join(f"{g}={got[g]}" for g in guards))
    finally:
        shutil.rmtree(args.work, ignore_errors=True)
    print(f"\n{'guard':16s} {'attacks stopped':>18s} {'harmless stopped':>18s}")
    for g, (a, an, h, hn) in score.items():
        print(f"{g:16s} {a:6d} / {an:<4d} {100 * a / max(an, 1):5.1f}% {h:6d} / {hn:<4d} {100 * h / max(hn, 1):5.1f}%")
    print("\nright, by corpus file (attacks stopped, harmless let through):")
    print(f"{'file':40s} " + " ".join(f"{g:>14s}" for g in guards))
    for f in sorted(by_file):
        print(f"{f:40s} " + " ".join(f"{by_file[f][g][0]:>6d} / {by_file[f][g][1]:<5d}" for g in guards))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
