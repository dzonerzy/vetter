"""The log of decided commands: only on this machine, secrets masked
before anything is written. `vetter replay` runs it through another
policy.

~/.local/state/vetter/log.jsonl (its directory mode 700, the file 600), the
last MAX_ENTRIES (older than MAX_DAYS dropped); one JSON object a line:
time, agent, cwd, command, decision, rule.

mask() hides what these regular expressions match, in this order (each
matched by hand as Python's re matches it: its \\b, \\s and \\w of all of
Unicode; re.I's letters, the dotless ı, İ, the long ſ and the Kelvin sign
K among them):

    \\b([A-Za-z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|PASS|AUTH|CREDENTIAL)[A-Za-z0-9_]*=)
        ('[^']*'|"[^"]*"|\\S+)                     re.I    \\1***
    (Authorization:\\s*)(?:(Bearer|Basic|token)\\s+)?[^'"\\s]+    re.I    \\1 \\2 ***
    \\b(Bearer)\\s+[A-Za-z0-9._~+/=-]+                          \\1 ***
    (\\s(?:-u|--user)[=\\s]+)([^:\\s'"]+):(\\S+)                  \\1\\2:***
    (://[^/\\s:@]+):[^@\\s/]+@                                   \\1:***@
    (--password[=\\s]+)\\S+                                      \\1***
    \\b(?:ghp|gho|ghu|ghs|ghr|github_pat|glpat|sk|xox[abprs])[-_][A-Za-z0-9_-]{10,}    ***
    \\bAKIA[0-9A-Z]{16}\\b                                       ***
    \\beyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+    ***
"""

from os import chmod, makedirs, replace
from os.path import exists, getsize
from time import time

import zgram

from ..jsontext import dumps, loads
from ..policy.language import where

MAX_ENTRIES = 10_000
MAX_DAYS = 30

KEYWORDS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASSWD", "PASS", "AUTH", "CREDENTIAL")
TOKEN_PREFIXES = ("ghp", "gho", "ghu", "ghs", "ghr", "github_pat", "glpat", "sk", "xoxa", "xoxb", "xoxp", "xoxr",
                  "xoxs")
# (\s: what Python's str.isspace() is)
SPACES = "\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0           " \
         "     　"
# (re.I: these match an ASCII letter too, as Python's [A-Za-z] and its
# letters do: ı, İ, ſ, K)
FOLDED = {"ı": "I", "İ": "I", "ſ": "S", "K": "K"}
JWT = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
BEARER = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~+/=-"
AWS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def is_space(c):
    return c in SPACES


def is_word(c):
    """\\w: alphanumeric (all of Unicode) or _"""
    return c == "_" or c.isalnum()


def name_char(c):
    """[A-Za-z0-9_] with re.I"""
    return c == "_" or ("0" <= c <= "9") or ("a" <= c <= "z") or ("A" <= c <= "Z") or c in FOLDED


def upper_folded(s):
    out = ""
    for c in s:
        out += FOLDED[c] if c in FOLDED else c.upper()
    return out


def boundary(s, i):
    """\\b before s[i], a word character"""
    return i == 0 or not is_word(s[i - 1])


def run_of(s, i, chars):
    """Where the run of `chars` from i ends"""
    while i < len(s) and s[i] in chars:
        i += 1
    return i


def run_not(s, i, stop):
    """Where the run from i of characters not in `stop` (nor spaces) ends"""
    while i < len(s) and s[i] not in stop and not is_space(s[i]):
        i += 1
    return i


def run_eq_space(s, i):
    while i < len(s) and (s[i] == "=" or is_space(s[i])):
        i += 1
    return i


def sub(s, at):
    """re.sub's walk: at(s, i) gives (end, replacement) of a match there,
    or None"""
    out = []
    last = 0
    i = 0
    while i < len(s):
        m = at(s, i)
        if m is None:
            i += 1
            continue
        out.append(s[last:i])
        out.append(m[1])
        last = m[0]
        i = m[0] if m[0] > i else i + 1
    out.append(s[last:])
    return "".join(out)


def at_name_value(s, i):
    # \b([A-Za-z0-9_]*(?:TOKEN|...)[A-Za-z0-9_]*=)('[^']*'|"[^"]*"|\S+), re.I
    if not name_char(s[i]) or not boundary(s, i):
        return None
    e = i
    while e < len(s) and name_char(s[e]):
        e += 1
    if e >= len(s) or s[e] != "=":
        return None
    name = upper_folded(s[i:e])
    hit = False
    for k in KEYWORDS:
        if k in name:
            hit = True
    if not hit:
        return None
    p = e + 1
    if p < len(s) and (s[p] == "'" or s[p] == '"'):
        close = s.find(s[p], p + 1)
        if close >= 0:
            return (close + 1, s[i:p] + "***")
    q = p
    while q < len(s) and not is_space(s[q]):
        q += 1
    if q == p:
        return None
    return (q, s[i:p] + "***")


def ieq(s, i, word):
    """s[i:] starts with word, ASCII, re.I's way"""
    if i + len(word) > len(s):
        return False
    return upper_folded(s[i:i + len(word)]) == word.upper()


def at_authorization(s, i):
    # (Authorization:\s*)(?:(Bearer|Basic|token)\s+)?[^'"\s]+, re.I
    if not ieq(s, i, "Authorization:"):
        return None
    head_end = i + 14
    spaces = head_end
    while spaces < len(s) and is_space(s[spaces]):
        spaces += 1
    # (\s* from the most spaces down: the first way that matches)
    k = spaces
    while k >= head_end:
        for scheme in ("Bearer", "Basic", "token"):
            if ieq(s, k, scheme):
                w = k + len(scheme)
                ws = w
                while ws < len(s) and is_space(s[ws]):
                    ws += 1
                # (\s+ from the most down to one)
                t = ws
                while t > w:
                    v = run_not(s, t, "'\"")
                    if v > t:
                        return (v, s[i:k] + s[k:w] + " ***")
                    t -= 1
        v = run_not(s, k, "'\"")
        if v > k:
            return (v, s[i:k] + "***")
        k -= 1
    return None


def at_bearer(s, i):
    # \b(Bearer)\s+[A-Za-z0-9._~+/=-]+
    if not s.startswith("Bearer", i) or not boundary(s, i):
        return None
    w = i + 6
    ws = w
    while ws < len(s) and is_space(s[ws]):
        ws += 1
    if ws == w:
        return None
    v = run_of(s, ws, BEARER)
    if v == ws:
        return None
    return (v, "Bearer ***")


def at_user(s, i):
    # (\s(?:-u|--user)[=\s]+)([^:\s'"]+):(\S+)
    if not is_space(s[i]):
        return None
    if s.startswith("-u", i + 1):
        o = i + 3
    elif s.startswith("--user", i + 1):
        o = i + 7
    else:
        return None
    r = run_eq_space(s, o)
    k = r
    while k > o:
        u = run_not(s, k, ":'\"")
        if u > k and u < len(s) and s[u] == ":":
            p = u + 1
            q = p
            while q < len(s) and not is_space(s[q]):
                q += 1
            if q > p:
                return (q, s[i:u] + ":***")
        k -= 1
    return None


def at_url(s, i):
    # (://[^/\s:@]+):[^@\s/]+@
    if not s.startswith("://", i):
        return None
    u = run_not(s, i + 3, "/:@")
    if u == i + 3 or u >= len(s) or s[u] != ":":
        return None
    p = run_not(s, u + 1, "@/")
    if p == u + 1 or p >= len(s) or s[p] != "@":
        return None
    return (p + 1, s[i:u] + ":***@")


def at_password(s, i):
    # (--password[=\s]+)\S+
    if not s.startswith("--password", i):
        return None
    o = i + 10
    r = run_eq_space(s, o)
    k = r
    while k > o:
        if k < len(s) and not is_space(s[k]):
            q = k
            while q < len(s) and not is_space(s[q]):
                q += 1
            return (q, s[i:k] + "***")
        k -= 1
    return None


def at_token(s, i):
    # \b(?:ghp|...|xox[abprs])[-_][A-Za-z0-9_-]{10,}
    if not boundary(s, i) or not is_word(s[i]):
        return None
    for prefix in TOKEN_PREFIXES:
        if s.startswith(prefix, i):
            d = i + len(prefix)
            if d < len(s) and (s[d] == "-" or s[d] == "_"):
                v = run_of(s, d + 1, JWT)
                if v - (d + 1) >= 10:
                    return (v, "***")
    return None


def at_aws(s, i):
    # \bAKIA[0-9A-Z]{16}\b
    if not s.startswith("AKIA", i) or not boundary(s, i):
        return None
    e = i + 20
    if e > len(s):
        return None
    for c in s[i + 4:e]:
        if c not in AWS:
            return None
    if e < len(s) and is_word(s[e]):
        return None
    return (e, "***")


def at_jwt(s, i):
    # \beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+
    if not s.startswith("eyJ", i) or not boundary(s, i):
        return None
    a = run_of(s, i + 3, JWT)
    if a - (i + 3) < 10 or a >= len(s) or s[a] != ".":
        return None
    b = run_of(s, a + 1, JWT)
    if b == a + 1 or b >= len(s) or s[b] != ".":
        return None
    c = run_of(s, b + 1, JWT)
    if c == b + 1:
        return None
    return (c, "***")


def record(rt, agent, cwd, command, decision, path):
    """Append a decision to the log at `path` (never raises: a log that
    fails isn't a decision that fails)."""
    record_call(rt, agent, cwd, command, decision, path, "", None)


def record_call(rt, agent, cwd, command, decision, path, ident, project):
    """record(), with the agent's id for the call ("" none: a later ran()
    with it says the command ran) and the project it was decided in."""
    entry = {"time": int(time()), "agent": agent, "cwd": cwd, "command": mask(command),
             "decision": decision.decision,
             "rule": where(decision.rule) if decision.rule is not None else decision.by}
    if ident != "":
        entry["id"] = ident
    if project is not None:
        entry["project"] = project
    append(rt, path, entry)


def record_ran(rt, agent, ident, path):
    """The call with this id ran (after an ask: the user said yes)."""
    line = dumps({"time": int(time()), "agent": agent, "ran": ident}) + "\n"
    try:
        new = not exists(path)
        makedirs(parent_of(path), 0o700, True)
        open(path, "a", encoding="utf-8").write(line)
        if new:
            chmod(path, 0o600)
    except OSError:
        pass


def append(rt, path, entry):
    try:
        new = not exists(path)
        # (its directory the user's only: the commands are theirs)
        makedirs(parent_of(path), 0o700, True)
        open(path, "a", encoding="utf-8").write(dumps(entry) + "\n")
        if new:
            chmod(path, 0o600)
        trim(rt, path)
    except OSError:
        pass


def parent_of(path):
    i = max(path.rfind("/"), path.rfind("\\"))
    return path[:i] if i > 0 else path


def trim(rt, path):
    # (now and then: past 110% of the cap, back to the cap, old ones dropped)
    if getsize(path) < 200 * MAX_ENTRIES:
        return
    lines = open(path, encoding="utf-8").read().splitlines()
    if len(lines) <= MAX_ENTRIES * 11 // 10:
        return
    cutoff = time() - MAX_DAYS * 86400
    keep = [ln for ln in lines[len(lines) - MAX_ENTRIES:] if entry_time(rt, ln) >= cutoff]
    tmp = path[:len(path) - 6] + ".tmp" if path.endswith(".jsonl") else path + ".tmp"
    open(tmp, "w", encoding="utf-8").write("\n".join(keep) + "\n")
    chmod(tmp, 0o600)
    replace(tmp, path)


def entries(rt, path):
    """The log's entries (dicts), those that read; none without a log."""
    if not exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8").read().splitlines():
        try:
            e = loads(rt, line)
        except zgram.ParseError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def entry_time(rt, line):
    try:
        e = loads(rt, line)
    except zgram.ParseError:
        return 0
    if not isinstance(e, dict):
        return 0
    t = e.get("time", 0)
    return t if isinstance(t, int) or isinstance(t, float) else 0


def mask(command):
    """The command with what looks like a secret replaced by ***."""
    s = sub(command, at_name_value)
    s = sub(s, at_authorization)
    s = sub(s, at_bearer)
    s = sub(s, at_user)
    s = sub(s, at_url)
    s = sub(s, at_password)
    s = sub(s, at_token)
    s = sub(s, at_aws)
    return sub(s, at_jwt)
