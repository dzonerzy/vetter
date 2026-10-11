"""bash read (vetter/shells/bash/syntax.py), run by zrun (the reference
mode and compiled, strict): the tree, here-documents, backticks and errors,
as recorded (tests/golden), on the corpus and generated commands."""

import pytest
import zgram

from golden import compare, load_golden
from vetter import engine
from vetter.shells.bash import syntax


def shape(n):
    """(rule, start, end) of every node, in order"""
    out = [(n.rule, n.start, n.end)]
    for c in n.children:
        out += shape(c)
    return out


def ticks(bt):
    return [(b.start, shape(b.command.tree), ticks(b.command.backticks)) for b in bt]


def read(rt, command):
    try:
        p = syntax.parse(rt, command)
    except zgram.ParseError as e:
        return ("not bash", str(e))
    except ValueError as e:
        return ("unreadable", str(e))
    docs = [(d.heredoc.op_start, d.heredoc.delimiter, d.heredoc.body_start, d.heredoc.body_end,
             d.body is not None) for d in p.docs]
    return ("ok", shape(p.tree), docs, ticks(p.backticks))


@pytest.fixture(scope="module")
def program():
    lang = engine.language({"read": read})
    return engine.load(lang, {"read": ["command"]})


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_as_recorded(program, mode):
    cases = load_golden("bash_syntax")
    compare("bash_syntax", cases, [program.call("read", *c["in"], mode=mode) for c in cases])
