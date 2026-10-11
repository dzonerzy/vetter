"""fnmatch.fnmatchcase in zrun's strict subset: `*` any run of characters
(`/` too), `?` one, `[abc]`, `[a-z]`, `[!abc]` (`]` first is itself), a
`[` without its `]` itself."""


def match(name, pattern):
    return _match(name, 0, pattern, 0)


def _class_end(pattern, j):
    """The index past the class starting at pattern[j] == '[', or -1."""
    k = j + 1
    if k < len(pattern) and pattern[k] == "!":
        k += 1
    if k < len(pattern) and pattern[k] == "]":
        k += 1
    while k < len(pattern) and pattern[k] != "]":
        k += 1
    if k >= len(pattern):
        return -1
    return k + 1


def _in_class(c, pattern, j, end):
    """Is c in the class pattern[j:end] ('[' ... ']')?"""
    k = j + 1
    negate = False
    if pattern[k] == "!":
        negate = True
        k += 1
    found = False
    first = True
    while k < end - 1:
        lo = pattern[k]
        if lo == "]" and not first:
            break
        first = False
        if k + 2 < end - 1 and pattern[k + 1] == "-":
            hi = pattern[k + 2]
            if lo <= c <= hi:
                found = True
            k += 3
        else:
            if c == lo:
                found = True
            k += 1
    return found != negate


def _match(name, i, pattern, j):
    # (backtracking on the last `*` only: linear for common patterns)
    star_j = -1
    star_i = 0
    while i < len(name):
        if j < len(pattern):
            p = pattern[j]
            if p == "*":
                star_j = j
                star_i = i
                j += 1
                continue
            if p == "?":
                i += 1
                j += 1
                continue
            if p == "[":
                end = _class_end(pattern, j)
                if end > 0:
                    if _in_class(name[i], pattern, j, end):
                        i += 1
                        j = end
                        continue
                elif name[i] == "[":
                    i += 1
                    j += 1
                    continue
            elif p == name[i]:
                i += 1
                j += 1
                continue
        if star_j >= 0:
            star_i += 1
            i = star_i
            j = star_j + 1
            continue
        return False
    while j < len(pattern) and pattern[j] == "*":
        j += 1
    return j == len(pattern)
