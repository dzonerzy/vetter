"""One program with every test's entry: vetter compiled once for all of
them (each its own program, it was compiled once for each: minutes), and
before pytest-xdist's workers start (conftest.py), so they load it from
zrun's cache instead of compiling it together.

    program = shared.program()
    program.call("resolve", command, cwd, home, mode="compiled")
"""

from vetter import engine

_program = None


def entries():
    """name -> (function, its parameters), from the tests that call them."""
    import test_bash_expand
    import test_bash_resolve
    import test_bash_syntax
    import test_check
    import test_cmd_resolve
    import test_hook
    import test_log
    import test_ps_resolve

    decide_args = ["command", "shell", "cwd", "home", "text", "filename"]
    return {
        "expand": (test_bash_expand.expand_all, ["command", "values", "home"]),
        "resolve": (test_bash_resolve.resolved, ["command", "cwd", "home"]),
        "ps_resolve": (test_ps_resolve.resolved, ["command", "cwd", "home"]),
        "cmd_resolve": (test_cmd_resolve.resolved, ["command", "cwd", "home"]),
        "decide": (test_check.decide, decide_args),
        "traced": (test_check.traced, decide_args),
        "run_hook": (test_hook.run_hook, ["agent", "policy"]),
        "read": (test_bash_syntax.read, ["command"]),
        "masks": (test_log.masks, ["commands"]),
        "record": (test_log.record, ["path", "agent", "cwd", "command", "decision", "rule_by"]),
        "trim": (test_log.trim, ["path"]),
    }


def program():
    global _program
    if _program is None:
        e = entries()
        lang = engine.language({name: fn for name, (fn, _) in e.items()})
        _program = engine.load(lang, {name: params for name, (_, params) in e.items()})
    return _program


def warm():
    """Compile it now (each entry called once compiled, its code made and
    kept in zrun's cache). The log's record and trim (they write files):
    left to their tests; the hook's in a home of its own, stdin given."""
    import io
    import os
    import sys
    import tempfile

    from vetter.places import STOCK

    p = program()
    with tempfile.TemporaryDirectory() as home:
        policy = os.path.join(home, "p.vet")
        with open(policy, "w", encoding="utf-8") as f:
            f.write("policy t\nlog off\nuse stock\n")
        saved = (os.environ.get("HOME"), sys.stdin, sys.stdout)
        os.environ["HOME"] = home
        sys.stdin = io.StringIO('{"tool_name": "Bash", "tool_input": {"command": "true"}, "cwd": "/home/user/project"}')
        sys.stdout = io.StringIO()
        try:
            p.call("run_hook", "claude", policy, mode="compiled")
        finally:
            if saved[0] is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = saved[0]
            sys.stdin = saved[1]
            sys.stdout = saved[2]
    p.call("read", "true", mode="compiled")
    p.call("expand", "true", (), "/home/user", mode="compiled")
    p.call("resolve", "true", "/home/user/project", "/home/user", mode="compiled")
    p.call("ps_resolve", "Get-Date", "C:/Users/user/project", "C:/Users/user", mode="compiled")
    p.call("cmd_resolve", "dir", "C:/Users/user/project", "C:/Users/user", mode="compiled")
    p.call("masks", ("true",), mode="compiled")
    for entry in ("decide", "traced"):
        p.call(entry, "true", "bash", "/home/user/project", "/home/user", STOCK[0], STOCK[1], mode="compiled")
