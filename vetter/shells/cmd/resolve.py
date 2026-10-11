"""What a cmd.exe command line runs: internal commands with what they do
to files, what runs other commands (call, start, cmd /c, for /f,
powershell, forfiles, wmic), external programs through bash's specs. The
walker is a record (CW) and module functions, given rt first.

    r = resolve(rt, "del /s /q %TEMP%\\x", "C:/Users/u/p", "C:/Users/u", 0, None, (), False)
"""

from dataclasses import dataclass

from ... import paths
from ...paths import fold
from ...specs import Role, is_space, strip
from ..bash.expand import Field, Variables
from ..bash.resolve import Ctx, Execution, Redirect, Resolution, Stdin, W, execution, run, unknown
from .syntax import Block, For, If, Simple, parse

MAX_DEPTH = 8
QUIET = {"nul", "nul:", "con", "con:"}

INTERNAL = {"echo", "set", "cls", "title", "ver", "vol", "path", "prompt", "color", "setlocal", "endlocal",
            "exit", "goto", "pause", "verify", "popd", "break", "rem", "date", "time", "shift", "assoc",
            "ftype", "mklink", "if", "for", "call", "start", "cd", "chdir", "pushd", "del", "erase", "rd", "rmdir",
            "copy", "move", "ren", "rename", "md", "mkdir", "type", "dir"}

# Windows programs that run commands or code from what they're given: read
# here whichever shell starts them (simple() below)
LAUNCHERS = {"cmd", "powershell", "pwsh", "conhost", "forfiles", "wmic", "schtasks", "at"}

# (for /f's rounds a line is read for: its variables' values)
MAX_ROUNDS = 8


def default_env(home, cwd):
    """cmd's variables as a new cmd.exe has them, from the user's home."""
    h = (home if home is not None and home != "" else "C:/Users/user").replace("/", "\\")
    drive = h[:2] if len(h) >= 2 and h[1] == ":" and ((h[0] >= "A" and h[0] <= "Z") or (h[0] >= "a" and h[0] <= "z")) \
        else "C:"
    env = {
        "USERPROFILE": h, "HOMEDRIVE": drive, "HOMEPATH": h[2:], "TEMP": h + "\\AppData\\Local\\Temp",
        "TMP": h + "\\AppData\\Local\\Temp", "APPDATA": h + "\\AppData\\Roaming", "LOCALAPPDATA": h + "\\AppData\\Local",
        "COMSPEC": "C:\\Windows\\system32\\cmd.exe", "SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows",
        "SYSTEMDRIVE": "C:", "PROGRAMFILES": "C:\\Program Files", "PROGRAMFILES(X86)": "C:\\Program Files (x86)",
        "PROGRAMDATA": "C:\\ProgramData", "PUBLIC": "C:\\Users\\Public", "OS": "Windows_NT",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC",
        "PROCESSOR_ARCHITECTURE": "AMD64",
    }
    if cwd is not None and cwd != "":
        env["CD"] = cwd.replace("/", "\\")
    return env


@dataclass
class CW:
    """The walker: what it found, the home, how deep in code read again,
    via, whether !VAR! expands, bash's walker, where it runs."""

    r: object
    home: object
    depth: int
    via: tuple
    delayed: bool
    bash: object
    cwd: object


def walker(r, home, depth, via, delayed):
    return CW(r, home, depth, via, delayed, W(r), None)


def resolve(rt, command, cwd, home, depth, r, via, delayed):
    """The line's executions (r, or a new Resolution); ValueError
    ("unreadable: ...") when cmd's reading of it can't be known."""
    if r is None:
        r = Resolution([], [], set(), set())
    w = walker(r, home, depth, via, delayed)
    w.cwd = cwd
    seq, _ = parse(command, default_env(home, cwd), delayed)
    for part in seq.parts:
        node(rt, w, part)
    return r


def launch(rt, r, home, depth, via, cwd, name, line, redirects, span):
    """A launcher started by another shell (PowerShell, bash) with this
    command line: read as cmd would see it started."""
    w = walker(r, home, depth, via, False)
    w.cwd = cwd
    first = len(r.executions)
    simple(rt, w, Simple(name, line, [], span))
    if len(r.executions) > first:
        r.executions[first].redirects = [x for x in redirects]


def ctx_of(w):
    return Ctx(w.cwd, Variables({"HOME": w.home}), w.home, w.via, w.depth, None, None, 0, "", {}, None)


def note(rt, w, reason, span, kind):
    unknown(rt, w.bash, reason, span, ctx_of(w), kind, [])


def strip_chars(s, chars):
    i = 0
    j = len(s)
    while i < j and s[i] in chars:
        i += 1
    while j > i and s[j - 1] in chars:
        j -= 1
    return s[i:j]


def split_runs(s, sep):
    """re.split(r"[sep]+", s): the pieces between runs of sep's characters
    (empty ones at the ends kept)."""
    out = []
    cur = ""
    i = 0
    while i < len(s):
        if sep(s[i]):
            out.append(cur)
            cur = ""
            while i < len(s) and sep(s[i]):
                i += 1
            continue
        cur += s[i]
        i += 1
    out.append(cur)
    return out


def is_number(s, signed):
    """[+-]?[0-9]+ (signed) or [0-9]+"""
    i = 0
    if signed and (s[:1] == "+" or s[:1] == "-"):
        i = 1
    if i >= len(s):
        return False
    while i < len(s):
        if s[i] < "0" or s[i] > "9":
            return False
        i += 1
    return True


def blank_or_sep(c):
    return is_space(c) or c == "," or c == ";" or c == "="


def for_values(n):
    """Each round's for variables when the line tells them (a list of
    dicts); None: only running tells."""
    var = lstrip_pct(n.variable)
    opts = [fold(o) for o in n.options]
    items = strip(n.items)
    if "/l" in opts:
        numbers = split_runs(items, blank_or_sep)
        if len(numbers) != 3:
            return None
        for x in numbers:
            if not is_number(x, True):
                return None
        start = int(numbers[0])
        step = int(numbers[1])
        end = int(numbers[2])
        out = []
        v = start
        while step != 0 and (v <= end if step > 0 else v >= end) and len(out) < MAX_ROUNDS:
            out.append({var: str(v)})
            v += step
        return out
    if "/f" in opts:
        at = 0
        for k in range(len(opts)):
            if opts[k] == "/f":
                at = k
                break
        o = fold(strip_chars(" ".join(n.options[at + 1 :]), '"'))
        usebackq = "usebackq" in o
        quote = "'" if usebackq else '"'
        if not (len(items) > 1 and items[0] == quote and items[len(items) - 1] == quote) or "skip=" in o or "eol=" in o:
            return None
        s = items[1 : len(items) - 1]
        delims = " \t"
        d = o.find("delims=")
        if d >= 0:
            e = d + 7
            while e < len(o) and not is_space(o[e]):
                e += 1
            delims = o[d + 7 : e]
        spec = tokens_spec(o)
        parts = [s]
        if delims != "":
            parts = [x for x in split_runs(s, lambda c: c in delims) if x != ""]
        wanted = []
        for piece in spec.split(","):
            if piece == "*" or piece.endswith("*"):
                if piece != "*" and not is_number(piece[: len(piece) - 1], False):
                    return None
                highest = 0
                for w in wanted:
                    if not isinstance(w, tuple) and w > highest:
                        highest = w
                rest_from = int(piece[: len(piece) - 1]) if piece != "*" else highest + 1
                wanted.append(("rest", rest_from))
                continue
            a, _, b = piece.partition("-")
            # (tokens= cmd reads: 1 to 31; anything else, not known here)
            if not is_number(a, False) or not (b == "" or is_number(b, False)):
                return None
            hi = int(b) if b != "" else int(a)
            if hi - int(a) > 31:
                return None
            for k in range(int(a), hi + 1):
                wanted.append(k)
        for w in wanted:
            if (w[1] if isinstance(w, tuple) else w) < 1:
                return None
        values = {}
        letter = var
        for w in wanted:
            if isinstance(w, tuple):
                values[letter] = " ".join(parts[w[1] - 1 :])
            else:
                values[letter] = parts[w - 1] if w - 1 < len(parts) else ""
            letter = chr(ord(letter) + 1)
        return [values]
    if len(opts) > 0:
        return None
    words = for_words(items)
    for w in words:
        if "*" in w or "?" in w:
            return None
    return [{var: w} for w in words]


def lstrip_pct(s):
    i = 0
    while i < len(s) and s[i] == "%":
        i += 1
    return s[i:]


def tokens_spec(o):
    """re.search(r"tokens=([0-9,\\-*]+)", o)[1], or "1"."""
    i = 0
    while True:
        d = o.find("tokens=", i)
        if d < 0:
            return "1"
        e = d + 7
        while e < len(o) and (("0" <= o[e] and o[e] <= "9") or o[e] == "," or o[e] == "-" or o[e] == "*"):
            e += 1
        if e > d + 7:
            return o[d + 7 : e]
        i = d + 1


def for_words(items):
    """re.findall(r'"[^"]*"|[^\\s,;="]+', items)"""
    out = []
    i = 0
    n = len(items)
    while i < n:
        c = items[i]
        if c == '"':
            j = items.find('"', i + 1)
            if j >= 0:
                out.append(items[i : j + 1])
                i = j + 1
            else:
                i += 1
            continue
        if blank_or_sep(c):
            i += 1
            continue
        j = i
        while j < n and not blank_or_sep(items[j]) and items[j] != '"':
            j += 1
        out.append(items[i:j])
        i = j
    return out


def has_modifier(body, var):
    """re.search(r"%~(?:[fdpnxsatz]+|\\$\\w+:)" + var, body, re.ASCII)"""
    i = body.find("%~")
    while i >= 0:
        p = i + 2
        run_end = p
        while run_end < len(body) and body[run_end] in "fdpnxsatz":
            run_end += 1
        for k in range(p + 1, run_end + 1):
            if body[k : k + len(var)] == var:
                return True
        if body[p : p + 1] == "$":
            q = p + 1
            while q < len(body) and (body[q].isalnum() and ord(body[q]) < 128 or body[q] == "_"):
                q += 1
            if q > p + 1 and body[q : q + 1] == ":" and body[q + 1 : q + 1 + len(var)] == var:
                return True
        i = body.find("%~", i + 1)
    return False


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def node(rt, w, n):
    if isinstance(n, list):
        # (a pipeline: each reads the one before)
        producer = None
        for c in n:
            first = len(w.r.executions)
            node(rt, w, c)
            if len(w.r.executions) > first and producer is not None:
                w.r.executions[first].stdin = Stdin(None, producer)
            producer = w.r.executions[first] if len(w.r.executions) > first else None
    elif isinstance(n, Simple):
        simple(rt, w, n)
    elif isinstance(n, Block):
        for c in n.body:
            node(rt, w, c)
        if len(n.redirections) > 0:
            reds = []
            for x in n.redirections:
                red = redirect(x)
                if red is not None:
                    reds.append(red)
            if len(reds) > 0:
                w.r.executions.append(execution([Field(["("], False, False)], {}, reds, w.cwd, n.span, w.via, None,
                                                "group"))
    elif isinstance(n, If):
        node(rt, w, n.then)
        if n.otherwise is not None:
            node(rt, w, n.otherwise)
    elif isinstance(n, For):
        for_command(rt, w, n)


def for_command(rt, w, n):
    opts = [fold(o) for o in n.options]
    items = strip(n.items)
    if "/f" in opts:
        usebackq = False
        for o in n.options:
            if "usebackq" in o:
                usebackq = True
        quote = "`" if usebackq else "'"
        if items.startswith(quote) and items.endswith(quote) and len(items) > 1:
            # (for /f ... in ('command'): it runs)
            code(rt, w, items[1 : len(items) - 1], n.span, "for /f", None)
    rounds = for_values(n)
    modifiers = False
    if rounds is not None and len(rounds) > 0:
        for var in rounds[0]:
            if has_modifier(n.body_text, var):
                modifiers = True
    if rounds is not None and strip(n.body_text) != "" and not modifiers:
        # (the values known: the body read with each, as cmd runs it)
        for values in rounds[:MAX_ROUNDS]:
            text = n.body_text
            for var, v in values.items():
                text = text.replace("%~" + var, strip_chars(v, '"')).replace("%" + var, v)
            code(rt, w, text, n.span, "for", None)
        return
    node(rt, w, n.body)


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def conhost_rest(args):
    """re.sub(r"^(\\s*--\\S+(\\s+[0-9]+)?)*\\s*", "", args)"""
    p = 0
    while True:
        q = p
        while q < len(args) and is_space(args[q]):
            q += 1
        if args[q : q + 2] != "--":
            break
        r = q + 2
        while r < len(args) and not is_space(args[r]):
            r += 1
        if r == q + 2:
            break
        p = r
        s = p
        while s < len(args) and is_space(args[s]):
            s += 1
        if s > p and s < len(args) and args[s] >= "0" and args[s] <= "9":
            while s < len(args) and args[s] >= "0" and args[s] <= "9":
                s += 1
            p = s
    while p < len(args) and is_space(args[p]):
        p += 1
    return args[p:]


def wmic_command(args):
    """re.search(r'[cC][rR][eE][aA][tT][eE]\\s+"([^"]*)"', args)[1], or None."""
    i = 0
    while i + 6 <= len(args):
        if paths_ascii_lower(args[i : i + 6]) == "create":
            j = i + 6
            k = j
            while k < len(args) and is_space(args[k]):
                k += 1
            if k > j and k < len(args) and args[k] == '"':
                q = args.find('"', k + 1)
                if q >= 0:
                    return args[k + 1 : q]
        i += 1
    return None


def paths_ascii_lower(s):
    out = ""
    for c in s:
        out += chr(ord(c) + 32) if c >= "A" and c <= "Z" else c
    return out


def simple(rt, w, n):
    from ..powershell.resolve import powershell, windows_argv
    from ..powershell.resolve import walker as ps_walker

    if n.name == "" or fold(n.name) == "rem":
        return
    name = n.name
    low = fold(paths.program_name(name))
    reds = []
    for x in n.redirections:
        red = redirect(x)
        if red is not None:
            reds.append(red)
    span = n.span
    if low in INTERNAL and "\\" not in name and "/" not in name:
        internal(rt, w, low, name, n.args, reds, span)
        return
    argv = [Field([name], False, False)] + [Field([a], False, False) for a in windows_argv(n.args)]
    if low == "cmd":
        w.r.executions.append(execution(argv, {}, reds, w.cwd, span, w.via, None, "program"))
        cmd(rt, w, n.args, span)
        return
    if low == "powershell" or low == "pwsh":
        e = execution(argv, {}, reds, w.cwd, span, w.via, None, "program")
        w.r.executions.append(e)
        ps = ps_walker(w.r, w.home, w.depth + 1)
        ps.cwd = w.cwd
        ps.via = w.via
        powershell(rt, ps, e, argv[1:], span)
        return
    if low == "conhost":
        # (conhost runs the command line it's given)
        w.r.executions.append(execution(argv, {}, reds, w.cwd, span, w.via, None, "program"))
        rest = conhost_rest(n.args)
        if rest != "":
            code(rt, w, rest, span, "conhost", None)
        return
    if low == "forfiles":
        w.r.executions.append(execution(argv, {}, reds, w.cwd, span, w.via, None, "program"))
        note(rt, w, "forfiles runs a command for each file it finds", span, "code")
        return
    if low == "wmic" and "create" in fold(n.args):
        w.r.executions.append(execution(argv, {}, reds, w.cwd, span, w.via, None, "program"))
        created = wmic_command(n.args)
        if created is not None:
            code(rt, w, created, span, "wmic process call create", None)
        else:
            note(rt, w, "wmic process call create: a command vetter doesn't read", span, "code")
        return
    if (low == "schtasks" or low == "at") and "/create" in fold(n.args):
        w.r.executions.append(execution(argv, {}, reds, w.cwd, span, w.via, None, "program"))
        note(rt, w, low + " /create: schedules a command to run later", span, "persistent")
        return
    # (rundll32, regsvr32, msiexec...: specs/windows.toml)
    run(rt, w.bash, argv, {}, reds, ctx_of(w), span, None, w.via)


def split_args(s):
    """An internal command's words: blanks and , ; = separate, quotes group
    (and stay off the value)."""
    out = []
    i = 0
    n = len(s)
    while i < n:
        if blank_or_sep(s[i]) and s[i] != '"':
            i += 1
            continue
        j = i
        while j < n:
            if s[j] == '"':
                q = s.find('"', j + 1)
                j = n if q < 0 else q + 1
            elif blank_or_sep(s[j]):
                break
            else:
                j += 1
        out.append(s[i:j].replace('"', ""))
        i = j
    return out


def internal(rt, w, low, name, args, reds, span):
    words = split_args(args)
    argv = [Field([low], False, False)] + [Field([x], False, False) for x in words]
    e = Execution(argv, {}, reds, w.cwd, span, w.via, None, "program", [], [], True, low == "type" or low == "dir")
    operands = [x for x in words if not x.startswith("/")]
    if low == "del" or low == "erase" or low == "rd" or low == "rmdir":
        for x in operands:
            e.roles.append(Role("delete", Field([x], False, False), None))
    elif low == "copy" or low == "move":
        if low == "copy":
            operands = [x for x in operands if x != "+"]
        sources = operands[: len(operands) - 1] if len(operands) > 1 else operands
        for x in sources:
            e.roles.append(Role("delete" if low == "move" else "read", Field([x], False, False), None))
        if len(operands) > 1:
            e.roles.append(Role("write", Field([operands[len(operands) - 1]], False, False), None))
    elif low == "ren" or low == "rename":
        if len(operands) > 0:
            e.roles.append(Role("delete", Field([operands[0]], False, False), None))
        if len(operands) > 1:
            e.roles.append(Role("write", Field([operands[1]], False, False), None))
    elif low == "md" or low == "mkdir":
        for x in operands:
            e.roles.append(Role("write", Field([x], False, False), None))
    elif low == "type" or low == "dir":
        for x in operands:
            e.roles.append(Role("read", Field([x], False, False), None))
    w.r.executions.append(e)
    if low == "cd" or low == "chdir" or low == "pushd":
        if len(operands) > 0:
            w.cwd = paths.join(w.cwd, " ".join(operands))
    elif low == "call":
        rest = strip(args)
        if rest != "" and not rest.startswith(":"):
            code(rt, w, rest, span, "call", None)
    elif low == "start":
        start(rt, w, args, span)


def start_option_end(s):
    """The end of re.match(r"/([dD]|affinity|node)\\s+\\S+\\s*|/\\S+\\s*", s)
    (letters in either case), or -1."""
    if s[:1] != "/":
        return -1
    for word in ("d", "affinity", "node"):
        k = 1 + len(word)
        if paths_ascii_lower(s[1:k]) == word:
            j = k
            while j < len(s) and is_space(s[j]):
                j += 1
            if j > k and j < len(s):
                e = j
                while e < len(s) and not is_space(s[e]):
                    e += 1
                while e < len(s) and is_space(s[e]):
                    e += 1
                return e
    e = 1
    while e < len(s) and not is_space(s[e]):
        e += 1
    if e == 1:
        return -1
    while e < len(s) and is_space(s[e]):
        e += 1
    return e


def start(rt, w, args, span):
    """start ["title"] [/options] command args: the command run."""
    s = strip(args)
    if s.startswith('"'):
        j = s.find('"', 1)
        s = strip(s[j + 1 :]) if j > 0 else ""
    while True:
        e = start_option_end(s)
        if e < 0:
            break
        s = s[e:]
    if s != "":
        code(rt, w, s, span, "start", None)


def cmd(rt, w, args, span):
    """cmd /c TEXT, cmd /k TEXT (/v:on: !VAR! expanded too)."""
    at = -1
    for i in range(len(args) - 1):
        if args[i] == "/" and args[i + 1] in "cCkK":
            at = i
            break
    delayed = False
    for i in range(len(args) - 4):
        if args[i] == "/" and paths_ascii_lower(args[i + 1 : i + 5]) == "v:on":
            delayed = True
            break
    if at < 0:
        return
    e = at + 2
    while e < len(args) and is_space(args[e]):
        e += 1
    rest = args[e:]
    if rest.startswith('"') and rstrip(rest).endswith('"'):
        r = strip(rest)
        rest = r[1 : len(r) - 1]
    code(rt, w, rest, span, "cmd /c", delayed)


def rstrip(s):
    j = len(s)
    while j > 0 and is_space(s[j - 1]):
        j -= 1
    return s[:j]


def code(rt, w, text, span, label, delayed):
    if w.depth >= MAX_DEPTH:
        note(rt, w, label + ": nested too deep", span, "code")
        return
    executions = len(w.r.executions)
    unknowns = len(w.r.unknowns)
    try:
        resolve(rt, text, w.cwd, w.home, w.depth + 1, w.r, w.via + (label,), w.delayed if delayed is None else delayed)
    except ValueError as ex:
        why = str(ex)
        if why.startswith("unreadable: "):
            why = why[12:]
        note(rt, w, label + ": " + why, span, "code")
    for x in w.r.executions[executions:]:
        x.span = span
    for u in w.r.unknowns[unknowns:]:
        u.span = span


def redirect(red):
    if "&" in red.op:
        return None
    target = red.target.replace('"', "")
    if fold(target) in QUIET:
        return None
    op = ">>" if ">>" in red.op else (">" if ">" in red.op else "<")
    fd = red.op[0] if red.op[0] >= "0" and red.op[0] <= "9" else None
    return Redirect(fd, op, Field([target], False, False), None)
