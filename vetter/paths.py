"""Paths on either system, as vetter compares them: Windows ones (C:\\x,
\\\\server, HKCU:) and POSIX ones, made canonical (forward slashes, a drive
letter in upper case, `.` and `..` resolved), joined, compared (Windows'
names by each character's uppercase: case_key).
"""


def _letter(c):
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


def drive_len(p):
    """The length of a drive at p's start (C:, HKCU:), else 0."""
    i = 0
    while i < len(p) and _letter(p[i]):
        i += 1
    if i > 0 and i < len(p) and p[i] == ":":
        return i + 1
    return 0


def is_windows(p):
    return drive_len(p) > 0 or p.startswith("\\\\") or p.startswith("//")


def to_slashes(p):
    return p.replace("\\", "/")


def is_abs(p):
    p = to_slashes(p)
    if p.startswith("/"):
        return True
    n = drive_len(p)
    return n > 0 and (n == len(p) or p[n] == "/")


def normpath(p):
    """posixpath.normpath"""
    if p == "":
        return "."
    initial = 0
    if p.startswith("/"):
        initial = 1
        if p.startswith("//") and not p.startswith("///"):
            initial = 2
    comps = p.split("/")
    out = []
    for c in comps:
        if c == "" or c == ".":
            continue
        if c != ".." or (initial == 0 and len(out) == 0) or (len(out) > 0 and out[len(out) - 1] == ".."):
            out.append(c)
        elif len(out) > 0:
            out.pop()
    s = "/".join(out)
    if initial > 0:
        s = "/" * initial + s
    if s == "":
        return "."
    return s


def norm(p):
    """The path made canonical: Windows ones with / and a drive letter in
    upper case, `.` and `..` resolved."""
    if not is_windows(p) and "\\" not in p:
        return normpath(p)
    p = windows_same(to_slashes(p))
    if p.startswith("//"):
        return "//" + normpath(p[2:]).lstrip("/")
    n = drive_len(p)
    if n > 0:
        rest = normpath("/" + p[n:].lstrip("/"))
        return p[:n].upper() + rest
    return normpath(p)


# (this machine, as a UNC host: \\localhost\C$\x is C:\x)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1", ".")


def windows_same(p):
    """The path Windows takes p (with /) to: \\\\?\\ and \\\\.\\ dropped
    (\\\\?\\UNC\\h\\s: \\\\h\\s), this machine's admin share a drive
    (\\\\localhost\\C$\\x: C:\\x), each name without the dots and spaces it
    ends with, and without a stream (x::$DATA: x)."""
    if p.startswith("//?/") or p.startswith("//./"):
        # (a drive's, a share's; \\.\pipe\x, a device: as it is)
        rest = p[4:]
        if fold(rest[:4]) == "unc/":
            p = "//" + rest[4:]
        elif len(rest) >= 2 and _letter(rest[0]) and rest[1] == ":":
            p = rest
    head = None
    if p.startswith("//"):
        host, _, rest = p[2:].partition("/")
        share, slash, tail = rest.partition("/")
        if fold(host) in LOCAL_HOSTS and len(share) == 2 and _letter(share[0]) and share[1] == "$":
            p = share[0] + ":/" + tail
        elif host != "" and share != "" and slash != "":
            head = "//" + host + "/" + share
    if head is None:
        # (a file system's: a drive letter's; a registry's, HKCU:, as it is)
        if len(p) < 2 or not _letter(p[0]) or p[1] != ":":
            return p
        head = p[:2]
    names = p[len(head) :].split("/")
    for k in range(len(names)):
        name = names[k]
        if name == "" or name == "." or name == "..":
            continue
        colon = name.find(":")
        if colon > 0 and k == len(names) - 1:
            # (a stream of the file: the file)
            name = name[:colon]
        while len(name) > 0 and (name[len(name) - 1] == "." or name[len(name) - 1] == " "):
            name = name[: len(name) - 1]
        names[k] = name
    return head + "/".join(names)


def join(cwd, p):
    """p from cwd (None: unknown)."""
    if is_abs(p) or (is_windows(p) and p.startswith("//")):
        return norm(p)
    if drive_len(p) > 0:
        # (C:x: relative to a drive's own directory: not known here)
        return None
    if cwd is None:
        return None
    if is_windows(cwd) and to_slashes(p).startswith("/"):
        # (\x on Windows: the current drive's root)
        return norm(cwd[:2] + to_slashes(p))
    return norm(to_slashes(cwd).rstrip("/") + "/" + to_slashes(p))


def program_name(p):
    """A program's name from how it's called: its path's last part, without
    a Windows executable's extension (C:\\x\\Git.exe: Git)."""
    i = len(p)
    while i > 0 and p[i - 1] != "/" and p[i - 1] != "\\":
        i -= 1
    name = p[i:]
    if name == "":
        name = p
    key = case_key(name)
    if key.endswith(".EXE") or key.endswith(".COM") or key.endswith(".CMD") or key.endswith(".BAT"):
        name = name[: len(name) - 4]
    return name


def case_key(s):
    """s as Windows compares names (paths.case_key): each character's
    uppercase, one whose uppercase is several characters itself (ß)."""
    if len(s.encode()) == len(s):
        return s.upper()
    out = ""
    for c in s:
        u = c.upper()
        out += u if len(u) == 1 else c
    return out


def fold(s):
    """case_key(s) with its ASCII letters lowercased (paths.fold)."""
    # (ASCII: its letters' case key, lowercased, is its lowercase)
    if len(s.encode()) == len(s):
        return s.lower()
    out = ""
    for c in case_key(s):
        if c >= "A" and c <= "Z":
            out += chr(ord(c) + 32)
        else:
            out += c
    return out


def same(a, b):
    if is_windows(a) or is_windows(b):
        return case_key(a) == case_key(b)
    return a == b


def inside(path, place):
    """path is place or under it."""
    if is_windows(path) or is_windows(place):
        path = case_key(path)
        place = case_key(place)
    return path == place or path.startswith(place.rstrip("/") + "/")
