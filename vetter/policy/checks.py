"""A policy's checks, with zrules: what loading it can't see by running it.

- names: a place that isn't a path, `project`, `home` or a `let` list is an
  error (a typo: `in buld` would match nothing); a program name close to a
  list's or a known program's is a warning (`allow gti status`);
- subcommands and flags vetter's specs know: one they don't, close to one
  they do, is a warning (`git pussh`, `unless --txtconv`);
- a `let` never used, two rules with the same reason (`drop` takes out
  both): warnings.

    errors, warnings = check(text, "mine.vet", known_lets={...})

Each is "file:line:column: message".
"""

import functools
import re

import zrules

from .. import specs

# (in a place: a path, a glob, ~, a drive, a pattern)
_PATHY = re.compile(r"[/\\~*?\[{.:]")
# (the places vetter knows when it decides: the agent's project, the home)
PLACE_VARS = {"$project", "$home", "$temp"}


@functools.cache
def _known_programs():
    """Every program name vetter knows something about."""
    from ..shells.bash.resolve import BUILTINS, CODE_BUILTINS
    from ..shells.cmd.resolve import INTERNAL
    from ..shells.powershell.cmdlets import ALIASES, CMDLETS

    names = set(specs.SPECS) | BUILTINS | CODE_BUILTINS | INTERNAL | set(ALIASES)
    names |= {c.name for c in CMDLETS.values()}
    return {n.lower(): n for n in names}


def _distance(a, b):
    """Edits from a to b, a swap of two neighbours one edit (gti: git)."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def _swapped(word, candidates):
    """The candidate that is `word` with two neighbouring letters swapped."""
    for k in range(len(word) - 1):
        w = word[:k] + word[k + 1] + word[k] + word[k + 2:]
        if w != word and w in candidates:
            return w
    return None


def _close(word, candidates):
    """The candidate a typo of `word` most likely meant: one edit away (two
    for long words), the same length first."""
    limit = 1 if len(word) < 8 else 2
    best = None
    for c in candidates:
        if abs(len(c) - len(word)) > limit:
            continue
        d = _distance(word.lower(), c.lower())
        if 0 < d <= limit:
            # (a program with a spec before an alias: gti is git, not gci)
            key = (d, len(c) != len(word), c not in specs.SPECS, c)
            if best is None or key < best[0]:
                best = (key, c)
    return best[1] if best else None


def _spec(name):
    return specs.SPECS.get(name) or specs.SPECS.get(name.lower())


def _flags(spec):
    out = set(spec.values) | set(spec.flags) | set(spec.roles)
    for s in spec.sub.values():
        out |= _flags(s)
    return out


def _program_names(program_node):
    """The program node's levels, as lists of words (strings unquoted)."""
    levels = []
    for lv in program_node:
        if lv.rule() == "level":
            levels.append([(w, w.text().strip('"')) for w in lv if w.rule() in ("word", "string")])
    return levels


def check(parser, text, filename, known_lets, lets_used_elsewhere=False):
    """(errors, warnings) of a policy's text. `known_lets`: the lists defined
    before it (the prelude's, the used policies'), always visible."""
    known_lets = set(known_lets)

    def unresolved(node, ctx):
        t = node.text().strip('"')
        parent = node.parent()
        prule = parent.rule() if parent is not None else ""
        head = re.split(r"[/\\]", t, maxsplit=1)[0]
        if head.startswith("$") and head not in PLACE_VARS:
            hint = _close(head, PLACE_VARS) or next((v for v in sorted(PLACE_VARS) if v.startswith(head)), None)
            ctx.error(node, f"{head} isn't one of vetter's places ({', '.join(sorted(PLACE_VARS))})"
                      + (f": did you mean {hint}?" if hint else ""), code="unknown-place")
            return True
        if head in ("project", "home", "temp") and node.rule() == "pword":
            # (a folder named project, here: almost surely not meant)
            ctx.error(node, f"{head} here is a folder named {head}: did you mean ${head}? (./{head} for a folder "
                      "of that name)", code="unknown-place")
            return True
        up = parent
        while up is not None:
            if up.rule() == "let":
                # (a list's items: programs or places, as where it's used says)
                return True
            up = up.parent()
        if prule in ("places", "inside1", "outside1", "exactly1", "host"):
            if _PATHY.search(t) or prule == "host":
                return True
            hint = _close(t, known_lets | PLACE_VARS)
            ctx.error(node, f"{t} isn't a place or a list (let {t} = ...)"
                      + (f": did you mean {hint}?" if hint else ""), code="unknown-place")
            return True
        # (a program, or a subcommand: the program check below)
        if prule == "level":
            first = next(c for c in parent.parent() if c.rule() == "level")
            is_first = first.index == parent.index
        else:
            is_first = prule == "level1"
        if is_first and t.lower() not in _known_programs() and not _PATHY.search(t):
            # (programs vetter doesn't know are many and fine: a list's name
            # mistyped, or two letters of a known one swapped, is a typo)
            hint = _close(t, known_lets) or _swapped(t, specs.SPECS)
            if hint is not None and hint != t:
                ctx.warning(node, f"{t}: not a list nor a program vetter knows: did you mean {hint}?",
                            code="unknown-program")
        return True

    def program(node, ctx):
        levels = _program_names(node)
        if len(levels) < 2:
            return
        for _, name in levels[0]:
            spec = _spec(name)
            if spec is None or not spec.commands:
                continue
            for w, sub in levels[1]:
                if sub in spec.commands or sub in known_lets or _PATHY.search(sub):
                    continue
                hint = _close(sub, spec.commands)
                ctx.warning(w, f"{name} has no subcommand {sub} that vetter knows"
                            + (f": did you mean {hint}?" if hint else " (an alias of yours: fine)"),
                            code="unknown-subcommand")

    def match(node, ctx):
        progs = [c for c in node if c.rule() == "program"]
        if not progs:
            return
        known = set()
        for _, name in _program_names(progs[-1])[0]:
            spec = _spec(name)
            if spec is not None:
                known |= _flags(spec)
        if not known:
            return
        for f in node.find("flag"):
            flag = f.text().split("=")[0]
            if flag in known:
                continue
            hint = _close(flag, known)
            if hint is not None:
                ctx.warning(f, f"{flag}: not an option vetter knows for it: did you mean {hint}?",
                            code="unknown-flag")

    rules = zrules.Rules(parser, [
        zrules.scopes(scope="policy", define="let > .name",
                      use="places > pword, inside1 > pword, outside1 > pword, exactly1 > pword, level > word, "
                          "level1 > word",
                      builtins=sorted(known_lets | PLACE_VARS), on_unresolved=unresolved,
                      on_unused="ignore" if lets_used_elsewhere else "warning",
                      on_redefine="error", messages={"unused": "let {text} is never used"}),
        zrules.unique("rule > string", within="policy", severity="warning",
                      message="another rule has the reason {text}: `drop` would take out both"),
        zrules.custom("program", program),
        zrules.custom("match", match),
    ])
    errors, warnings = [], []
    for d in rules.check(text):
        line = f"{filename}:{d.line}:{d.column}: {d.message}"
        (errors if d.severity == "error" else warnings).append(line)
    return errors, warnings
