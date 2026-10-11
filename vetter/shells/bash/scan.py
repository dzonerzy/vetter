"""bash's lexer where vetter needs it before (or beside) the grammar:
here-documents found as bash's lexer finds them, $'...' decoded,
backticks' text unescaped. An unreadable command: ValueError("unreadable:
...").
"""

from dataclasses import dataclass


@dataclass
class Heredoc:
    """A here-document: its `<<` operator's position, its delimiter's value,
    whether its body is expanded (an unquoted delimiter), whether tabs are
    stripped (`<<-`), its body's span (the delimiter line excluded), and
    where the delimiter line ends."""

    op_start: int
    delimiter: str
    expanded: bool
    strip_tabs: bool
    body_start: int
    body_end: int
    end: int


def at(text, i, s):
    """Does text have s at i?"""
    return text[i : i + len(s)] == s


def find(text, c, i):
    """The index of c in text from i, or -1."""
    n = len(text)
    while i < n:
        if text[i] == c:
            return i
        i += 1
    return -1


def unreadable(why):
    return ValueError("unreadable: " + why)


def _word_start(text, j, in_word_at):
    return j == 0 or (text[j - 1] in " \t\n;&|()<>" and j != in_word_at)


def heredocs(text):
    """Every here-document of the command, in order: its operator (outside
    quotes, comments and expansions, `<<<` aside), its delimiter word, and
    the body bash reads for it after the newline ending that line."""
    docs = []
    pending = []
    i = 0
    n = len(text)
    # (what the scanner is inside: '$(' a command or process substitution,
    # '(' a subshell, '{' a ${...}, 'a' an arithmetic $((...)), '"' double
    # quotes)
    stack = []
    # (just after a substitution: still in the word, `$()#x` isn't a comment)
    in_word_at = -1
    while i < n:
        c = text[i]
        top = stack[len(stack) - 1] if len(stack) > 0 else ""
        if c == "\\":
            i += 2
            continue
        if top == '"':
            # (in double quotes: only substitutions open, and they're
            # scanned: `"$(cat <<E ...)"` has a here-document)
            if c == '"':
                stack.pop()
                i += 1
                continue
            if c != "`" and c != "$":
                i += 1
                continue
        elif c == "'" and top != "a":
            j = find(text, "'", i + 1)
            i = n if j < 0 else j + 1
            continue
        elif c == "$" and at(text, i, "$'"):
            i = _skip_ansi(text, i + 2)
            continue
        elif c == '"':
            stack.append('"')
            i += 1
            continue
        if c == "`":
            i = _skip_backtick(text, i + 1)
            continue
        if c == "$" and at(text, i, "$(("):
            stack.append("a")
            i += 3
            continue
        if c == "$" and at(text, i, "$("):
            stack.append("$(")
            i += 2
            continue
        if c == "$" and at(text, i, "${"):
            stack.append("{")
            i += 2
            continue
        if top == "a":
            if c == "(":
                stack.append("a(")
            elif at(text, i, "))"):
                stack.pop()
                i += 2
                in_word_at = i
                continue
            i += 1
            continue
        if top == "a(":
            if c == ")":
                stack.pop()
            i += 1
            continue
        if top == "{":
            if c == "}":
                stack.pop()
            i += 1
            continue
        if c == "#" and _word_start(text, i, in_word_at):
            j = find(text, "\n", i)
            i = n if j < 0 else j
            continue
        if c == "(":
            stack.append("$(" if i > 0 and text[i - 1] in "<>" else "(")
            i += 1
            continue
        if c == ")":
            if len(stack) > 0 and (stack[len(stack) - 1] == "(" or stack[len(stack) - 1] == "$("):
                if stack.pop() == "$(":
                    in_word_at = i + 1
            i += 1
            continue
        if at(text, i, "<<<"):
            # (a here-string: its word is on the line)
            i += 3
            continue
        if at(text, i, "<<"):
            op_start = i
            strip = at(text, i, "<<-")
            i += 3 if strip else 2
            while i < n and text[i] in " \t":
                i += 1
            delim, quoted, i = _read_delimiter(text, i)
            if delim is None:
                raise unreadable("a here-document without its delimiter")
            pending.append((op_start, delim, not quoted, strip))
            continue
        if c == "\n" and len(pending) > 0:
            i += 1
            for op_start, delim, expanded, strip in pending:
                body_start = i
                while True:
                    if i >= n:
                        # (bash: "here-document delimited by end-of-file")
                        docs.append(Heredoc(op_start, delim, expanded, strip, body_start, n, n))
                        break
                    j = find(text, "\n", i)
                    line_end = n if j < 0 else j
                    line = text[i:line_end]
                    # (an expanded body's `\`-newline joins two lines,
                    # before the delimiter is looked for: `EO\` `F` ends it)
                    while expanded and _continued(line) and line_end < n:
                        j = find(text, "\n", line_end + 1)
                        nxt = n if j < 0 else j
                        line = line[: len(line) - 1] + text[line_end + 1 : nxt]
                        line_end = nxt
                    if (line.lstrip("\t") if strip else line) == delim:
                        docs.append(Heredoc(op_start, delim, expanded, strip, body_start, i, line_end))
                        # (the next body starts on the next line)
                        i = line_end + 1
                        break
                    i = line_end + 1
            pending = []
            continue
        i += 1
    # (no newline after the operator's line: an empty body to the end)
    for op_start, delim, expanded, strip in pending:
        docs.append(Heredoc(op_start, delim, expanded, strip, n, n, n))
    return docs


def _continued(line):
    """Does the line end in a `\\` that escapes its newline?"""
    k = len(line)
    while k > 0 and line[k - 1] == "\\":
        k -= 1
    return (len(line) - k) % 2 == 1


def _skip_ansi(text, i):
    j = ansi_end(text, i)
    return len(text) if j < 0 else j + 1


def ansi_end(text, i):
    """The `'` closing a $'...' whose text starts at i (-1: none)."""
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "'":
            return i
        i += 1
    return -1


def _skip_dq(text, i):
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        if c == "`":
            i = _skip_backtick(text, i + 1)
            continue
        if c == "$" and at(text, i, "$("):
            i = skip_parens(text, i + 2)
            continue
        if c == "$" and at(text, i, "${"):
            j = find(text, "}", i)
            i = n if j < 0 else j + 1
            continue
        i += 1
    return n


def _skip_backtick(text, i):
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`":
            return i + 1
        i += 1
    return n


def skip_parens(text, i):
    """Past the `)` closing a `$(` (quotes inside skipped)."""
    depth = 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = find(text, "'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            i = _skip_dq(text, i + 1)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _read_delimiter(text, i):
    """The delimiter word at i, its quotes removed (a quoted one: the body
    isn't expanded), and where it ends; (None, False, i) if there's none."""
    out = []
    quoted = False
    n = len(text)
    start = i
    while i < n and text[i] not in " \t\n;&|<>()":
        c = text[i]
        if c == "$" and at(text, i, "$'"):
            # (decoded: `<<$'\''` ends at a line `'`)
            quoted = True
            j = ansi_end(text, i + 2)
            if j < 0:
                return None, False, start
            out.append(ansi_decode(text[i + 2 : j]))
            i = j + 1
        elif c == "$" and at(text, i, '$"'):
            # ($"..." is "...")
            i += 1
        elif c == "'":
            quoted = True
            j = find(text, "'", i + 1)
            if j < 0:
                return None, False, start
            out.append(text[i + 1 : j])
            i = j + 1
        elif c == '"':
            quoted = True
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    out.append(text[j + 1])
                    j += 2
                    continue
                out.append(text[j])
                j += 1
            if j >= n:
                return None, False, start
            i = j + 1
        elif c == "\\" and at(text, i, "\\\n"):
            # (a line continuation, gone before the word is read: `<<VE\`
            # newline `TTER` is VETTER, unquoted)
            i += 2
        elif c == "\\":
            quoted = True
            if i + 1 < n:
                out.append(text[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    if i == start:
        return None, False, start
    return "".join(out), quoted, i


def mask(text, docs):
    """The text with the here-documents' bodies (and delimiter lines)
    blanked, newlines kept: the grammar reads that."""
    if len(docs) == 0:
        return text
    chars = list(text)
    for d in docs:
        for i in range(d.body_start, d.end):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def unescape_backtick(s, in_dq):
    special = '$`\\"' if in_dq else "$`\\"
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in special:
            out.append(s[i + 1])
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _simple_escape(e):
    """$'\\e': the character, or "" when e isn't a simple escape."""
    if e == "a":
        return "\a"
    if e == "b":
        return "\b"
    if e == "e" or e == "E":
        return "\x1b"
    if e == "f":
        return "\f"
    if e == "n":
        return "\n"
    if e == "r":
        return "\r"
    if e == "t":
        return "\t"
    if e == "v":
        return "\v"
    if e == "\\" or e == "'" or e == '"' or e == "?":
        return e
    return ""


def ansi_decode(s):
    """The text of a $'...' string, its escapes decoded as bash does."""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        e = s[i + 1]
        simple = _simple_escape(e)
        if simple != "":
            out.append(simple)
            i += 2
        elif e in "01234567":
            j = i + 1
            while j < n and j < i + 4 and s[j] in "01234567":
                j += 1
            out.append(chr(int(s[i + 1 : j], 8) & 0xFF))
            i = j
        elif e == "x":
            j = i + 2
            while j < n and j < i + 4 and s[j] in "0123456789abcdefABCDEF":
                j += 1
            out.append(chr(int(s[i + 2 : j], 16)) if j > i + 2 else "\\x")
            i = j
        elif e == "u" or e == "U":
            width = 4 if e == "u" else 8
            j = i + 2
            while j < n and j < i + 2 + width and s[j] in "0123456789abcdefABCDEF":
                j += 1
            out.append(chr(int(s[i + 2 : j], 16)) if j > i + 2 else "\\" + e)
            i = j
        elif e == "c" and i + 2 < n:
            out.append(chr(ord(s[i + 2]) & 0x1F))
            i += 3
        else:
            out.append("\\" + e)
            i += 2
    return "".join(out)
