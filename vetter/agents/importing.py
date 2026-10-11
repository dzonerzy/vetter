"""`vetter import`: an agent's own permission rules as a vetter policy.

Their rules come first (Claude Code's deny, then ask, then allow; Codex's
in their order), then `use stock`: the stock policy's denies still come
before everything (what they forbid stays forbidden), its other rules
decide what the imported ones don't name. What can't be said in vetter's
terms is left as a comment saying why.

    text = from_claude(settings_dict, "~/.claude/settings.json")
    text = from_codex({"default.rules": source})
"""

import ast
import datetime
import json
import re

# ----------------------------------------------------------------------
# Claude Code: permissions.allow / ask / deny
# ----------------------------------------------------------------------

_ENTRY = re.compile(r"^(?P<tool>[A-Za-z]+)(?:\((?P<arg>.*)\))?$", re.S)
_OPERATORS = re.compile(r"[;&|<>`$()\n]")


def _q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _word(w):
    """A word as the policy language takes it: bare when it can be."""
    return w if re.fullmatch(r"\$?[A-Za-z0-9_.+:@%/~=?*-]+", w) and not w.startswith("-") else _q(w)


def _command_match(spec):
    """A Bash rule's command (`git diff:*`, `npm run build`, `ls *`) as a
    program match, and a note when vetter's is broader; None and why when
    it can't be said."""
    prefix = spec.endswith(":*")
    cmd = spec[:-2] if prefix else spec
    cmd = cmd.strip()
    if cmd.endswith(" *"):
        cmd, prefix = cmd[:-2].rstrip(), True
    if not cmd or cmd == "*":
        return "any", None
    if _OPERATORS.search(cmd):
        return None, "a command with shell operators: vetter decides each part of a command on its own"
    words = cmd.split()
    if any("*" in w for w in words):
        return None, "a wildcard inside the command"
    names = []
    for w in words:
        if w.startswith("-"):
            break
        names.append(w)
    rest = words[len(names):]
    # (its options: each must be there, as in the agent's prefix)
    options = [w for w in rest if w.startswith("-") and re.fullmatch(r"-[A-Za-z0-9_=-]*", w)]
    note = None
    if len(options) < len(rest):
        note = "the words after its options left out: vetter matches a program by name, subcommands and options"
    elif not prefix:
        note = "with more arguments too: vetter matches a program by name, subcommands and options"
    withs = "".join(f" with {o}" for o in options)
    if "/" in names[0] or "\\" in names[0]:
        path = names[0]
        if path.startswith("./"):
            path = "$project/" + path[2:]
        return f"run exactly {_word(path)}", note
    return " ".join(_word(n) for n in names) + withs, note


def _place(path):
    """A Read/Edit rule's path (gitignore-style, as Claude Code reads it) as
    a place: ./x and /x from the project, //x absolute, ~/x home."""
    if path.startswith("//"):
        p = path[1:]
    elif path.startswith("~/") or path == "~":
        p = path
    elif path.startswith("/"):
        p = "$project" + path
    elif path.startswith("./"):
        p = "$project/" + path[2:]
    else:
        p = "$project/" + path
    p = p.replace("/**/", "/*/").removesuffix("/**").removesuffix("/*") or p
    return _word(p)


def _claude_rule(decision, entry):
    m = _ENTRY.match(entry.strip())
    if not m:
        return None, f"not a permission rule vetter reads: {entry}"
    tool, arg = m["tool"], m["arg"]
    reason = _q(f"claude: {entry}")
    if tool in ("Bash", "PowerShell"):
        match, note = _command_match(arg or "*")
        if match is None:
            return None, f"{entry}: {note}"
        rule = f"{decision} {reason} {match}"
        return rule + (f"   # ({note})" if note else ""), None
    if tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        verb = "read" if tool == "Read" else "write"
        if not arg:
            return f"{decision} {reason} {verb}", None
        return f"{decision} {reason} {verb} in {_place(arg)}", None
    if tool == "WebFetch":
        if arg and arg.startswith("domain:"):
            # (a domain the agent may fetch from: the same for commands)
            return f"{decision} {reason} download from {_word(arg[7:])}", None
        return None, f"{entry}: WebFetch without a domain"
    return None, f"{entry}: not a shell or file rule (vetter vets commands)"


def from_claude(settings, where="~/.claude/settings.json", today=None):
    perms = (settings or {}).get("permissions") or {}
    lines = _header("Claude Code", where, today)
    skipped = []
    for decision in ("deny", "ask", "allow"):
        entries = perms.get(decision) or []
        if entries:
            lines.append(f"\n# {decision}")
        for e in entries:
            rule, why = _claude_rule(decision, e)
            if rule is not None:
                lines.append(rule)
            else:
                skipped.append(why)
    return _footer(lines, skipped)


# ----------------------------------------------------------------------
# Codex: execpolicy's prefix_rule(...) in ~/.codex/rules/*.rules
# ----------------------------------------------------------------------

_CODEX_DECISIONS = {"allow": "allow", "prompt": "ask", "forbidden": "deny"}


def _codex_rules(source, name):
    """The prefix_rule calls of a .rules file (Starlark, read as Python's
    syntax: literals only)."""
    out, skipped = [], []
    try:
        tree = ast.parse(source, name)
    except SyntaxError as e:
        return [], [f"{name}: not read ({e.msg}, line {e.lineno})"]
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "prefix_rule"):
            continue
        try:
            kw = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
        except ValueError:
            skipped.append(f"{name}:{node.lineno}: a prefix_rule with values that aren't literals")
            continue
        pattern = kw.get("pattern")
        if not pattern and node.args:
            pattern = ast.literal_eval(node.args[0])
        out.append((node.lineno, pattern, kw.get("decision", "allow"), kw.get("justification")))
    return out, skipped


def from_codex(files, where="~/.codex/rules", today=None):
    lines = _header("Codex", where, today)
    skipped = []
    for name, source in sorted(files.items()):
        rules, bad = _codex_rules(source, name)
        skipped += bad
        if rules:
            lines.append(f"\n# {name}")
        for lineno, pattern, decision, why in rules:
            d = _CODEX_DECISIONS.get(decision)
            if d is None or not isinstance(pattern, (list, tuple)) or not pattern:
                skipped.append(f"{name}:{lineno}: a rule vetter doesn't read ({decision!r}, {pattern!r})")
                continue
            levels = []
            withs = []
            note = None
            for token in pattern:
                alts = token if isinstance(token, (list, tuple)) else [token]
                if any(not isinstance(a, str) for a in alts):
                    note = "a pattern vetter doesn't read whole"
                    break
                if any(a.startswith("-") for a in alts):
                    if all(re.fullmatch(r"-[A-Za-z0-9_=-]*", a) for a in alts):
                        # (alternatives: any of them; each token: all)
                        withs.append(" with " + ", ".join(alts))
                        continue
                    note = "a pattern vetter doesn't read whole"
                    break
                if withs:
                    note = "the words after its options left out: vetter matches a program by name, subcommands " \
                           "and options"
                    break
                levels.append(", ".join(_word(a) for a in alts))
            if not levels:
                skipped.append(f"{name}:{lineno}: {pattern!r}: no program name")
                continue
            reason = _q(f"codex: {why}" if why else f"codex: {' '.join(map(str, pattern))}")
            lines.append(f"{d} {reason} " + " ".join(levels) + "".join(withs) + (f"   # ({note})" if note else ""))
    return _footer(lines, skipped)


# ----------------------------------------------------------------------


def _header(agent, where, today):
    today = today or datetime.date.today().isoformat()
    return [
        "policy imported",
        f"# {agent}'s permission rules from {where} ({today}), by `vetter import`.",
        "# They come first; the stock policy's denies come before everything",
        "# (what they forbid stays forbidden), its other rules decide the rest.",
    ]


def _footer(lines, skipped):
    lines.append("\nuse stock")
    if skipped:
        lines.append("\n# Not imported:")
        lines += [f"#   {s}" for s in skipped]
    return "\n".join(lines) + "\n"


def read_claude(path):
    with open(path) as f:
        return json.load(f)
