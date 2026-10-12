"""`vetter learn`: rules from what the user said yes to. The hook logs each
decision with the agent's id for the call, and (PostToolUse) each call
that ran: an ask whose call ran is a yes. Each command said yes to is
decided again, and what made it asked made the narrowest rule that would
allow it: the program and its subcommands (no rule named it), the host it
connects to, the folder in the project it deletes or writes in, the
folder it reads. Never: what vetter couldn't see, what a rule asks about
on purpose (losing work, sudo, what the agent wrote), anything denied, a
rule the user also said no to once. The rules go in the user's policy,
before its `use`: a used policy's deny rules still come first.

    vetter learn [--min N] [--apply all|1,3] [--policy FILE] [--log FILE]
"""

import os
import re

from .. import engine, places

# (the asks a rule makes only about places: a yes to one says where; the
# others are asked on purpose, whatever the user said before)
LEARNABLE = {"deleting files", "network"}
WORD = re.compile(r"^[a-z][a-z0-9._-]*$")


def said(entries):
    """(asks said yes to, asks not said yes to): log entries."""
    ran = {e["ran"] for e in entries if isinstance(e.get("ran"), str)}
    yes = []
    no = []
    for e in entries:
        if e.get("decision") != "ask" or not isinstance(e.get("id"), str) or not isinstance(e.get("command"), str):
            continue
        (yes if e["id"] in ran else no).append(e)
    return yes, no


def rules_for(policy, entry, home):
    """The rules that would have allowed what made this command asked;
    None: it can't be learned (a part vetter couldn't see, one asked on
    purpose, one denied)."""
    d, project = decided(policy, entry, home)
    if d.decision != "ask":
        return []
    out = []
    for pd in d.parts:
        if pd.decision == "deny":
            return None
        if pd.decision != "ask":
            continue
        if pd.part.unknown:
            return None
        if pd.by != "default" and (pd.rule is None or pd.rule.reason not in LEARNABLE):
            return None
        for ad in pd.actions:
            # (a run asked for what it does: the doing's rule, not the
            # program's)
            if ad.decision != "ask" or ad.reason.startswith("by what it does"):
                continue
            rule = rule_for(pd.part, ad.action, project)
            if rule is None:
                return None
            if rule not in out:
                out.append(rule)
    return out


def decided(policy, entry, home):
    """The logged command decided again where it ran: (decision, project)."""
    cwd = entry.get("cwd") or home
    project = entry.get("project") or places.project_root(cwd, home)
    return engine.call("check", policy, entry["command"], "bash", cwd, home, project, None), project


def rule_for(part, a, project):
    if a.verb == "run" and a.kind is None:
        if part.name is None or part.dynamic or not WORD.match(part.name.lower()):
            return None
        # (its subcommands: the words before its first option)
        words = [part.name]
        for f in part.what.argv[1:3]:
            x = engine_static(f)
            if x is None or not WORD.match(x):
                break
            words.append(x)
        return " ".join(words)
    if (a.verb == "network" or a.verb == "download") and a.host:
        return "network to " + a.host
    if (a.verb == "delete" or a.verb == "write") and a.path and project and a.path.startswith(project + "/"):
        rest = a.path[len(project) + 1:]
        if "/" in rest:
            return a.verb + " in " + quote(project + "/" + rest.partition("/")[0])
        return a.verb + " exactly " + quote(a.path)
    if a.verb == "read" and a.path and "/" in a.path.rstrip("/"):
        return "read in " + quote(a.path.rstrip("/").rpartition("/")[0] or "/")
    return None


def engine_static(f):
    from ..shells.bash.expand import field_known, field_static

    return field_static(f) if field_known(f) else None


def quote(p):
    return p if re.match(r"^[A-Za-z0-9_./~$:-]+$", p) else '"' + p.replace('"', '\\"') + '"'


def suggestions(policy, text, path, entries, home, least):
    """[(rule, how many yeses, examples)], those said yes to `least` times
    or more, none allowing a command the user said no to."""
    yes, no = said(entries)
    count = {}
    examples = {}
    for e in yes:
        rules = rules_for(policy, e, home)
        for r in rules or []:
            count[r] = count.get(r, 0) + 1
            examples.setdefault(r, [])
            if e["command"] not in examples[r] and len(examples[r]) < 3:
                examples[r].append(e["command"])
    out = []
    still = [e for e in no if decided(policy, e, home)[0].decision != "allow"]
    for r, n in count.items():
        if n < least:
            continue
        # (one it would have allowed, said no to: not learned)
        trial = engine.call("load_text", with_rules(text, [r]), path)
        if any(decided(trial, e, home)[0].decision == "allow" for e in still):
            continue
        out.append((r, n, examples[r]))
    return sorted(out, key=lambda x: -x[1])


def with_rules(text, rules):
    """The policy's text with the rules added before its first `use` (at
    the end if it has none)."""
    block = "".join(f'allow "learned: {r}" {r}\n' for r in rules)
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("use "):
            return "".join(lines[:i]) + block + "\n" + "".join(lines[i:])
    return text + ("" if text.endswith("\n") else "\n") + block


def run(args):
    home = places.home_dir()
    path = places.path_text(places.expand_user(args.policy, home)) if args.policy else \
        places.path_text(home + "/.config/vetter/policy.vet")
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else "policy mine\n\nuse stock\n"
    policy = engine.call("load_text", text, path)
    log = places.path_text(places.expand_user(args.log, home)) if args.log else places.log_path(home)
    found = suggestions(policy, text, path, engine.call("log_entries", log), home, args.min)
    if not found:
        print("nothing to learn: no ask said yes to " + str(args.min) + " times or more (the hook logs a yes "
              "where the agent tells it a command ran: `vetter install claude` again if it's older)")
        return 0
    for k, (rule, n, ex) in enumerate(found, 1):
        print(f"{k:3d}. allow {rule}")
        print(f"     said yes {n} times: " + "; ".join(x.replace(chr(10), " ")[:60] for x in ex))
    if not args.apply:
        print(f"\n`vetter learn --apply all` (or --apply 1,3) adds them to {path}")
        return 0
    chosen = [r for r, _, _ in found] if args.apply == "all" else \
        [found[int(x) - 1][0] for x in args.apply.split(",") if x.strip().isdigit() and 0 < int(x) <= len(found)]
    new = with_rules(text, chosen)
    # (it must load: its tests pass, its rules all reachable)
    engine.call("load_text", new, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"\nadded {len(chosen)} rule{'s' if len(chosen) != 1 else ''} to {path}")
    return 0
