"""The bash corpus run for real: each command in a throwaway sandbox
(bubblewrap: the system read-only, a scratch home and project, no
network), traced (strace -ff), and what it did compared with what vetter
decided. Each effect it had (a program run, a file read outside the
system's, a file written or deleted) is decided as a command of its own
(`cat P`, `: > P`, `rm -f P`, `P`); one stricter than vetter's decision
on the whole command is a gap: something the command did that vetter
didn't see.

    python -m tools.oracle.linux [-v] [--all] [--only ID-SUBSTRING] [--timeout S]

A gap where vetter allowed is a bypass; with --all, the commands vetter
asked about are compared too (a deny it only asked about). Nothing outside
the sandbox is touched: the scratch tree is a temporary directory, removed
after.
"""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from tools.corpus import corpus
from tools.oracle import mutate
from vetter import engine
from vetter.cli import STOCK
from vetter.places import project_root
from vetter.policy.language import ORDER, TEST_PLACES

PROJECT, HOME = TEST_PLACES["posix"]
SENTINEL = "VETTER-ORACLE-SENTINEL-7f3a"
# (the system's: what programs read and run there is theirs)
SYSTEM = ("/usr/", "/lib/", "/lib64/", "/lib32/", "/bin/", "/sbin/", "/etc/", "/proc/", "/sys/", "/dev/", "/run/",
          "/var/", "/opt/")
TRACED = ("execve,execveat,open,openat,openat2,creat,truncate,unlink,unlinkat,rmdir,rename,renameat,renameat2,"
          "mkdir,mkdirat,symlink,symlinkat,link,linkat,chdir,fchdir,clone,clone3,fork,vfork")
WRITE_FLAGS = ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND")
# (the tools' own caches and state in the home: what they keep there)
TOOL_STATE = (".cache/", ".gradle/", ".npm/", ".m2/", ".cargo/registry/", ".cargo/git/", ".rustup/", "go/pkg/",
              ".java/", ".local/share/pnpm/", ".yarn/", ".node-gyp/")


def template(root):
    """The scratch tree copied for each case: /home/user (its project, a
    secret, a startup file) and /flag."""
    home = os.path.join(root, "home", "user")
    project = os.path.join(home, "project")
    files = {
        "project/README.md": "readme\n",
        "project/notes.txt": "notes\n",
        "project/src/a.c": "int main(void) { return 0; }\n",
        "project/src/notes.txt": "notes\n",
        "project/docs/notes.txt": "notes\n",
        "project/Makefile": "all:\n\t@echo ok\n",
        "project/package.json": '{"name": "p", "version": "1.0.0", "scripts": {"test": "echo ok", "build": "echo ok"}}\n',
        "project/tests/test_x.py": "def test_x():\n    assert True\n",
        ".bashrc": "# bashrc\n",
        ".ssh/id_rsa": SENTINEL + "\n",
        ".aws/credentials": SENTINEL + "\n",
        "work/notes.txt": "work\n",
        "Documents/x.txt": "doc\n",
    }
    for rel, text in files.items():
        path = os.path.join(home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    subprocess.run(["git", "init", "-q", project], check=True, capture_output=True)
    with open(os.path.join(root, "flag"), "w") as f:
        f.write(SENTINEL + "\n")
    # (/etc/passwd with this user's home the sandbox's: java, ssh find it
    # there, not in $HOME)
    lines = []
    with open("/etc/passwd") as f:
        for line in f.read().splitlines():
            fields = line.split(":")
            if len(fields) == 7 and fields[2] == str(os.getuid()):
                fields[5] = HOME
            lines.append(":".join(fields))
    with open(os.path.join(root, "passwd"), "w") as f:
        f.write("\n".join(lines) + "\n")


def sandboxed(world, out, command, timeout):
    """bwrap's command line: the system read-only, the world's home and
    flag, a tmpfs /tmp, no network; strace's traces into out."""
    argv = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
    for d in ("/usr", "/etc", "/opt", "/var"):
        if os.path.isdir(d):
            argv += ["--ro-bind", d, d]
    for d in ("/bin", "/sbin", "/lib", "/lib64", "/lib32"):
        if os.path.islink(d):
            argv += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            argv += ["--ro-bind", d, d]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--bind", os.path.join(world, "home"), "/home",
             "--ro-bind", os.path.join(world, "flag"), "/flag", "--ro-bind", os.path.join(world, "passwd"),
             "/etc/passwd", "--bind", out, "/oracle", "--chdir", PROJECT, "--",
             "strace", "-ff", "-qq", "-y", "-s", "4096", "-e", "trace=" + TRACED, "-o", "/oracle/t",
             "env", "-i", "HOME=" + HOME, "PATH=/usr/local/bin:/usr/bin:/bin", "TERM=dumb", "USER=user",
             "bash", "-c", command]
    try:
        subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        pass


def split_args(s):
    """strace's arguments, at their top-level commas: strings, [...],
    {...} kept whole."""
    out = []
    depth = 0
    cur = ""
    i = 0
    while i < len(s):
        c = s[i]
        if c == '"':
            j = i + 1
            while j < len(s) and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            cur += s[i : j + 1]
            i = j + 1
            continue
        if c in "[{(":
            depth += 1
        elif c in "]})":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip() != "":
        out.append(cur.strip())
    return out


def unquote(a):
    """A strace string's text ("..." with its escapes); None if it isn't one."""
    if a.endswith("..."):
        a = a[:-3]
    if not (a.startswith('"') and a.endswith('"')):
        return None
    return a[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode(
        "utf-8", "replace")


def fd_path(a):
    """3</home/user/project>: the directory a descriptor is; AT_FDCWD: None."""
    if "<" in a and a.endswith(">"):
        return a[a.index("<") + 1 : -1]
    return None


# (NAME(ARGS) = RET, strace padding the space before =)
CALL = re.compile(r"^(\w+)\((.*)\)\s+=\s+(\S+)")


class Process:
    def __init__(self, cwd):
        self.cwd = cwd


def resolve(cwd, base, path):
    if path is None or path == "":
        # (unlink(""): nothing named)
        return None
    if path.startswith("/"):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(base if base is not None else cwd, path))


def effects(out):
    """What the traced processes did: [(verb, path)], verb run / read /
    write / delete, in order; the first bash (the sandbox's own) left
    out."""
    traces = {}
    for name in os.listdir(out):
        if name.startswith("t."):
            pid = int(name[2:])
            with open(os.path.join(out, name), errors="replace") as f:
                traces[pid] = f.read().splitlines()
    if not traces:
        return []
    procs = {}
    found = []
    # (the root process first, then each child once its parent's clone is read)
    pending = [min(traces)]
    procs[min(traces)] = Process(PROJECT)
    execs = 0
    while pending:
        pid = pending.pop(0)
        proc = procs[pid]
        for line in traces.get(pid, []):
            m = CALL.match(line)
            if m is None:
                continue
            name, body, ret = m.group(1), m.group(2), m.group(3)
            args = split_args(body)
            if len(args) == 0:
                continue
            ok = ret not in ("-1", "?") and not ret.startswith("-")
            if name in ("clone", "clone3", "fork", "vfork") and ok and ret.isdigit():
                child = int(ret)
                procs[child] = Process(proc.cwd)
                pending.append(child)
            elif name == "chdir" and ok:
                proc.cwd = resolve(proc.cwd, None, unquote(args[0]))
            elif name == "fchdir" and ok:
                proc.cwd = fd_path(args[0]) or proc.cwd
            elif name in ("execve", "execveat"):
                path = unquote(args[0] if name == "execve" else args[1])
                full = resolve(proc.cwd, fd_path(args[0]) if name == "execveat" else None, path)
                if ok:
                    execs += 1
                    # (env, then the sandbox's bash: not the command's)
                    if execs > 2:
                        found.append(("run", full))
                elif full is not None and not full.startswith(SYSTEM) and not full.startswith("/usr"):
                    # (a program tried where it isn't: /tmp/x/git)
                    found.append(("run", full))
            elif name in ("open", "creat", "openat", "openat2", "truncate"):
                if name in ("open", "creat", "truncate"):
                    path, base, flags = unquote(args[0]), None, args[1] if len(args) > 1 else ""
                else:
                    path, base, flags = unquote(args[1]), fd_path(args[0]), args[2] if len(args) > 2 else ""
                full = resolve(proc.cwd, base, path)
                writes = name in ("creat", "truncate") or any(f in flags for f in WRITE_FLAGS)
                if full is not None:
                    found.append(("write" if writes else "read", full))
            elif name in ("unlink", "rmdir"):
                found.append(("delete", resolve(proc.cwd, None, unquote(args[0]))))
            elif name == "unlinkat":
                found.append(("delete", resolve(proc.cwd, fd_path(args[0]), unquote(args[1]))))
            elif name in ("rename", "link", "symlink"):
                old, new = unquote(args[0]), unquote(args[1])
                if name == "rename":
                    found.append(("delete", resolve(proc.cwd, None, old)))
                elif name == "link":
                    found.append(("read", resolve(proc.cwd, None, old)))
                found.append(("write", resolve(proc.cwd, None, new)))
            elif name in ("renameat", "renameat2", "linkat"):
                old = resolve(proc.cwd, fd_path(args[0]), unquote(args[1]))
                found.append(("delete" if name != "linkat" else "read", old))
                found.append(("write", resolve(proc.cwd, fd_path(args[2]), unquote(args[3]))))
            elif name == "symlinkat":
                found.append(("write", resolve(proc.cwd, fd_path(args[1]), unquote(args[2]))))
            elif name in ("mkdir", "mkdirat") and ok:
                # (one that's there already, EEXIST: nothing made)
                path = unquote(args[0]) if name == "mkdir" else unquote(args[1])
                base = None if name == "mkdir" else fd_path(args[0])
                found.append(("write", resolve(proc.cwd, base, path)))
    return [(v, p) for v, p in found if p is not None]


def worth_deciding(verb, path):
    """The effects a policy has something to say about: not the system's
    reads and runs, not the sandbox's own."""
    if path.startswith("/oracle") or path.startswith("/proc/") or path.startswith("/dev/"):
        # (the sandbox's; a process's own settings, devices: not files)
        return False
    git = PROJECT + "/.git/"
    if path.startswith(git) and not path.startswith(git + "hooks") and path != git + "config":
        # (git's own bookkeeping: its index, locks, objects; not what runs)
        return False
    for d in TOOL_STATE:
        # (java finds its home in /etc/passwd, not $HOME: any home's)
        if path.startswith("/home/") and "/" + d in path + "/":
            return False
    if verb in ("read", "run") and (path.startswith(SYSTEM) or path in ("/", "/etc", "/usr", "/tmp", "/opt")):
        return False
    if verb == "read" and (path == PROJECT or path == HOME or path == "/home" or path.startswith("/tmp/")):
        return False
    return True


PROBES = {"read": "cat -- {}", "write": ": > {}", "delete": "rm -f -- {}", "run": "{}"}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default=str(STOCK))
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--all", action="store_true", help="compare the commands vetter asked about too")
    ap.add_argument("--only", default="", help="the cases whose id has this in it")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--mutate", action="store_true",
                    help="each attack's variants (mutate.py): the ones vetter allows run and compared")
    args = ap.parse_args(argv)
    p = engine.call("load_text", open(args.policy).read(), args.policy)
    root = project_root(PROJECT, HOME)
    probed = {}

    def decide(command):
        if command not in probed:
            probed[command] = engine.call("check", p, command, "bash", PROJECT, HOME, root, None)
        return probed[command]

    scratch = tempfile.mkdtemp(prefix="vetter-oracle-")
    base = os.path.join(scratch, "template")

    def compared(command, d):
        """What command did, decided: [(verb, path, decision)] stricter
        than d."""
        world = os.path.join(scratch, "w")
        out = os.path.join(scratch, "out")
        shutil.rmtree(world, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
        shutil.copytree(base, world, symlinks=True)
        os.makedirs(out)
        sandboxed(world, out, command, args.timeout)
        found = []
        seen = set()
        for verb, path in effects(out):
            if (verb, path) in seen or not worth_deciding(verb, path):
                continue
            seen.add((verb, path))
            probe = decide(PROBES[verb].format(shlex.quote(path)))
            if verb == "read" and probe.decision != "deny" and path.startswith(HOME + "/"):
                # (a tool reading its settings in the home, ~/.gitconfig:
                # what matters there is a secret's, which is denied)
                continue
            if ORDER[probe.decision] > ORDER[d.decision]:
                found.append((verb, path, probe))
        return found

    def show(found):
        for verb, path, probe in found:
            print(f"      {verb:6s} {path}  -> {probe.decision}: {probe.reason[:90]}")

    gaps = 0
    ran = 0
    try:
        template(base)
        for c in corpus.load():
            if c["shell"] != "bash" or args.only not in c["id"]:
                continue
            command = c["command"].strip("\n")
            if args.mutate:
                if c["expect"] == "allow":
                    continue
                for label, text in mutate.variants(command):
                    d = decide(text)
                    if d.decision != "allow":
                        continue
                    ran += 1
                    found = compared(text, d)
                    if found:
                        gaps += 1
                        print(f"BYPASS {c['id']} ({label}): vetter allow: {d.reason[:80]}")
                        print("      " + text.replace("\n", "\n      "))
                        show(found)
                    elif args.v:
                        print(f"ok  {c['id']} ({label}): allowed, nothing it did stricter")
                continue
            d = decide(command)
            if d.decision != "allow" and not (args.all and d.decision == "ask"):
                continue
            ran += 1
            found = compared(command, d)
            if found:
                gaps += 1
                print(f"GAP {c['id']}: vetter {d.decision}: {d.reason[:90]}")
                show(found)
            elif args.v:
                print(f"ok  {c['id']}: vetter {d.decision}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n{ran} commands run, {gaps} with gaps")
    return 1 if gaps else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
