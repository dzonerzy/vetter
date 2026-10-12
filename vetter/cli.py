"""vetter's command line.

    vetter check [--policy FILE] [--cwd DIR] [--home DIR] [--shell bash|powershell|cmd] [--json] COMMAND
    vetter why [--policy FILE] [--cwd DIR] [--home DIR] [--shell ...] [--all | --rule LINE] COMMAND
    vetter test [--policy FILE] [--coverage]
    vetter lint [--policy FILE] [--project]
    vetter import claude|codex [--from PATH] [-o FILE [--force]]
    vetter replay [--policy FILE] [--log FILE] [--limit N]
    vetter hook AGENT [--policy FILE]           (claude codex gemini cursor copilot cline amp opencode json)
    vetter install AGENT [--settings FILE] [--dry-run]   (the same, and vscode)

The policy: --policy, else ~/.config/vetter/policy.vet, else the stock one;
a project's .vetter.vet adds its deny and ask rules (never allow: the agent
could write it). vetter's code runs through engine.py (zrun's reference
mode); what's here is the command line's own: its options, its output,
`vetter lint`'s checks (policy/checks.py).
"""

import argparse
import json
import os
import pathlib
import re
import sys

from . import __version__, engine, paths, places
from .agents.hook import AGENTS
from .check import SHELLS
from .places import STOCK as STOCK_POLICY
from .policy import trace
from .policy.actions import action_text
from .policy.language import POLICIES, POLICY, unreachable, where

STOCK = pathlib.Path(STOCK_POLICY[1])

EXIT = {"allow": 0, "ask": 1, "deny": 2}


class PolicyError(ValueError):
    """A policy that doesn't load: where, and what's wrong."""


def load_policy(path=None, cwd=None, home=None):
    """The policy (`ignored`: a project's allow rules left out) and the
    warnings `vetter lint` finds in it; its errors a PolicyError."""
    home = home or places.home_dir()
    try:
        policy = engine.call("load_policy", path or "", cwd, home)
    except ValueError as e:
        message = str(e)
        raise PolicyError(message[8:] if message.startswith("policy: ") else message) from None
    text = STOCK_POLICY[0] if policy.filename == STOCK_POLICY[1] else places.read_text(policy.filename)
    warnings = _checked(text, policy.filename, set(policy.lets) - _own_lets(text),
                        builtin=policy.filename.startswith(str(POLICIES)))
    found = places.project_policy(cwd, home) if cwd is not None else None
    if found is not None:
        warnings += _checked(places.read_text(found), found, set(policy.lets))
    return policy, warnings


def _own_lets(text):
    return {m[1] for m in re.finditer(r"(?m)^let\s+([a-z_][a-z0-9_-]*)", text)}


def _checked(text, filename, known_lets, builtin=False):
    """checks.py on a policy's text: its errors stop it loading, its
    warnings are returned."""
    from .policy import checks

    errors, warnings = checks.check(POLICY, text, pathlib.Path(filename).name, known_lets,
                                    lets_used_elsewhere=builtin)
    if errors:
        raise PolicyError("\n".join(errors))
    return warnings


def _decide(args, traced=False):
    # (C:/Users/... given on Linux: kept as it is, to try Windows commands)
    cwd = args.cwd if paths.is_abs(args.cwd) else os.path.abspath(args.cwd)
    home = args.home or places.home_dir()
    policy, _ = load_policy(args.policy, cwd, home)
    # (why each rule didn't match: what `why --all` and `--rule` show)
    policy.trace = traced
    for r in policy.ignored or []:
        print(f"(ignored: {where(r)}: a project's policy can't allow: {r.reason})", file=sys.stderr)
    temp = places.temp_dirs(home, not args.home)
    return engine.call("check", policy, args.command, args.shell, cwd, home, places.project_root(cwd, home), temp)


def cmd_check(args):
    d = _decide(args)
    if args.json:
        print(json.dumps(_decision_json(d)))
    else:
        ref = f" [{where(d.rule)}]" if d.rule is not None else ""
        print(f"{d.decision}: {d.reason}{ref}")
        mark = trace.caret(args.command, d.span)
        if mark:
            print(mark)
    return EXIT[d.decision]


def _decision_json(d):
    return {
        "decision": d.decision,
        "reason": d.reason,
        "rule": {"file": d.rule.file, "line": d.rule.line} if d.rule is not None else None,
        "by": d.by,
        "span": {"start": d.span[0], "end": d.span[1]},
        "parts": [{"what": p.part.label, "decision": p.decision,
                   "actions": [{"action": action_text(a.action), "decision": a.decision, "reason": a.reason,
                                "rule": where(a.rule) if a.rule else None} for a in p.actions]}
                  for p in d.parts],
    }


def cmd_why(args):
    d = _decide(args, traced=args.all or args.rule is not None)
    print(trace.show(d, args.command, every_rule=args.all, only_rule=args.rule))
    return EXIT[d.decision]


def cmd_import(args):
    """An agent's permission rules as a vetter policy: printed, or written to
    --output."""
    from .agents import importing

    if args.agent == "claude":
        src = pathlib.Path(args.source or "~/.claude/settings.json").expanduser()
        text = importing.from_claude(importing.read_claude(src) if src.exists() else {}, str(src))
    else:
        d = pathlib.Path(args.source or "~/.codex/rules").expanduser()
        files = [d] if d.is_file() else sorted(d.glob("*.rules")) if d.is_dir() else []
        text = importing.from_codex({f.name: f.read_text() for f in files}, str(d))
    # (what's written must load: it's checked like any policy)
    check_text(text, "imported.vet")
    if args.output:
        out = pathlib.Path(args.output).expanduser()
        if out.exists() and not args.force:
            print(f"{out} exists (--force to replace it)", file=sys.stderr)
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"written: {out}")
    else:
        sys.stdout.write(text)
    return 0


def check_text(text, filename):
    """A policy's text loaded and linted (a PolicyError if it doesn't load):
    the policy."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        policy, _ = load_policy(path)
    return policy


def _unreachable_lines(policy):
    hidden = unreachable(policy)
    for b, a in hidden:
        print(f"{where(b)}: {b.decision} {b.reason!r} is never reached: {where(a)} ({a.decision} {a.reason!r}) "
              f"decides first")
    return hidden


def cmd_lint(args):
    """What's wrong with a policy without running it: errors, warnings
    (typos in programs, subcommands, flags; lists never used), rules never
    reached."""
    try:
        policy, warnings = load_policy(args.policy, os.getcwd() if args.project else None)
    except PolicyError as e:
        print(e)
        return 2
    for w in warnings:
        print(w)
    hidden = _unreachable_lines(policy)
    for r in policy.ignored or []:
        print(f"{where(r)}: a project's policy can't allow: {r.reason} (left out)")
    problems = len(warnings) + len(hidden)
    print(f"{problems} problem{'s' if problems != 1 else ''} ({len(policy.rules)} rules)")
    return 1 if problems else 0


def cmd_test(args):
    try:
        policy, warnings = load_policy(args.policy)
    except PolicyError as e:
        print(e)
        return 2
    for w in warnings:
        print(w)
    hidden = _unreachable_lines(policy)
    # (a failure shown with every rule tried, and why)
    policy.trace = True
    failures = engine.call("run_tests", policy)
    for filename, line, command, exp, d in failures:
        print(f"{pathlib.Path(filename).name}:{line}: test {exp}: {command}")
        print(f"  got {d.decision}\n")
        print("\n".join("  " + x for x in trace.show(d, command, every_rule=True).split("\n")))
        print()
    if args.coverage:
        for r in engine.call("coverage", policy):
            print(f"{where(r)}: no test reaches {r.decision} {r.reason!r}")
    print(f"{len(policy.tests) - len(failures)}/{len(policy.tests)} tests pass ({len(policy.rules)} rules"
          + (f", {len(hidden)} never reached" if hidden else "") + ")")
    return 1 if failures or hidden else 0


def cmd_replay(args):
    """The logged commands through a policy: what it decides differently."""
    home = places.home_dir()
    policy, _ = load_policy(args.policy, None, home)
    path = places.path_text(places.expand_user(args.log, home)) if args.log else places.log_path(home)
    entries = engine.call("log_entries", path)
    if args.limit:
        entries = entries[-args.limit:]
    changed = 0
    for e in entries:
        cwd = e.get("cwd")
        d = engine.call("check", policy, e["command"], "bash", cwd, home, places.project_root(cwd, home), None)
        if d.decision == e["decision"]:
            continue
        changed += 1
        print(f"{e['decision']} -> {d.decision}   {e['command']}")
        print(f"   was: {e.get('rule')}")
        ref = f" [{where(d.rule)}]" if d.rule is not None else f" [{d.by}]"
        print(f"   now: {d.reason}{ref}\n")
    print(f"{changed} of {len(entries)} logged commands decided differently by {policy.filename}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vetter", description="Vets every command your AI agent wants to run.")
    ap.add_argument("--version", action="version", version=f"vetter {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="decide about a command")
    p.add_argument("--policy")
    p.add_argument("--cwd", default=".")
    p.add_argument("--home", help="the user's home (default: yours)")
    p.add_argument("--shell", choices=SHELLS, default="bash")
    p.add_argument("--json", action="store_true")
    p.add_argument("command")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("why", help="how a command was read and which rules decided")
    p.add_argument("--policy")
    p.add_argument("--cwd", default=".")
    p.add_argument("--home", help="the user's home (default: yours)")
    p.add_argument("--shell", choices=SHELLS, default="bash")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="every rule tried, and why it didn't match")
    g.add_argument("--rule", type=int, metavar="LINE", help="only the rule at this line")
    p.add_argument("command")
    p.set_defaults(func=cmd_why)

    p = sub.add_parser("test", help="run a policy's tests, find the rules it never reaches")
    p.add_argument("--policy")
    p.add_argument("--coverage", action="store_true", help="the rules no test reaches")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("import", help="an agent's permission rules as a vetter policy")
    p.add_argument("agent", choices=["claude", "codex"])
    p.add_argument("--from", dest="source", help="its settings (claude) or rules file or folder (codex)")
    p.add_argument("-o", "--output", help="write it there (e.g. ~/.config/vetter/policy.vet)")
    p.add_argument("--force", action="store_true", help="replace --output if it exists")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("lint", help="a policy's problems without running it: typos, unused lists, rules never "
                                    "reached")
    p.add_argument("--policy")
    p.add_argument("--project", action="store_true", help="with this directory's project policy (.vetter.vet)")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("replay", help="the logged commands through a policy: what it decides differently")
    p.add_argument("--policy")
    p.add_argument("--log", help="the log (default: ~/.local/state/vetter/log.jsonl)")
    p.add_argument("--limit", type=int, help="only the last N")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("learn", help="rules from the asks you said yes to (shown; --apply adds them)")
    p.add_argument("--policy", help="the policy to add them to (default: ~/.config/vetter/policy.vet)")
    p.add_argument("--log", help="the log (default: ~/.local/state/vetter/log.jsonl)")
    p.add_argument("--min", type=int, default=2, help="said yes to at least this many times (default 2)")
    p.add_argument("--apply", help="all, or the suggestions' numbers: 1,3")
    p.set_defaults(func=lambda a: _learn().run(a))

    p = sub.add_parser("hook", help="an agent's hook: its request on stdin, the decision on stdout")
    p.add_argument("agent", choices=sorted(AGENTS))
    p.add_argument("--policy")
    p.set_defaults(func=lambda a: engine.call("hook", a.agent, a.policy or ""))

    p = sub.add_parser("install", help="install the hook in an agent's settings")
    p.add_argument("agent", choices=["amp", "claude", "cline", "codex", "copilot", "cursor", "gemini", "opencode",
                                     "vscode"])
    p.add_argument("--settings", help="the file to write (default: the agent's user settings)")
    p.add_argument("--dry-run", action="store_true", help="show the change, don't write it")
    p.set_defaults(func=lambda a: _install().install(a.agent, a.settings, a.dry_run))

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except PolicyError as e:
        print(f"policy: {e}", file=sys.stderr)
        return 2


def _install():
    from .agents import install

    return install


def _learn():
    from .agents import learn

    return learn


if __name__ == "__main__":
    sys.exit(main())
