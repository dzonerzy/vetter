"""Where vetter finds things on this machine, as the hook and the CLI do:
the home, the policy (--policy, else ~/.config/vetter/policy.vet, else the
stock one; a project's .vetter.vet), the project a directory is in, the
temporary directories, the log. Read as Python reads them (os.name, the
environment, paths: in a standalone program, the system's it runs on).
"""

import os
from os import getenv
from os.path import exists, isdir, isfile, realpath

from . import paths
from .agents import written
from .policy.language import BUILTIN, add_project, load

STOCK = BUILTIN["stock"]
PROJECT_POLICY = ".vetter.vet"


def windows():
    """Whether this runs on Windows (os.name read here: a standalone
    build's the system's it runs on)"""
    return os.name == "nt"


def native_shell():
    """The shell an agent runs commands in on this system."""
    return "powershell" if windows() else "bash"


def home_dir():
    """os.path.expanduser("~")"""
    if windows():
        h = getenv("USERPROFILE")
        if h is None:
            drive = getenv("HOMEDRIVE") or ""
            h = drive + (getenv("HOMEPATH") or "")
        return h
    h = getenv("HOME")
    if h is None:
        return "~"
    return h.rstrip("/") or "/"


def expand_user(p, home):
    if p == "~" or p.startswith("~/") or (windows() and p.startswith("~\\")):
        return home + p[1:]
    return p


def path_text(p):
    """str(pathlib.Path(p)): its separators made one, `.` parts and a
    trailing separator taken out"""
    if windows():
        p = p.replace("/", "\\")
    root = ""
    sep = "\\" if windows() else "/"
    if p.startswith(sep):
        root = sep
        # (POSIX keeps a leading //, not more)
        if not windows() and p.startswith("//") and not p.startswith("///"):
            root = "//"
    parts = [x for x in p.split(sep) if x != "" and x != "."]
    out = root + sep.join(parts)
    return out or "."


def dirname(p):
    """os.path.dirname"""
    i = max(p.rfind("/"), p.rfind("\\")) if windows() else p.rfind("/")
    head = p[:i + 1]
    stripped = head.rstrip("\\/") if windows() else head.rstrip("/")
    if stripped and not (windows() and stripped.endswith(":")):
        return stripped
    return head


def path_join(d, name):
    if d.endswith("/") or (windows() and d.endswith("\\")):
        return d + name
    return d + ("\\" if windows() else "/") + name


def project_policy(cwd, home):
    """The nearest .vetter.vet from cwd up (not past home)."""
    d = realpath(cwd)
    h = realpath(home)
    while True:
        f = path_join(d, PROJECT_POLICY)
        if isfile(f):
            return f
        parent = dirname(d)
        if d == h or parent == d:
            return None
        d = parent


def project_root(cwd, home):
    """The project a directory is in: the nearest one up with a .git or a
    .vetter.vet, not past the home and never the home itself (a dotfiles
    repository); else the directory itself."""
    if not cwd or not isdir(cwd):
        return cwd
    d = realpath(cwd)
    stop = realpath(home) if home else None
    while True:
        if d == stop:
            return cwd
        if exists(path_join(d, ".git")) or isfile(path_join(d, PROJECT_POLICY)):
            return d
        parent = dirname(d)
        if parent == d:
            return cwd
        d = parent


def workspace_project(cwd, home, workspace):
    """The project, given the folder the agent works in (the workspace the
    user opened: Claude Code's CLAUDE_PROJECT_DIR, Cursor's workspace
    roots): it, when the command runs in it (cd'ing into a repository in
    it doesn't make the rest of it elsewhere), unless a repository holds it
    (the larger); never the home, nor /."""
    root = project_root(cwd, home)
    if not workspace or not cwd or not isdir(workspace) or not isdir(cwd):
        return root
    w = realpath(workspace)
    if (home and w == realpath(home)) or w == dirname(w):
        return root
    c = realpath(cwd)
    if c != w and not c.startswith(w.rstrip("/") + "/"):
        return root
    r = realpath(root) if root and isdir(root) else c
    if r != w and w.startswith(r.rstrip("/") + "/"):
        return root
    return w


def load_policy(rt, policy_path, cwd, home):
    """The policy, with the project's own rules first when cwd (None: no
    project) is in a project that has a .vetter.vet (its deny and ask rules
    only: its allow rules, left out, the policy's `ignored`)."""
    if policy_path:
        p = path_text(expand_user(policy_path, home))
        policy = load(rt, read_text(p), p)
    else:
        user = path_text(home + "/.config/vetter/policy.vet")
        if isfile(user):
            policy = load(rt, read_text(user), user)
        else:
            policy = load(rt, STOCK[0], STOCK[1])
    found = project_policy(cwd, home) if cwd is not None else None
    if found is not None:
        policy.ignored = add_project(rt, policy, read_text(found), found)
    # (deciding on this machine: its symbolic links followed, what the
    # agent's earlier commands wrote known)
    policy.follow_links = True
    policy.written = written.load(written_path(home))
    return policy


def read_text(path):
    # (open().read(): what zrun reads natively, a `with` it doesn't compile)
    return open(path, encoding="utf-8").read()


def log_path(home):
    """~/.local/state/vetter/log.jsonl"""
    return path_text(home + "/.local/state/vetter/log.jsonl")


def written_path(home):
    """~/.local/state/vetter/written.tsv (agents/written.py)"""
    return path_text(home + "/.local/state/vetter/written.tsv")


def temp_dirs(home, from_environment):
    """The temporary directories ($temp in a policy): the usual ones on
    Linux, macOS and Windows, and (from_environment) the machine's own (TMPDIR
    on macOS is under /var/folders, Windows' TEMP and TMP)."""
    out = ["/tmp", "/var/tmp", "/private/tmp", "C:/Windows/Temp"]
    if home:
        out.append(paths.norm(home + "/AppData/Local/Temp"))
    if not from_environment:
        return out
    for k in ("TMPDIR", "TEMP", "TMP"):
        v = getenv(k)
        if v and paths.is_abs(v):
            v = paths.norm(v)
            if v not in out:
                out.append(v)
    return out
