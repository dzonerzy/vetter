"""What a cmd.exe line runs (vetter/shells/cmd), run by zrun (the reference
mode and compiled, strict): the executions and unknowns (or the reason the
line can't be read), as recorded (tests/golden), on the corpus,
hand-written lines and generated ones."""

import pytest

from golden import compare, load_golden
from test_bash_resolve import field, fields, stdin_of
from vetter import engine
from vetter.shells.cmd import resolve


def resolved(rt, command, cwd, home):
    try:
        r = resolve.resolve(rt, command, cwd, home, 0, None, (), False)
    except ValueError as e:
        return ["no", str(e)]
    executions = []
    for e in r.executions:
        reds = []
        for d in e.redirects:
            reds.append([d.fd, d.op, field(d.target) if d.target is not None else None])
        roles = [[x.role, field(x.value), x.option] for x in e.roles]
        env = sorted([[k, field(v)] for k, v in e.env.items()])
        executions.append([fields(e.argv), env, reds, e.cwd, e.span, e.via, stdin_of(e.stdin), e.kind, roles,
                           e.cmdlet, e.readonly])
    unknowns = [[u.reason, u.span, u.via, u.kind, fields(u.paths), u.cwd] for u in r.unknowns]
    return [executions, unknowns, sorted([d for d in r.downloads])]


@pytest.fixture(scope="module")
def program():
    lang = engine.language({"cmd_resolve": resolved})
    return engine.load(lang, {"cmd_resolve": ["command", "cwd", "home"]})


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_as_recorded(program, mode):
    cases = load_golden("cmd_resolve")
    compare("cmd_resolve", cases, [program.call("cmd_resolve", *c["in"], mode=mode) for c in cases])
