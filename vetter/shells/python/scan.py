"""What Python's tokenizer does before its grammar, for python.zgram: each
logical line made one line (inside brackets, a newline, a comment, a
backslash-newline a space; a backslash-newline anywhere else too), its
indentation as marks (INDENT before the first token of a line indented
more than the one before; a DEDENT for each level a line goes back to, and
at the end), \\r\\n made \\n; strings, f-strings and their nested
expressions left as they are.

    marked = mark(text)    # ValueError("unreadable: ...") when Python wouldn't read it
"""

INDENT = "\x0e"
DEDENT = "\x0f"

STRING_PREFIX = "rRbBuUfF"


def unreadable(why):
    return ValueError("unreadable: " + why)


def is_ident(c):
    return (c >= "a" and c <= "z") or (c >= "A" and c <= "Z") or (c >= "0" and c <= "9") or c == "_" \
        or ord(c) >= 128


def prefix_at(text, q):
    """The string prefix before the quote at q (rb, f, Rf...), "" none."""
    k = q
    while k > 0 and q - k < 2 and text[k - 1] in STRING_PREFIX:
        k -= 1
    if k > 0 and is_ident(text[k - 1]):
        # (a name ending in r, b, f: not a prefix: `bar"x"` isn't Python)
        return ""
    return text[k:q]


def string_end(text, i, f):
    """Where the string whose quote is at i ends (just after its closing
    quotes); -1: not closed. An f-string's {expressions} are skipped as
    code (their strings their own, its quotes inside them allowed)."""
    n = len(text)
    q = text[i]
    triple = text[i : i + 3] == q * 3
    j = i + 3 if triple else i + 1
    while j < n:
        c = text[j]
        if c == "\\":
            # (in an f-string a backslash doesn't escape a brace: `\{{` is
            # a backslash and a {)
            j += 1 if f and text[j + 1 : j + 2] in ("{", "}") else 2
            continue
        if triple and text[j : j + 3] == q * 3:
            return j + 3
        if not triple and c == q:
            return j + 1
        if not triple and c == "\n":
            return -1
        if f and c == "{":
            if text[j : j + 2] == "{{":
                j += 2
                continue
            j = field_end(text, j)
            if j < 0:
                return -1
            continue
        j += 1
    return -1


def field_end(text, j):
    """Just after the } closing the f-string field opening at j."""
    n = len(text)
    depth = 0
    while j < n:
        c = text[j]
        if c == '"' or c == "'":
            end = string_end(text, j, "f" in prefix_at(text, j).lower())
            if end < 0:
                return -1
            j = end
            continue
        if c == "{" or c == "(" or c == "[":
            depth += 1
        elif c == "}" or c == ")" or c == "]":
            depth -= 1
            if depth == 0 and c == "}":
                return j + 1
        j += 1
    return -1


def mark(text):
    # (Python's newlines: \r\n, and \r alone too, in strings as well)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    stack = [0]
    depth = 0
    i = 0
    n = len(text)
    line_start = True
    while i < n:
        if line_start and depth == 0:
            # (a line's indentation: a tab to the next multiple of 8, a form
            # feed back to 0, as Python counts)
            j = i
            col = 0
            while j < n and (text[j] == " " or text[j] == "\t" or text[j] == "\f"):
                if text[j] == "\t":
                    col = (col // 8 + 1) * 8
                elif text[j] == " ":
                    col += 1
                else:
                    col = 0
                j += 1
            out.append(text[i:j])
            i = j
            line_start = False
            if i >= n:
                break
            c = text[i]
            blank = c == "\n" or c == "#" or (c == "\r" and text[i + 1 : i + 2] == "\n") \
                or (c == "\\" and text[i + 1 : i + 2] == "\n")
            if not blank:
                if col > stack[len(stack) - 1]:
                    stack.append(col)
                    out.append(INDENT)
                else:
                    while col < stack[len(stack) - 1]:
                        stack.pop()
                        out.append(DEDENT)
                    if col != stack[len(stack) - 1]:
                        raise unreadable("an indentation that matches no outer level")
            continue
        c = text[i]
        if c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            if depth > 0:
                out.append(" " * (j - i))
            else:
                out.append(text[i:j])
            i = j
            continue
        if c == "\\" and text[i + 1 : i + 2] == "\n":
            out.append("  ")
            i += 2
            continue
        if c == "\\" and text[i + 1 : i + 3] == "\r\n":
            out.append("   ")
            i += 3
            continue
        if c == "\r" and text[i + 1 : i + 2] == "\n":
            i += 1
            continue
        if c == "\n":
            if depth > 0:
                out.append(" ")
            else:
                out.append("\n")
                line_start = True
            i += 1
            continue
        if c == '"' or c == "'":
            end = string_end(text, i, "f" in prefix_at(text, i).lower())
            if end < 0:
                raise unreadable("a string that isn't closed")
            out.append(text[i:end])
            i = end
            continue
        if c == "(" or c == "[" or c == "{":
            depth += 1
        elif c == ")" or c == "]" or c == "}":
            if depth == 0:
                raise unreadable("a bracket closed that wasn't opened")
            depth -= 1
        out.append(c)
        i += 1
    if depth > 0:
        raise unreadable("a bracket that isn't closed")
    tail = "".join(out)
    if len(stack) > 1:
        if not tail.endswith("\n"):
            tail += "\n"
        tail += DEDENT * (len(stack) - 1)
    return tail
