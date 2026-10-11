"""What the agent's earlier commands wrote: a file a command wrote (or the
agent's editing tools: Claude Code's Write and Edit...) run by a later
command is the agent's own code, `run generated`; one it downloaded, `run
downloaded`: as in one command (actions.generated). The hook keeps them in
~/.local/state/vetter/written.tsv, a line a path: "time<TAB>kind<TAB>path";
the last MAX_PATHS, none older than MAX_DAYS.

    w = load(path)                          # {path: kind}
    record_decision(decision, w, path)      # what a command it answered writes
    record(["/p/x.sh"], "generated", path)  # what an editing tool writes
"""

from os import chmod, makedirs, replace
from os.path import exists, getsize
from time import time

from ..policy.actions import BUILD_TOOLS

MAX_PATHS = 4000
MAX_DAYS = 3


def load(path):
    """{path: kind} of what's recorded (none without the file)."""
    out = {}
    if not exists(path):
        return out
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return out
    except UnicodeDecodeError:
        return out
    cutoff = time() - MAX_DAYS * 86400
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) < cutoff:
            continue
        if parts[1] == "generated" or parts[1] == "downloaded":
            out[parts[2]] = parts[1]
    return out


def writes_of(decision, written):
    """(path, kind) of what the decided command writes: its programs' and
    redirections' files; a build tool's when the command wrote something
    itself too, or the build reads what an earlier one wrote (the source
    of what it builds the agent's)."""
    out = []
    builds = []
    for r in decision.parts:
        part = r.part
        kind = "generated"
        reads_written = False
        for a in part.actions:
            if a.verb == "download":
                kind = "downloaded"
            if a.verb == "read" and a.path is not None and a.path in written:
                reads_written = True
        for a in part.actions:
            if a.verb != "write" or a.path is None or a.path == "":
                continue
            if part.name is not None and part.name in BUILD_TOOLS and kind != "downloaded":
                builds.append((a.path, "generated", reads_written))
            else:
                out.append((a.path, kind))
    for path, kind, reads in builds:
        if reads or len(out) > 0:
            out.append((path, kind))
    return out


def record_decision(decision, written, path):
    """What a command the hook answered writes (not one it denies: it
    doesn't run)."""
    if decision.decision == "deny":
        return
    entries = writes_of(decision, written)
    by_kind = {}
    for p, kind in entries:
        if kind not in by_kind:
            by_kind[kind] = []
        by_kind[kind].append(p)
    for kind, paths in by_kind.items():
        record(paths, kind, path)


def record(paths, kind, path):
    """Append paths (absolute) of a kind; never raises: a memory that
    fails isn't a decision that fails."""
    keep = [p for p in paths if p.startswith("/") or (len(p) > 2 and p[1] == ":")]
    if len(keep) == 0:
        return
    try:
        new = not exists(path)
        makedirs(parent_of(path), 0o700, True)
        now = str(int(time()))
        text = ""
        for p in keep:
            if "\n" not in p and "\t" not in p:
                text += now + "\t" + kind + "\t" + p + "\n"
        open(path, "a", encoding="utf-8").write(text)
        if new:
            chmod(path, 0o600)
        trim(path)
    except OSError:
        pass


def parent_of(path):
    i = max(path.rfind("/"), path.rfind("\\"))
    return path[:i] if i > 0 else path


def trim(path):
    # (now and then: past 110% of the cap, back to the cap, old ones dropped)
    if getsize(path) < 60 * MAX_PATHS:
        return
    lines = open(path, encoding="utf-8").read().splitlines()
    if len(lines) <= MAX_PATHS * 11 // 10:
        return
    cutoff = time() - MAX_DAYS * 86400
    keep = []
    for line in lines[len(lines) - MAX_PATHS :]:
        t = line.split("\t", 1)[0]
        if t.isdigit() and int(t) >= cutoff:
            keep.append(line)
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write("\n".join(keep) + "\n")
    chmod(tmp, 0o600)
    replace(tmp, path)
