"""The policy language (docs/05-policy-language.md): a policy loaded from
its text (rt.parse with the language's grammar, policy.zgram; the prelude
and `use`d policies built in), and decided: each part of a command's
resolution, each of its actions down the rules, the first that matches
deciding; the command's decision the strictest part's.

    p = load(rt, text, "mine.vet")
    add_project(rt, p, project_text, ".vetter.vet")
    d = decide(p, resolution, project, home, temp)

A policy with errors (checks.py's: a place no list names, a $var vetter
doesn't know, a list defined twice) doesn't load, in the hook as in the CLI;
checks.py's warnings are the CLI's (`vetter lint`).
"""

import pathlib
from dataclasses import dataclass, field

import zgram

from .. import paths
from ..glob import match as fnmatch
from ..shells.bash.syntax import nodes_of, offset
from ..specs import SPECS, is_space, project_dirs, strip
from ..shells.bash.expand import field_known, field_static, field_text
from .actions import Action, action_text, defines, looked_up, parts
from ..paths import fold

HERE = pathlib.Path(__file__).resolve().parent
POLICIES = HERE / "builtin"
GRAMMAR = (HERE / "policy.zgram").read_text(encoding="utf-8")
POLICY = zgram.compile(GRAMMAR)

# (the built-in policies, by name: their text and the file they're from)
BUILTIN = {path.stem: (path.read_text(), str(path)) for path in sorted(POLICIES.glob("*.vet"))}

# Where a policy's tests run: (the project, the home)
TEST_PLACES = {"posix": ("/home/user/project", "/home/user"),
               "windows": ("C:/Users/user/project", "C:/Users/user")}

ORDER = {"allow": 0, "ask": 1, "deny": 2}
FILE_VERBS = ("read", "write", "delete")
BY = {"rule": 2, "unknown": 1, "default": 0, "nothing": 0}


@dataclass
class Rule:
    decision: str
    reason: str
    file: str
    line: int
    matches: list
    text: str
    # (a deny from a used policy: before every rule of the policy using it)
    locked: bool


def where(rule):
    return paths_basename(rule.file) + ":" + str(rule.line)


def paths_basename(f):
    i = len(f)
    while i > 0 and f[i - 1] != "/" and f[i - 1] != "\\":
        i -= 1
    return f[i:]


@dataclass
class Match:
    """item, producer (None: none): ("any",), ("program", levels, keys:
    their (case key, is a pattern)), ("action", verb, obj); clauses:
    (unless / with, conditions)."""

    item: tuple
    producer: object
    clauses: list


@dataclass
class Policy:
    filename: str
    default: str
    unknown: str
    log: bool
    lets: dict
    rules: list
    # (a decision's steps say why each rule didn't match: `vetter why`'s;
    # off, only the matching one's reason is made)
    trace: bool = False
    # (its tests: (expected decision, command, file, line, shell))
    tests: list = field(default_factory=list)
    # (a project's allow rules left out: places.load_policy's)
    ignored: object = None
    # (paths followed through this machine's symbolic links before they're
    # matched: places.load_policy's, deciding here)
    follow_links: bool = False
    # (what the agent's earlier commands wrote: {path: "generated" or
    # "downloaded"}, agents/written.py's; run, its kind)
    written: dict = field(default_factory=dict)


@dataclass
class Step:
    """A rule tried on a part: did it match, and why."""

    rule: object
    matched: bool
    why: str


@dataclass
class ActionDecision:
    action: object
    decision: str
    rule: object
    reason: str
    by: str
    steps: list


@dataclass
class PartDecision:
    part: object
    decision: str
    rule: object
    reason: str
    by: str
    actions: list


@dataclass
class Decision:
    decision: str
    rule: object
    reason: str
    span: tuple
    by: str
    parts: list


def policy_error(message):
    return ValueError("policy: " + message)


def unquote(node):
    t = node.text
    if not t.startswith('"'):
        return t
    out = ""
    i = 1
    while i < len(t) - 1:
        if t[i] == "\\":
            out += t[i + 1]
            i += 2
        else:
            out += t[i]
            i += 1
    return out


def names_of(node):
    out = []
    for c in node.children:
        if c.rule == "string" or c.rule == "word" or c.rule == "pword":
            out.append(unquote(c))
    return out


def split_ws(s):
    out = []
    w = ""
    for c in s:
        if is_space(c):
            if w != "":
                out.append(w)
            w = ""
        else:
            w += c
    if w != "":
        out.append(w)
    return out


def load_text(rt, p, text, filename, seen):
    try:
        tree = rt.parse(POLICY, text)
    except zgram.ParseError as e:
        raise policy_error(filename + ": " + str(e))
    for stmt in tree.children:
        rule = stmt.rule
        line = text.count("\n", 0, offset(text, stmt)) + 1
        if rule == "setting":
            words = split_ws(stmt.text)
            if words[0] == "log":
                p.log = words[1] == "on"
            elif words[0] == "default":
                p.default = words[1]
            else:
                p.unknown = words[1]
        elif rule == "let":
            name = nodes_of(stmt, "ident", [])[0].text
            p.lets[name] = names_of(nodes_of(stmt, "places", [])[0])
        elif rule == "use":
            name = nodes_of(stmt, "ident", [])[0].text
            if name in seen:
                raise policy_error(filename + ":" + str(line) + ": use " + name + ": it uses itself")
            if name not in BUILTIN:
                raise policy_error(filename + ":" + str(line) + ": use " + name + ": there's no policy " + name)
            before = len(p.rules)
            used = BUILTIN[name]
            load_text(rt, p, used[0], used[1], seen + (name,))
            for r in p.rules[before:]:
                if r.decision == "deny":
                    r.locked = True
        elif rule == "drop":
            # (a used policy's rule taken out, by its reason: the only way
            # to undo a deny you didn't write)
            reason = unquote(nodes_of(stmt, "string", [])[0])
            kept = [r for r in p.rules if r.reason != reason]
            if len(kept) == len(p.rules):
                raise policy_error(filename + ":" + str(line) + ": drop " + repr(reason) + ": no rule before has that reason")
            p.rules = kept
        elif rule == "tests":
            for t in stmt.children:
                if t.rule == "tline":
                    # (the line of its decision: blank lines before it skipped)
                    decision = nodes_of(t, "decision", [])[0]
                    tline = text.count("\n", 0, offset(text, decision)) + 1
                    tags = nodes_of(t, "shell_tag", [])
                    shell = tags[0].text[1:len(tags[0].text) - 1] if len(tags) > 0 else "bash"
                    command = nodes_of(t, "rest", [])[0].text.rstrip()
                    p.tests.append((decision.text, command, filename, tline, "powershell" if shell == "ps" else shell))
        elif rule == "rule":
            p.rules.append(make_rule(p, stmt, filename, line))
    return tree


def make_rule(p, node, filename, line):
    decision = nodes_of(node, "decision", [])[0].text
    reason = None
    for c in node.children:
        if c.rule == "string":
            reason = unquote(c)
            break
    matches = []
    for c in node.children:
        if c.rule == "match":
            matches.append(make_match(p, c))
        elif c.rule == "block":
            for m in c.children:
                if m.rule == "match":
                    matches.append(make_match(p, m))
    body = node.text.partition("\n")[0]
    while len(body) > 0 and (body[len(body) - 1] == " " or body[len(body) - 1] == "{"):
        body = body[: len(body) - 1]
    if reason is None:
        # (no reason given: the rule's own words)
        reason = body
        if " " in body:
            reason = split_first(body)
    return Rule(decision, reason, filename, line, matches, body, False)


def split_first(body):
    """body.split(None, 1)[1]"""
    i = 0
    while i < len(body) and is_space(body[i]):
        i += 1
    while i < len(body) and not is_space(body[i]):
        i += 1
    while i < len(body) and is_space(body[i]):
        i += 1
    return body[i:]


def make_match(p, node):
    items = []
    for c in node.children:
        if c.rule == "any" or c.rule == "action" or c.rule == "program":
            items.append(c)
    m = Match(make_item(p, items[len(items) - 1]), None, [])
    if len(items) == 2:
        m.producer = make_item(p, items[0])
    for c in node.children:
        if c.rule == "unless" or c.rule == "with":
            m.clauses.append((c.rule, [make_cond(p, k) for k in c.children]))
    return m


def make_item(p, node):
    r = node.rule
    if r == "any":
        return ("any",)
    if r == "program":
        levels = []
        for lv in node.children:
            if lv.rule == "level":
                levels.append(expand(p, names_of(lv)))
        # (each name as it's compared, made once: its case key, and whether
        # it's a pattern or only equal to one name)
        keys = [[(paths.case_key(n), has_wildcard(n)) for n in names] for names in levels]
        return ("program", levels, keys)
    verb = nodes_of(node, "verb", [])[0].text
    kinds = [c for c in node.children if c.rule == "runkind"]
    if len(kinds) > 0:
        # (run KIND [in PLACES])
        where_ = None
        for c in node.children:
            if c.rule == "inside":
                where_ = expand(p, names_of(nodes_of(c, "places", [])[0]))
                break
        return ("action", verb, ("kind", kinds[0].text, where_))
    obj = None
    for c in node.children:
        cr = c.rule
        if cr == "exactly" or cr == "inside" or cr == "outside" or cr == "from" or cr == "to":
            obj = (cr, expand(p, names_of(nodes_of(c, "places", [])[0])))
        elif cr == "bare_places":
            obj = ("inside", expand(p, names_of(nodes_of(c, "places", [])[0])))
    return ("action", verb, obj)


def make_cond(p, node):
    r = node.rule
    if r == "flag":
        return ("flag", node.text)
    if r == "dynamic":
        return ("dynamic",)
    if r == "via":
        return ("via", expand(p, [unquote(nodes_of(node, "level1", [])[0])]))
    found = nodes_of(node, "places", [])
    vals = []
    if len(found) > 0:
        vals = names_of(found[0])
    else:
        for c in node.children:
            if c.rule == "string" or c.rule == "pword":
                vals.append(unquote(c))
    kind = "host" if r == "host" else ("inside" if r == "inside1" else ("outside" if r == "outside1" else "exactly"))
    return (kind, expand(p, vals))


def expand(p, names):
    """Names with the lists among them put in, braces expanded."""
    out = []
    for n in names:
        if n in p.lets:
            out += expand(p, p.lets[n])
        else:
            out += braces(n)
    return out


def braces(s):
    """re.search(r"\\{([^{}]*)\\}", s): its alternatives, each expanded."""
    i = 0
    while i < len(s):
        if s[i] == "{":
            j = i + 1
            while j < len(s) and s[j] != "{" and s[j] != "}":
                j += 1
            if j < len(s) and s[j] == "}":
                out = []
                for alt in s[i + 1 : j].split(","):
                    out += braces(s[:i] + strip(alt) + s[j + 1 :])
                return out
        i += 1
    return [s]


# What stops a policy loading: checks.py's errors (`vetter lint`'s), here
# for the hook too

# (the places vetter knows when it decides)
PLACE_VARS = ["$home", "$project", "$temp"]
# (where a place word is used: what checks.py's scopes look at)
PLACE_PARENTS = ["places", "inside1", "outside1", "exactly1"]


def is_builtin(filename):
    for k in BUILTIN:
        if BUILTIN[k][1] == filename:
            return True
    return False


def pathy(t):
    """re.search(r"[/\\\\~*?\\[{.:]", t): a path, a glob, ~, a drive"""
    for c in t:
        if c in "/\\~*?[{.:":
            return True
    return False


def distance(a, b):
    """Edits from a to b, a swap of two neighbours one edit (gti: git)."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (1 if a[i - 1] != b[j - 1] else 0))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def close(word, candidates):
    """The candidate a typo of `word` most likely meant: one edit away (two
    for long words), the same length first (checks.py's _close)."""
    limit = 1 if len(word) < 8 else 2
    best = None
    best_key = (0, 0, 0)
    for c in candidates:
        if abs(len(c) - len(word)) > limit:
            continue
        d = distance(word.lower(), c.lower())
        if 0 < d <= limit:
            key = (d, 1 if len(c) != len(word) else 0, 0 if c in SPECS else 1)
            if best is None or key < best_key or (key == best_key and c < best):
                best = c
                best_key = key
    return best


def place_error(t, known):
    """What's wrong with a place word no list has that name (None: it's a
    path)."""
    hint = close(t, known + PLACE_VARS)
    return t + " isn't a place or a list (let " + t + " = ...)" + (": did you mean " + hint + "?" if hint is not None else "")


def head_error(t):
    """$var, `project`: what's wrong with a place word's first part."""
    i = 0
    while i < len(t) and t[i] != "/" and t[i] != "\\":
        i += 1
    head = t[:i]
    if head.startswith("$") and head not in PLACE_VARS:
        hint = close(head, PLACE_VARS)
        if hint is None:
            for v in PLACE_VARS:
                if v.startswith(head):
                    hint = v
                    break
        return (head + " isn't one of vetter's places (" + ", ".join(PLACE_VARS) + ")"
                + (": did you mean " + hint + "?" if hint is not None else ""))
    if head == "project" or head == "home" or head == "temp":
        # (a folder named project, here: almost surely not meant)
        return (head + " here is a folder named " + head + ": did you mean $" + head + "? (./" + head
                + " for a folder of that name)")
    return None


def where_in(text, node):
    """line:column of a node (1-based)"""
    at = offset(text, node)
    line = text.count("\n", 0, at) + 1
    return str(line) + ":" + str(at - text.rfind("\n", 0, at)) + ": "


def check_places(text, node, parent, in_let, known, defined, name, out):
    """The place words under node used as places, checked: each in order."""
    if node.rule == "pword":
        t = node.text
        if parent in PLACE_PARENTS and t not in known and t not in defined and t not in PLACE_VARS:
            message = head_error(t)
            if message is None and not in_let and not pathy(t):
                message = place_error(t, known + defined)
            if message is not None:
                out.append(name + ":" + where_in(text, node) + message)
        return
    for c in node.children:
        check_places(text, c, node.rule, in_let or node.rule == "let", known, defined, name, out)


def lint_errors(text, tree, filename, known):
    """checks.py's errors in a policy's text: places no list names, $vars
    vetter doesn't know, a list defined twice. `known`: the lists defined
    elsewhere (the prelude's, the used policies')."""
    name = paths_basename(filename)
    defined = []
    out = []
    for stmt in tree.children:
        ident = None
        if stmt.rule == "let":
            ident = nodes_of(stmt, "ident", [])[0]
            if ident.text in defined:
                out.append(name + ":" + where_in(text, ident) + "'" + ident.text + "' is already defined")
        check_places(text, stmt, "policy", False, known, defined, name, out)
        if ident is not None and ident.text not in defined:
            defined.append(ident.text)
    return out


def own_lets(tree):
    out = []
    for stmt in tree.children:
        if stmt.rule == "let":
            out.append(nodes_of(stmt, "ident", [])[0].text)
    return out


def lint(p, text, tree, filename):
    """A ValueError (the CLI's PolicyError) if a policy's text, loaded into
    p, has errors."""
    mine = own_lets(tree)
    errors = lint_errors(text, tree, filename, [k for k in p.lets if k not in mine])
    if len(errors) > 0:
        raise policy_error("\n".join(errors))


def load(rt, text, filename):
    """A policy from its text, with the prelude's names."""
    p = Policy(filename, "ask", "ask", True, {}, [])
    prelude = BUILTIN["prelude"]
    load_text(rt, p, prelude[0], prelude[1], ())
    tree = load_text(rt, p, text, filename, ())
    if not is_builtin(filename):
        lint(p, text, tree, filename)
    # (a used policy's denies can't be hidden by rules written before the
    # `use`: they go first; only `drop` takes one out)
    p.rules = [r for r in p.rules if r.locked] + [r for r in p.rules if not r.locked]
    return p


def add_project(rt, p, text, filename):
    """A project's own rules (`.vetter.vet`): only deny and ask, first. Its
    allow rules are left out (the agent can write that file): returned, to
    be reported."""
    project = Policy(filename, "ask", "ask", True, {k: v for k, v in p.lets.items()}, [])
    tree = load_text(rt, project, text, filename, ())
    errors = lint_errors(text, tree, filename, [k for k in p.lets])
    if len(errors) > 0:
        raise policy_error("\n".join(errors))
    denies = [r for r in project.rules if r.decision == "deny"]
    asks = [r for r in project.rules if r.decision == "ask"]
    locked = [r for r in p.rules if r.locked]
    p.rules = denies + locked + asks + [r for r in p.rules if not r.locked]
    p.tests += project.tests
    return [r for r in project.rules if r.decision == "allow"]


def test_decision(rt, p, command, shell):
    """A test's command decided, in the tests' places (a Windows project for
    PowerShell and cmd)."""
    from ..check import check
    from ..places import project_root

    places = TEST_PLACES["windows" if shell == "powershell" or shell == "cmd" else "posix"]
    return check(rt, p, command, shell, places[0], places[1], project_root(places[0], places[1]), None)


def run_tests(rt, p):
    """The tests that fail: (file, line, command, expected, Decision)."""
    failures = []
    for expected, command, filename, line, shell in p.tests:
        d = test_decision(rt, p, command, shell)
        if d.decision != expected:
            failures.append((filename, line, command, expected, d))
    return failures


def coverage(rt, p):
    """The rules no test reaches (they decide nothing in any test)."""
    used = set()
    for _, command, _, _, shell in p.tests:
        d = test_decision(rt, p, command, shell)
        for part in d.parts:
            for a in part.actions:
                if a.rule is not None:
                    used.add((a.rule.file, a.rule.line))
    return [r for r in p.rules if (r.file, r.line) not in used]


def unreachable(p):
    """Rules an earlier one always decides before: (rule, the earlier one).
    Certain cases only: what's reported is never reached."""
    out = []
    for k in range(len(p.rules)):
        b = p.rules[k]
        for a in p.rules[:k]:
            every = True
            for mb in b.matches:
                one = False
                for ma in a.matches:
                    if not one and covers(ma, mb):
                        one = True
                if not one:
                    every = False
            if every:
                out.append((b, a))
                break
    return out


def covers(a, b):
    """Does match a hold whenever match b does? (False when not sure.)"""
    if len(a.clauses) > 0 and a.clauses != b.clauses:
        return False
    if a.producer is not None and (b.producer is None or not item_covers(a.producer, b.producer)):
        return False
    return item_covers(a.item, b.item)


def item_covers(a, b):
    if a[0] == "any":
        return True
    if a[0] != b[0]:
        return False
    if a[0] == "program":
        la = a[1]
        lb = b[1]
        if len(la) > len(lb):
            return False
        for k in range(len(la)):
            for n in lb[k]:
                if not matches_one(n, la[k]):
                    return False
        return True
    va = a[1]
    oa = a[2]
    vb = b[1]
    ob = b[2]
    if not (va == vb or (va == "network" and (vb == "download" or vb == "send"))):
        return False
    if oa is None:
        return True
    if ob is None or oa[0] != ob[0]:
        return False
    if oa[0] == "kind":
        return oa[1] == ob[1] and (oa[2] is None or (ob[2] is not None and places_cover(oa[2], ob[2])))
    if oa[0] == "inside":
        return places_cover(oa[1], ob[1])
    if oa[0] == "from" or oa[0] == "to":
        for h in ob[1]:
            if not matches_one(h, oa[1]):
                return False
        return True
    return sorted(oa[1]) == sorted(ob[1])


def matches_one(name, patterns):
    for p in patterns:
        if fnmatch(name, p):
            return True
    return False


def places_cover(pa, pb):
    # (places resolved for comparing rules: no machine's)
    dummy = Places("/P", "/H", ["/T"], False, {}, {})
    ra = [resolve_place(dummy, p) for p in pa]
    for q in pb:
        rq = resolve_place(dummy, q)
        one = False
        for p in ra:
            if not one and in_place(rq, p):
                one = True
        if not one:
            return False
    return True


@dataclass
class Places:
    project: object
    home: object
    temp: list
    # (why a rule didn't match said: Policy.trace)
    trace: bool
    # (each place of the rules resolved once, for the decision)
    resolved: dict
    # (each name's case key, made once: name_key)
    keys: dict
    # (the rule being matched allows; its unless clause being matched)
    allowing: bool = False
    blocking: bool = False


def temp_dirs(home):
    out = ["/tmp", "/var/tmp", "/private/tmp", "C:/Windows/Temp"]
    if home is not None and home != "":
        out.append(paths.norm(home + "/AppData/Local/Temp"))
    return out


def resolve_all(pl, place):
    """A place's absolute paths or patterns: $temp is several."""
    got = pl.resolved.get(place)
    if got is not None:
        return got
    if place == "$temp" or place.startswith("$temp/"):
        got = [paths.norm(t + place[5:]) for t in pl.temp]
    else:
        got = [resolve_place(pl, place)]
    pl.resolved[place] = got
    return got


def resolve_place(pl, place):
    """A place's absolute path or pattern (None: not known here)."""
    for var, value in (("$project", pl.project), ("$home", pl.home), ("~", pl.home)):
        if place == var or place.startswith(var + "/"):
            return None if value is None else paths.norm(value + place[len(var) :])
    if paths.is_abs(place):
        return place if place == "/" else paths.norm(place)
    return None if pl.project is None else paths.join(pl.project, place)


def has_wildcard(s):
    return "*" in s or "?" in s or "[" in s


def rstrip_slash(s):
    while s.endswith("/"):
        s = s[: len(s) - 1]
    return s


def in_place(path, place):
    if path is None or place is None:
        return False
    if has_wildcard(place):
        if paths.is_windows(path):
            path = paths.case_key(path)
            place = paths.case_key(place)
        return fnmatch(path, place) or fnmatch(path, rstrip_slash(place) + "/*")
    return paths.inside(path, place)


def same(path, place):
    """Exactly the place; `/` is a Windows drive's root too."""
    if place == "/" and len(path) == 3 and path[1:] == ":/" and ((path[0] >= "A" and path[0] <= "Z")
                                                                 or (path[0] >= "a" and path[0] <= "z")):
        return True
    return paths.same(path, place)


def show(places):
    return ", ".join(places[:4]) + (", ..." if len(places) > 4 else "")


def host_ok(host, patterns):
    if host is None:
        return False
    for pat in patterns:
        if fnmatch(host, pat):
            return True
    return False


@dataclass
class Why:
    ok: bool
    why: str


def match_item(pl, item, part, act):
    """act None: the part as a whole (what's piped into a command)."""
    kind = item[0]
    if kind == "any":
        return Why(True, "anything")
    if kind == "program":
        return match_program(pl, item[1], item[2], part)
    verb = item[1]
    obj = item[2]
    if act is None:
        # (does the part do it at all)
        for a in part.actions:
            w = match_action(pl, verb, obj, a)
            if w.ok:
                return w
        return Why(False, "doesn't " + verb + (" " + obj_text(obj) if obj is not None else "") if pl.trace else "")
    return match_action(pl, verb, obj, act)


def positional_text(part, n):
    out = []
    for x in part.positional[:n]:
        out.append(x if x is not None and x != "" else "?")
    return " ".join(out)


def name_key(pl, name):
    """A name's case key, made once for the decision"""
    k = pl.keys.get(name)
    if k is None:
        k = paths.case_key(name)
        pl.keys[name] = k
    return k


def key_matches(key, k):
    """A name's case key against a rule's name (key, is_pattern)"""
    return fnmatch(key, k[0]) if k[1] else key == k[0]


def match_program(pl, levels, keys, part):
    if part.name is None:
        return Why(False, "its program isn't known")
    # (names ignore case: Windows and PowerShell do)
    key = name_key(pl, part.name)
    hit = False
    for k in keys[0]:
        if not hit and key_matches(key, k):
            hit = True
    if not hit:
        return Why(False, "not " + show(levels[0]) if pl.trace else "")
    for k in range(len(levels) - 1):
        alts = levels[k + 1]
        got = part.positional[k] if k < len(part.positional) else None
        ok = False
        if got is not None:
            got_key = name_key(pl, got)
            for a in keys[k + 1]:
                if not ok and key_matches(got_key, a):
                    ok = True
        if not ok:
            if not pl.trace:
                return Why(False, "")
            said = positional_text(part, k + 1)
            if said == "":
                said = "(nothing)"
            return Why(False, part.name + " " + said + " isn't " + part.name + " " + show(alts))
    return Why(True, strip(part.name + " " + positional_text(part, len(levels) - 1)))


def obj_text(obj):
    if obj[0] == "kind":
        return obj[1] + (" in " + show(obj[2]) if obj[2] is not None and len(obj[2]) > 0 else "")
    word = "in" if obj[0] == "inside" else obj[0]
    return word + " " + show(obj[1])


def nonempty(x):
    return x is not None and x != ""


def match_action(pl, verb, obj, a):
    # (network: talking to a host in any way)
    if a.verb != verb and not (verb == "network" and (a.verb == "download" or a.verb == "send")):
        return Why(False, "it's " + a.verb + ", not " + verb if pl.trace else "")
    if verb == "run":
        if obj is not None and obj[0] == "kind":
            if a.kind != obj[1]:
                return Why(False, "it runs " + (a.kind if nonempty(a.kind) else "a program") + ", not " + obj[1]
                           if pl.trace else "")
            if obj[2] is None:
                return Why(True, "runs " + a.text)
            return match_path(pl, a, "inside", obj[2])
        # (run PLACES: a program or a script found there, the command's own
        # too)
        # (a folder a tool works on, written or not: not a program found in
        # a place, `run in $temp`)
        if a.kind is not None and not ((a.kind == "script" or a.kind == "generated") and obj is not None
                                       and not a.folder):
            return Why(False, "it runs " + a.kind + ", not a program" if pl.trace else "")
    if obj is None:
        return Why(True, verb + " " + (a.path if nonempty(a.path) else (a.host if nonempty(a.host) else a.text)))
    if obj[0] == "from" or obj[0] == "to":
        if host_ok(a.host, obj[1]):
            return Why(True, a.host + " is " + show(obj[1]))
        return Why(False, (a.host if nonempty(a.host) else a.text + " (only running tells)") + " isn't " + show(obj[1])
                   if pl.trace else "")
    return match_path(pl, a, obj[0], obj[1])


def match_path(pl, a, rel, places):
    word = "in" if rel == "inside" else rel
    if a.path is None and a.verb == "run" and a.kind is None:
        ok = rel == "outside"
        return Why(ok, a.text + " is found on PATH, not named by a path" if ok or pl.trace else "")
    if a.path is None:
        where_ = a.text + " (only running tells)" if nonempty(a.text) else "a path only running tells"
        # (unknown: inside nothing; outside only to keep an allow from
        # applying (`unless outside $project`): a rule doesn't deny what
        # it can't tell, the action is asked)
        if rel == "outside" and pl.blocking:
            return Why(True, where_ + ": can't be shown in " + show(places))
        return Why(False, where_ + " isn't known to be " + word + " " + show(places) if pl.trace else "")
    # (the first place it's in, or is, decides: no need to look further)
    hit = False
    for q in places:
        for r in resolve_all(pl, q):
            if not hit:
                hit = (r is not None and same(a.path, r)) if rel == "exactly" else in_place(a.path, r)
    ok = not hit if rel == "outside" else hit
    return Why(ok, a.path + " " + ("is" if ok else "isn't") + " " + word + " " + show(places) if ok or pl.trace else "")


def first_word(s):
    i = 0
    while i < len(s) and is_space(s[i]):
        i += 1
    j = i
    while j < len(s) and not is_space(s[j]):
        j += 1
    return s[i:j]


def match_cond(pl, c, part, act):
    kind = c[0]
    if kind == "flag":
        if c[1] in part.flags:
            return Why(True, c[1])
        if c[1].startswith("--"):
            # (git --del is --delete: GNU programs take a long option's
            # prefix; one that might be it, as if it is (with: the rule
            # applies; unless: its exception does, the stricter both ways))
            for f in part.flags:
                if f.startswith("--") and len(f) > 2 and c[1].startswith(f):
                    return Why(True, f + " (" + c[1] + ")")
        return Why(False, c[1])
    if kind == "dynamic":
        return Why(part.dynamic, "arguments only running tells")
    if kind == "via":
        hit = None
        for v in part.via:
            for n in c[1]:
                if hit is None and fnmatch(first_word(v), n):
                    hit = v
        return Why(hit is not None, "via " + (hit if hit is not None else show(c[1])))
    if kind == "host":
        hosts = [a.host for a in part.actions if a.verb == "network" or a.verb == "download" or a.verb == "send"]
        ok = len(hosts) > 0
        for h in hosts:
            if not host_ok(h, c[1]):
                ok = False
        return Why(ok, "host " + show(c[1]))
    # (in / outside / exactly: the action's path, else the paths the part
    # touches)
    resolved = []
    for q in c[1]:
        resolved += resolve_all(pl, q)
    touched = [x.path for x in part.actions if x.verb == "read" or x.verb == "write" or x.verb == "delete"
               or (x.verb == "run" and x.path is not None)]
    if act is not None and act.path is not None:
        touched = [act.path]
    if len(touched) == 0:
        return Why(False, kind + " " + show(c[1]))
    if kind == "exactly":
        ok = False
        for path in touched:
            for q in resolved:
                if path is not None and q is not None and same(path, q):
                    ok = True
        return Why(ok, "exactly " + show(c[1]))
    every = True
    for path in touched:
        hit = False
        for q in resolved:
            if in_place(path, q):
                hit = True
        if not hit:
            every = False
    if kind == "inside":
        return Why(every, "in " + show(c[1]))
    return Why(not every, "outside " + show(c[1]))


def match_rule(pl, m, part, act):
    w = match_item(pl, m.item, part, act)
    if not w.ok:
        return w
    why = w.why
    if m.producer is not None:
        prod = part.producer
        if prod is None:
            return Why(False, "nothing is piped into it")
        if not part.unknown and part.what.given:
            # (python -c CODE: what's piped in is data; code that runs it,
            # exec(sys.stdin.read()), os.system("sh"), is the code's)
            return Why(False, "it runs the program it's given, not what's piped into it" if pl.trace else "")
        # (what's piped in through others too: curl | tee log | sh)
        pw = match_item(pl, m.producer, prod, None)
        first = prod
        depth = 0
        while not pw.ok and prod.producer is not None and depth < 16:
            prod = prod.producer
            depth += 1
            pw = match_item(pl, m.producer, prod, None)
        if not pw.ok:
            return Why(False, "what's piped into it: " + pw.why if pl.trace else "")
        through = " | ... " if prod is not first else " | "
        why = (prod.name if nonempty(prod.name) else "?") + through + why
    for clause_kind, conds in m.clauses:
        pl.blocking = pl.allowing and clause_kind == "unless"
        results = [match_cond(pl, c, part, act) for c in conds]
        pl.blocking = False
        if clause_kind == "unless":
            for r in results:
                if r.ok:
                    return Why(False, why + ", but unless " + r.why if pl.trace else "")
        else:
            hit = None
            for r in results:
                if hit is None and r.ok:
                    hit = r.why
            if hit is None:
                return Why(False, why + ", but not with " + ", ".join([r.why for r in results]) if pl.trace else "")
            why += ", with " + hit
    return Why(True, why)


def rank_above(a, b):
    """a strictly above b: its decision stricter, or as strict and by a
    rule over an unknown over the default."""
    ra = ORDER[a.decision]
    rb = ORDER[b.decision]
    if ra != rb:
        return ra > rb
    return BY[a.by] > BY[b.by]


def followed(path, verb):
    """A path through this machine's symbolic links (what it is, where
    it's read or written: a link in the project to ~/.ssh is ~/.ssh); a
    deletion's directory only (deleting a link deletes it, not what it
    points to); another system's path as it is."""
    from os import name as os_name
    from os.path import realpath

    if path is None:
        return path
    windows = os_name == "nt"
    if paths.is_windows(path) != windows or not paths.is_abs(path):
        return path
    if verb == "delete":
        i = path.rfind("/")
        if i <= 0:
            return path
        return paths.norm(realpath(path[:i]) + "/" + path[i + 1:])
    return paths.norm(realpath(path))


# Programs that import a test tree's conftest.py (and pytest's config files)
PYTESTS = ("pytest", "py.test")
PYTEST_FILES = ("conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")


def machine_actions(p, part):
    """What a program does here that its command doesn't say, deciding on
    this machine: git running what its repository's own config names
    (core.fsmonitor=./w); pytest importing a conftest.py the agent wrote."""
    from ..gitconfig import dirname as git_dirname
    from ..gitconfig import git_dir, isfile, repo_config, runs_from
    from ..toolconfig import configured, virtualenv_activate

    if part.name is None or part.unknown:
        return []
    e = part.what
    cwd = e.cwd
    if cwd is None:
        return []
    out = []
    sub = ""
    for a in e.argv[1:]:
        s = field_static(a)
        if s is not None and not s.startswith("-") and not s.startswith("+"):
            sub = s
            break
    for r in e.roles:
        if r.role == "activate":
            # (. .venv/bin/activate, read as a virtualenv's: one that isn't
            # may go elsewhere, run more)
            where = paths.join(cwd, field_static(r.value)) if field_known(r.value) else None
            if where is None or not virtualenv_activate(where):
                out.append(Action("run", None, None, "configured", "sourced " + field_text(r.value)
                                  + ": not a virtualenv's activate, what it changes only running tells"))
    for path, setting in configured(part.name, sub, cwd):
        # (a program its config names: a file of code where it is, the
        # agent's if it wrote it; a setting otherwise, configured)
        if path is None:
            out.append(Action("run", None, None, "configured", "its config: " + setting))
        else:
            out.append(Action("run", path, None, "script", "its config: " + setting))
    for found in looked_up(part):
        # (git.cmd in the folder cmd runs git in: that runs, not PATH's)
        if isfile(found):
            out.append(Action("run", found, None, "configured", "cmd finds " + found + " before PATH's"))
    if part.name == "git":
        # (the repository's: where it runs, or -C's, --git-dir's)
        for d in project_dirs(e):
            where = paths.join(cwd, field_static(d)) if field_known(d) else None
            if where is None:
                continue
            g = git_dir(where)
            top = git_dirname(g) if g is not None and g.rstrip("/").endswith(".git") else where
            for setting in runs_from(repo_config(where)):
                key, _, value = setting.partition("=")
                value = value.strip().strip('"')
                if value != "" and " " not in value and "\t" not in value and not value.startswith("!") \
                        and (key == "core.hookspath" or "/" in value or "\\" in value):
                    # (core.hooksPath=.githooks, a program by its path: the
                    # scripts there, where they are)
                    out.append(Action("run", paths.join(top, value), None, "script",
                                      "the repository's git config: " + setting))
                else:
                    out.append(Action("run", None, None, "configured", "the repository's git config: " + setting))
    elif part.name in PYTESTS or ((part.name == "python" or part.name == "python3") and runs_pytest(e)):
        # (its conftest.py files: under where it runs, and in the folders
        # above it)
        here = cwd.rstrip("/") + "/"
        for path, kind in p.written.items():
            folder, _, leaf = path.rpartition("/")
            if leaf in PYTEST_FILES and (path.startswith(here) or here.startswith(folder + "/")):
                out.append(Action("run", path, None, kind, "pytest imports " + path))
    return out


def runs_pytest(e):
    """python -m pytest"""
    words = [field_static(a) for a in e.argv]
    for k in range(len(words) - 1):
        if words[k] == "-m" and words[k + 1] == "pytest":
            return True
    return False


def decide(p, resolution, project, home, temp):
    """`temp`: the temporary dirs ($temp); None: the usual ones."""
    pl = Places(project, home, temp_dirs(home) if temp is None else temp, p.trace, {}, {})
    results = []
    for part in parts(resolution, home):
        if p.follow_links:
            for a in part.actions:
                a.path = followed(a.path, a.verb)
        if p.follow_links:
            part.actions += machine_actions(p, part)
        for found in looked_up(part):
            # (git, after the agent wrote git.cmd where cmd looks first)
            for f, kind in p.written.items():
                if fold(f) == fold(found):
                    part.actions.append(Action("run", found, None, kind, "cmd finds " + found + " first"))
        for a in part.actions:
            # (written by an earlier command: as if by this one)
            plain = a.kind is None or a.kind == "script" or a.kind == "project-code"
            if a.verb == "run" and plain and a.path is not None and a.path in p.written and not a.folder:
                a.kind = p.written[a.path]
            elif a.verb == "run" and a.kind == "project-code" and a.path is not None:
                # (make after the agent wrote the Makefile: what it runs, the
                # agent's)
                for f, kind in p.written.items():
                    if defines(f, a.path, part.what.program if part.unknown else ""):
                        a.kind = kind
        if p.follow_links and part.unknown and part.what.kind == "repo_config" \
                and part.actions[0].kind == "project-code":
            # (git's repository config, read here: what it runs, the git
            # execution's actions (machine_actions); none, nothing unknown)
            continue
        decided = [decide_action(p, pl, part, a) for a in part.actions]
        run_by_effects(part, decided)
        # (the strictest; among equals, the action itself before "by what
        # it does": the first such)
        top = decided[0]
        for d in decided[1:]:
            if rank_above(d, top) or (not rank_above(top, d) and top.reason.startswith("by what it does")
                                      and not d.reason.startswith("by what it does")):
                top = d
        results.append(PartDecision(part, top.decision, top.rule, top.reason, top.by, decided))
    if len(results) == 0:
        return Decision("allow", None, "nothing runs", (0, 0), "nothing", results)
    top = results[0]
    for r in results[1:]:
        if rank_above(r, top):
            top = r
    return Decision(top.decision, top.rule, top.reason, top.part.span, top.by, results)


def decide_action(p, pl, part, act):
    steps = []
    for rule in p.rules:
        why = ""
        pl.allowing = rule.decision == "allow"
        for m in rule.matches:
            w = match_rule(pl, m, part, act)
            hidden = act.verb == "run" and act.kind is not None
            if w.ok and rule.decision == "allow" and m.item[0] == "program" \
                    and (act.verb in FILE_VERBS or hidden or act.inline):
                # (a program allowed by name: run; what it reads, writes and
                # deletes the places' rules decide: gcc -E /flag, read x < f;
                # what it runs that vetter can't see, the rules about that:
                # git's repository config naming core.fsmonitor)
                why = w.why + ", allowed to run, not what it " + act.verb + "s" if pl.trace else ""
                continue
            why = w.why
            if w.ok:
                steps.append(Step(rule, True, why))
                return ActionDecision(act, rule.decision, rule, rule.reason + ": " + why, "rule", steps)
        steps.append(Step(rule, False, why))
    # (a file only running tells: what it is vetter can't see, not a file
    # no rule names)
    hidden_file = act.verb in FILE_VERBS and act.path is None
    if act.kind is not None or part.name is None or hidden_file:
        seen = part.label if part.unknown else action_text(act)
        if not part.unknown and act.kind is not None and nonempty(act.text):
            # (what this machine said: its config's setting, as found)
            seen = act.verb + " " + act.kind + ": " + act.text
        return ActionDecision(act, p.unknown, None, "vetter can't see: " + seen, "unknown", steps)
    return ActionDecision(act, p.default, None, "no rule for " + action_text(act), "default", steps)


def run_by_effects(part, decided):
    """Running a program vetter knows (it has a spec, or it's a cmdlet) and
    no rule names: decided by what it does, its other actions."""
    known = (part.name is not None and part.name in SPECS) or part.cmdlet
    if part.name is None or not known:
        return
    others = [d for d in decided if d.action.verb != "run"]
    if len(others) == 0:
        return
    worst = others[0]
    for d in others[1:]:
        if rank_above(d, worst):
            worst = d
    for k in range(len(decided)):
        d = decided[k]
        if d.action.verb == "run" and d.action.kind is None and d.by == "default":
            decided[k] = ActionDecision(d.action, worst.decision, worst.rule,
                                        "by what it does (" + action_text(worst.action) + ")", worst.by, d.steps)
