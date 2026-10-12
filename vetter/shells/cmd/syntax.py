"""cmd.exe's command lines read as cmd reads them: %VAR% expansion, quotes
and carets, commands (if, for, blocks, rem). A line whose reading can't be
known: ValueError("unreadable: ...").

    seq, expanded = parse(line, env, delayed)
    text = expand_marks(text, env, "!")      # a command's !VAR!, as it runs
"""

from dataclasses import dataclass

from ...paths import case_key, fold
from ...specs import is_space, strip


def unreadable(why):
    return ValueError("unreadable: " + why)


# Phase 1: %VAR%


def expand(line, env, delayed):
    """The line with %VAR% (and !VAR! when delayed) expanded."""
    out = expand_marks(line, env, "%")
    if delayed:
        out = expand_marks(out, env, "!")
    return out


def no_variable(ref, mark):
    """%1, %*, a for's %i (~?[0-9*]), or a "name" with blanks, quotes or
    operators: no variable."""
    head = ref[:2]
    if mark == "%" and ((len(head) == 1 and head in "0123456789*")
                        or (len(head) == 2 and head[0] == "~" and head[1] in "0123456789*")):
        return True
    for c in ref.partition(":")[0]:
        if is_space(c) or c in "\"'()&|<>":
            return True
    return False


def expand_marks(line, env, mark):
    out = ""
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c != mark:
            out += c
            i += 1
            continue
        j = line.find(mark, i + 1)
        if j < 0:
            out += line[i:]
            break
        ref = line[i + 1 : j]
        if ref == "":
            # (%% at a prompt stays %%)
            out += mark + mark
            i = j + 1
            continue
        if no_variable(ref, mark):
            out += c
            i += 1
            continue
        out += reference(ref, env)
        i = j + 1
    return out


def ascii_space(c):
    return c == " " or c == "\t" or c == "\n" or c == "\r" or c == "\x0b" or c == "\x0c"


def skip_ascii_space(s, i):
    while i < len(s) and ascii_space(s[i]):
        i += 1
    return i


def int_at(s, i):
    """The end of -?[0-9]+ at i, or -1."""
    j = i
    if j < len(s) and s[j] == "-":
        j += 1
    k = j
    while k < len(s) and s[k] >= "0" and s[k] <= "9":
        k += 1
    return k if k > j else -1


def reference(ref, env):
    name, _, op = ref.partition(":")
    # (names compare as Windows compares them: env's keys are case_keys)
    key = case_key(name)
    if key not in env:
        raise unreadable("%" + name + "%: a variable whose value only running tells")
    v = env[key]
    if op == "":
        return v
    # (~\s*(-?\d+)\s*(?:,\s*(-?\d+))?, ASCII)
    if op[:1] == "~":
        i = skip_ascii_space(op, 1)
        e = int_at(op, i)
        if e >= 0:
            start = int(op[i:e])
            length = None
            j = skip_ascii_space(op, e)
            ok = j == len(op)
            if not ok and op[j] == ",":
                k = skip_ascii_space(op, j + 1)
                e2 = int_at(op, k)
                if e2 >= 0 and e2 == len(op):
                    length = int(op[k:e2])
                    ok = True
            if ok:
                if start < 0:
                    start = max(0, len(v) + start)
                s = v[start:]
                if length is not None:
                    s = s[:length] if length >= 0 else s[: max(0, len(s) + length)]
                return s
    if "=" in op:
        find, _, repl = op.partition("=")
        # (case doesn't matter, as Windows compares: case_key keeps each
        # character in its place)
        if find.startswith("*"):
            k = case_key(v).find(case_key(find[1:]))
            return v if k < 0 else repl + v[k + len(find) - 1 :]
        return replace_all(v, find, repl) if find != "" else v
    raise unreadable("%" + ref + "%: a form vetter doesn't read")


def replace_all(v, find, repl):
    """Each find in v replaced, case not mattering."""
    key = case_key(v)
    want = case_key(find)
    out = ""
    i = 0
    while True:
        k = key.find(want, i)
        if k < 0:
            return out + v[i:]
        out += v[i:k] + repl
        i = k + len(find)


# Phase 2: tokens


@dataclass
class Tok:
    kind: str       # "text", "op", "redir", "nl", "sp"
    text: str
    start: int


def tokens(line):
    """The line's tokens: runs of text (quotes kept, carets taken out),
    operators, redirections, newlines, blanks."""
    out = []
    i = 0
    n = len(line)
    buf = []
    start = 0
    while i < n:
        c = line[i]
        if c == '"':
            if len(buf) == 0:
                start = i
            j = line.find('"', i + 1)
            j = n - 1 if j < 0 else j
            buf.append(line[i : j + 1])
            i = j + 1
            continue
        if c == "^":
            if i + 1 < n and (line[i + 1] == "\r" or line[i + 1] == "\n"):
                # (a caret at a line's end continues it)
                i += 2 if line[i + 1 : i + 3] != "\r\n" else 3
                continue
            if len(buf) == 0:
                start = i
            if i + 1 < n:
                buf.append(line[i + 1])
            i += 2
            continue
        two = line[i : i + 2]
        if two == "&&" or two == "||":
            if len(buf) > 0:
                out.append(Tok("text", "".join(buf), start))
                buf = []
            out.append(Tok("op", two, i))
            i += 2
            continue
        if c == "&" or c == "|" or c == "(" or c == ")":
            if len(buf) > 0:
                out.append(Tok("text", "".join(buf), start))
                buf = []
            out.append(Tok("op", c, i))
            i += 1
            continue
        if c == ">" or c == "<":
            # (>>?(&[0-9])? or <(&[0-9])?)
            k = i + 1
            if c == ">" and k < n and line[k] == ">":
                k += 1
            if k + 1 < n and line[k] == "&" and line[k + 1] >= "0" and line[k + 1] <= "9":
                k += 2
            op = line[i:k]
            # (a > or < ends the word before it, but a lone digit right
            # before it is its stream: 2>x)
            fd = ""
            if len(buf) == 1 and len(buf[0]) == 1 and buf[0] >= "0" and buf[0] <= "9" and start == i - 1:
                fd = buf[0]
                buf = []
            if len(buf) > 0:
                out.append(Tok("text", "".join(buf), start))
                buf = []
            out.append(Tok("redir", fd + op, i - len(fd)))
            i = k
            continue
        if c == "\r" or c == "\n":
            if len(buf) > 0:
                out.append(Tok("text", "".join(buf), start))
                buf = []
            out.append(Tok("nl", "\n", i))
            i += 1
            continue
        if c == " " or c == "\t":
            if len(buf) > 0:
                out.append(Tok("text", "".join(buf), start))
                buf = []
            out.append(Tok("sp", c, i))
            i += 1
            continue
        if len(buf) == 0:
            start = i
        buf.append(c)
        i += 1
    if len(buf) > 0:
        out.append(Tok("text", "".join(buf), start))
    return out


# Phase 3: commands


@dataclass
class Redirection:
    op: str         # >, >>, <, 2>, 2>&1...
    target: str     # (empty for a merge)


@dataclass
class Simple:
    name: str
    args: str
    redirections: list
    span: tuple


@dataclass
class If:
    condition: list
    then: object
    otherwise: object
    span: tuple


@dataclass
class For:
    options: list
    variable: str
    items: str
    body: object
    span: tuple
    # (the body as written: the rest of the line, & and all, each time)
    body_text: str


@dataclass
class Block:
    body: list
    redirections: list
    span: tuple


@dataclass
class Seq:
    """Commands joined by & && || (ops between), pipelines (lists) by |."""

    parts: list
    ops: list


@dataclass
class P:
    """The parser: the tokens, where it is, the line they're of."""

    t: list
    i: int
    line: str


def peek_index(p, skip_sp):
    j = p.i
    while skip_sp and j < len(p.t) and p.t[j].kind == "sp":
        j += 1
    return j


def peek(p, skip_sp):
    j = peek_index(p, skip_sp)
    return p.t[j] if j < len(p.t) else None


def take(p):
    while p.i < len(p.t) and p.t[p.i].kind == "sp":
        p.i += 1
    if p.i >= len(p.t):
        raise unreadable("the line ends too soon")
    tok = p.t[p.i]
    p.i += 1
    return tok


def sequence(p, in_block):
    parts = []
    ops = []
    while True:
        tok = peek(p, True)
        if tok is None:
            break
        if tok.kind == "nl":
            take(p)
            if len(parts) > 0 and len(ops) < len(parts):
                ops.append("\n")
            continue
        if tok.kind == "op" and tok.text == ")":
            if in_block:
                break
            raise unreadable("a ) outside a block")
        parts.append(pipeline(p))
        tok = peek(p, True)
        if tok is None:
            break
        if tok.kind == "op" and (tok.text == "&" or tok.text == "&&" or tok.text == "||"):
            ops.append(take(p).text)
            continue
        if tok.kind == "nl" or (tok.kind == "op" and tok.text == ")" and in_block):
            continue
        raise unreadable("unexpected " + repr(tok.text))
    return Seq(parts, ops)


def pipeline(p):
    cmds = [command(p)]
    while True:
        tok = peek(p, True)
        if tok is not None and tok.kind == "op" and tok.text == "|":
            take(p)
            cmds.append(command(p))
            continue
        break
    return cmds if len(cmds) > 1 else cmds[0]


def lstrip_chars(s, chars):
    i = 0
    while i < len(s) and s[i] in chars:
        i += 1
    return s[i:]


def command(p):
    j = peek_index(p, True)
    if j >= len(p.t):
        raise unreadable("a command is missing")
    tok = p.t[j]
    start = tok.start
    if tok.kind == "op" and tok.text == "(":
        take(p)
        body = sequence(p, True)
        close = peek(p, True)
        if close is None or close.text != ")":
            raise unreadable("a ( isn't closed")
        take(p)
        reds = redirections(p)
        return Block(body.parts, reds, (start, close.start + 1))
    if tok.kind == "op":
        raise unreadable("unexpected " + repr(tok.text))
    core = fold(lstrip_chars(tok.text, "@")) if tok.kind == "text" else None
    if core is not None and core.startswith(":"):
        # (a label, :x or ::x, anywhere: nothing more on the line runs)
        while p.i < len(p.t) and p.t[p.i].kind != "nl":
            p.i += 1
        return Simple("rem", "", [], (start, start + len(tok.text)))
    if core == "rem":
        nxt = p.t[j + 1] if j + 1 < len(p.t) else None
        if nxt is None or nxt.kind == "sp" or nxt.kind == "nl":
            # (rem and a blank: the rest of the line is a comment, & too;
            # `rem.&x` runs x)
            take(p)
            while p.i < len(p.t) and p.t[p.i].kind != "nl":
                p.i += 1
            return Simple("rem", "", [], (start, start + 3))
    # (words up to an operator, with the redirections among them)
    words = []
    reds = []
    end = start
    while True:
        tok = peek(p, False)
        if tok is None or tok.kind == "nl" or tok.kind == "op":
            break
        if tok.kind == "sp":
            p.i += 1
            if len(words) > 0 and words[len(words) - 1] != " ":
                words.append(" ")
            continue
        if tok.kind == "redir":
            p.i += 1
            target = ""
            if "&" not in tok.text:
                t2 = peek(p, True)
                if t2 is None or t2.kind != "text":
                    raise unreadable("a redirection without its file")
                take(p)
                target = t2.text
                end = t2.start + len(t2.text)
            reds.append(Redirection(tok.text, target))
            continue
        p.i += 1
        words.append(tok.text)
        end = tok.start + len(tok.text)
    text = lstrip_chars(lstrip_chars(strip("".join(words)), "@"), " ,;=\t")
    if text == "":
        return Simple("", "", reds, (start, end))
    name, rest = split_name(text)
    low = fold(name)
    if low == "if":
        # (if 1==1 echo x> f: the redirection, read with the words, is the
        # command's after the condition)
        node = if_command(p, rest, start)
        if len(reds) > 0 and (isinstance(node.then, Simple) or isinstance(node.then, Block)):
            node.then.redirections = node.then.redirections + reds
        elif len(reds) > 0:
            raise unreadable("an if's redirection vetter doesn't place")
        return node
    if low == "for":
        return for_command(p, rest, start)
    if low == "rem" or (low.startswith("rem") and low[3] in ".:/\\(+[]"):
        # (rem. / rem/ / rem:: itself does nothing; what follows & runs)
        return Simple("rem", "", [], (start, end))
    return Simple(name, rest, reds, (start, end))


def redirections(p):
    reds = []
    while True:
        tok = peek(p, True)
        if tok is None or tok.kind != "redir":
            return reds
        take(p)
        target = ""
        if "&" not in tok.text:
            target = take(p).text
        reds.append(Redirection(tok.text, target))


def split_ws(s):
    """s.split()"""
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


def if_command(p, rest, start):
    """if [/i] [not] (exist X | defined X | errorlevel N | a==b | a op b)
    command [else command]."""
    words = split_ws(rest)
    cond = []
    k = 0
    while k < len(words) and (fold(words[k]) == "/i" or fold(words[k]) == "not"):
        cond.append(words[k])
        k += 1
    if k < len(words):
        w = fold(words[k])
        if w == "exist" or w == "defined" or w == "errorlevel" or w == "cmdextversion":
            cond += words[k : k + 2]
            k += 2
        elif "==" in words[k]:
            cond.append(words[k])
            k += 1
            if words[k - 1].endswith("==") and k < len(words):
                cond.append(words[k])
                k += 1
        elif k + 2 < len(words) and fold(words[k + 1]) in ("equ", "neq", "lss", "leq", "gtr", "geq"):
            cond += words[k : k + 3]
            k += 3
        elif k + 1 < len(words) and words[k + 1].startswith("=="):
            cond += words[k : k + 2]
            k += 2
            if words[k - 1] == "==" and k < len(words):
                cond.append(words[k])
                k += 1
    remaining = " ".join(words[k:])
    then = command_from_text(remaining) if remaining != "" else command(p)
    otherwise = None
    tok = peek(p, True)
    if tok is not None and tok.kind == "text" and fold(tok.text) == "else":
        take(p)
        otherwise = command(p)
    return If(cond, then, otherwise, (start, start))


@dataclass
class ForHead:
    """\\s*((?:/[dDrRlLfF](?:\\s+"[^"]*"|\\s+[^%\\s"][^\\s]*)?\\s+)*)(%%?[A-Za-z])\\s+[iI][nN]\\s*$
    as re matches it: the options' text, the variable."""

    options: str
    variable: str


def skip_space(s, i):
    while i < len(s) and is_space(s[i]):
        i += 1
    return i


def for_tail(s, i):
    """(%%?[A-Za-z])\\s+[iI][nN]\\s*$ at i: the variable, or None."""
    if i >= len(s) or s[i] != "%":
        return None
    for width in (2, 1):
        j = i + width
        if width == 2 and s[i + 1 : i + 2] != "%":
            continue
        if j >= len(s) or not ((s[j] >= "a" and s[j] <= "z") or (s[j] >= "A" and s[j] <= "Z")):
            continue
        k = skip_space(s, j + 1)
        if k == j + 1 or s[k : k + 2] not in ("in", "iN", "In", "IN"):
            continue
        e = skip_space(s, k + 2)
        # ($: the end, or a newline ending it)
        if e == len(s) or (e == len(s) - 1 and s[e] == "\n"):
            return s[i : j + 1]
        # (\s* backs off to leave a final newline to $)
        if s[len(s) - 1] == "\n" and skip_space(s, k + 2) >= len(s) - 1:
            return s[i : j + 1]
    return None


def for_options(s, i, base):
    """The options from i (each /x [arg] then blanks), then the tail: the
    head, or None. Tried in re's order: more options first; an option's
    argument (quoted, then bare) before none."""
    if s[i : i + 1] == "/" and i + 1 < len(s) and s[i + 1] in "dDrRlLfF":
        j = i + 2
        ends = []
        # (\s+"[^"]*")
        k = skip_space(s, j)
        if k > j and k < len(s) and s[k] == '"':
            q = s.find('"', k + 1)
            if q >= 0:
                ends.append(q + 1)
        # (\s+[^%\s"][^\s]*)
        if k > j and k < len(s) and s[k] != "%" and s[k] != '"' and not is_space(s[k]):
            e = k + 1
            while e < len(s) and not is_space(s[e]):
                e += 1
            ends.append(e)
        ends.append(j)
        for e in ends:
            after = skip_space(s, e)
            if after == e:
                continue
            head = for_options(s, after, base)
            if head is not None:
                return head
    v = for_tail(s, i)
    if v is None:
        return None
    return ForHead(s[base:i], v)


def for_head(rest):
    base = skip_space(rest, 0)
    return for_options(rest, base, base)


def for_command(p, rest, start):
    head = for_head(rest)
    if head is None:
        raise unreadable("a for vetter doesn't read")
    options = split_ws(head.options)
    variable = head.variable
    # (the set in parentheses, then `do` and the command)
    tok = peek(p, True)
    if tok is None or tok.text != "(":
        raise unreadable("for: its ( set ) is missing")
    open_at = tok.start
    take(p)
    depth = 1
    j = open_at + 1
    line = p.line
    while j < len(line) and depth > 0:
        if line[j] == "(":
            depth += 1
        elif line[j] == ")":
            depth -= 1
        elif line[j] == '"':
            k = line.find('"', j + 1)
            j = len(line) if k < 0 else k
        j += 1
    items = line[open_at + 1 : j - 1]
    # (skip the tokens of the set)
    while p.i < len(p.t) and p.t[p.i].start < j:
        p.i += 1
    tok = peek(p, True)
    if tok is None or tok.kind != "text" or not fold(tok.text).startswith("do"):
        raise unreadable("for: its do is missing")
    take(p)
    line_end = line.find("\n", tok.start)
    whole = line[tok.start + 2 : line_end if line_end >= 0 else len(line)]
    body_text = tok.text[2:]
    body = command_from_text(body_text) if strip(body_text) != "" else command(p)
    return For(options, variable, items, body, (start, start), whole)


def name_char(c):
    return c != " " and c != "\t" and c != "," and c != ";" and c != "=" and c != '"'


def split_name(text):
    """A command's name and the rest: the name ends at a blank or a , ; =
    (and, for a quoted name, at its quote); `echo.` `echo(` are echo."""
    if text.startswith('"'):
        j = text.find('"', 1)
        j = len(text) - 1 if j < 0 else j
        k = j + 1
        while k < len(text) and text[k] != " " and text[k] != "\t" and text[k] != "," and text[k] != ";" \
                and text[k] != "=":
            k += 1
        return text[:k].replace('"', ""), lstrip_chars(text[k:], " \t,;=")
    # ([^ \t,;="]+(?:"[^"]*"[^ \t,;="]*)*)
    k = 0
    while k < len(text) and name_char(text[k]):
        k += 1
    if k == 0:
        name = text
    else:
        while k < len(text) and text[k] == '"':
            q = text.find('"', k + 1)
            if q < 0:
                break
            k = q + 1
            while k < len(text) and name_char(text[k]):
                k += 1
        name = text[:k]
    low = fold(name)
    for internal in ("echo", "cd", "md", "rd", "type", "dir"):
        if low.startswith(internal) and len(low) > len(internal) and low[len(internal)] in ".:/\\[]+(":
            return name[: len(internal)], text[len(internal) :]
    return name.replace('"', ""), lstrip_chars(text[len(name) :], " \t,;=")


def command_from_text(text):
    """A command written on the rest of a word list (an if's or a for's
    command on the same line)."""
    p = P(tokens(text), 0, text)
    seq = sequence(p, False)
    if len(seq.parts) != 1:
        return Block(seq.parts, [], (0, len(text)))
    return seq.parts[0]


def parse(line, env, delayed):
    """The line read: (a Seq of commands, the expanded line). Its %VAR%
    expanded now, as cmd reads a line; !VAR! (delayed) left for each
    command as it runs (resolve.py: a `set` before it on the line counts)."""
    expanded = expand(line, env, False)
    p = P(tokens(expanded), 0, expanded)
    seq = sequence(p, False)
    tok = peek(p, True)
    if tok is not None:
        raise unreadable("unexpected " + repr(tok.text))
    return seq, expanded
