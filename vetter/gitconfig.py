"""A repository's own git config, read where the hook decides: the keys in
it that make git run a program (core.fsmonitor, core.pager, filter.x.clean,
alias.x = !cmd...). What the user set up globally is theirs; a repository's
local config can be the agent's (git config core.fsmonitor ./w, or a repo
it made in /tmp), and runs with every git command there.

    found = runs_from(repo_config("/p"))   # ["core.fsmonitor=./w", ...]
"""

from os.path import exists, isdir, isfile


def join(d, name):
    return d + name if d.endswith("/") or d.endswith("\\") else d + "/" + name


def dirname(p):
    """The folder p is in ("/" for /x, C:/ for C:/x); p itself at a root."""
    s = p.rstrip("/\\")
    i = max(s.rfind("/"), s.rfind("\\"))
    if i < 0:
        return p
    if i == 0:
        return "/"
    if i == 2 and s[1] == ":":
        return s[:3]
    return s[:i]

# Keys whose value is a program or command git runs (lowercase; * any name)
RUNNING_KEYS = ("core.fsmonitor", "core.hookspath", "core.pager", "core.editor", "core.sshcommand", "core.askpass",
                "core.gitproxy", "diff.external", "diff.*.textconv", "diff.*.command", "filter.*.clean",
                "filter.*.smudge", "filter.*.process", "merge.*.driver", "credential.helper", "credential.*.helper",
                "gpg.program", "gpg.*.program", "sequence.editor", "remote.*.uploadpack", "remote.*.receivepack",
                "uploadpack.packobjectshook", "include.path", "includeif.*.path", "pager.*", "interactive.difffilter",
                "web.browser", "browser.*.cmd", "man.*.cmd", "mergetool.*.cmd", "difftool.*.cmd")

# core.fsmonitor's values that run nothing
QUIET = ("", "false", "no", "off", "0", "true", "yes", "on", "1")


def git_dir(cwd):
    """The .git directory of the repository cwd is in (a worktree's .git
    file followed), or None."""
    d = cwd
    while d is not None and d != "":
        g = join(d, ".git")
        if isdir(g):
            return g
        if isfile(g):
            try:
                text = open(g, encoding="utf-8").read()
            except OSError:
                return None
            except UnicodeDecodeError:
                return None
            if text.startswith("gitdir:"):
                target = text[7:].strip()
                return target if target.startswith("/") or (len(target) > 1 and target[1] == ":") \
                    else join(d, target)
            return None
        parent = dirname(d)
        if parent == d:
            return None
        d = parent
    return None


def repo_config(cwd):
    """The text of the repository's local config (its worktree's too), or
    ""."""
    g = git_dir(cwd)
    if g is None:
        return ""
    out = ""
    for name in ("config", "config.worktree"):
        f = join(g, name)
        if exists(f):
            try:
                out += open(f, encoding="utf-8").read() + "\n"
            except OSError:
                pass
            except UnicodeDecodeError:
                # (one that isn't UTF-8: what's in it unknown, assumed to run)
                out += "[include]\npath = ?\n"
    return out


def entries(text):
    """(key, value) of a git config's text: section.sub.key, lowercase but
    the subsection."""
    out = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line == "" or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("["):
            end = line.find("]")
            head = line[1:end] if end > 0 else line[1:]
            name, _, sub = head.partition(" ")
            sub = sub.strip()
            if sub.startswith('"') and sub.endswith('"') and len(sub) > 1:
                sub = sub[1 : len(sub) - 1]
            section = name.lower() + ("." + sub if sub != "" else "")
            continue
        key, eq, value = line.partition("=")
        value = value.strip()
        if len(value) > 1 and value.startswith('"') and value.endswith('"'):
            value = value[1 : len(value) - 1]
        out.append((section + "." + key.strip().lower(), value if eq != "" else "true"))
    return out


def key_matches(key, pattern):
    kp = key.split(".")
    pp = pattern.split(".")
    if len(pp) == 2 and pp[1] == "*":
        return len(kp) >= 2 and kp[0] == pp[0]
    if len(kp) != len(pp):
        return False
    for a, b in zip(kp, pp):
        if b != "*" and a.lower() != b:
            return False
    return True


def runs_from(text):
    """"key=value" of each setting that makes git run something."""
    out = []
    for key, value in entries(text):
        running = False
        for pattern in RUNNING_KEYS:
            if key_matches(key, pattern):
                running = True
        if key == "core.fsmonitor" and value.lower() in QUIET:
            running = False
        if key.startswith("alias.") and value.startswith("!"):
            running = True
        if running:
            out.append(key + "=" + value)
    return out
