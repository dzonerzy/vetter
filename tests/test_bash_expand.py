"""Word expansion (vetter/shells/bash/expand.py), run by zrun (the reference
mode and compiled, strict): the fields of every word, assignment and
here-document, and the variables after, as recorded (tests/golden), on the
corpus and generated words, for several sets of variables."""

import pytest
import zgram

import shared
from golden import compare, load_golden
from vetter.shells.bash import expand, syntax

VARIABLES = [
    {},
    {"a": "x y", "b": "", "n": None, "arr": ["1", "2 3", ""], "@": ["p1", "p 2", "*"], "g": "*.txt",
     "p": "/usr/local/bin", "x": "ab:cd/ef.tar.gz", "ref": "p", "U": "straße Ǆx", "e": []},
    {"IFS": ":", "x": "ab:cd::e", "@": [], "a": " x  y ", "arr": ["a:b", "c"], "ref": "1"},
    {"IFS": None, "a": "x y", "@": ["1", "2"], "arr": ["q r"]},
    {"IFS": "", "a": "x y", "@": ["1", "2"], "x": "a*b"},
]


def fields_of(fields):
    out = []
    for f in fields:
        parts = []
        for p in f.parts:
            if isinstance(p, expand.Dynamic):
                parts.append(["dyn", expand.dynamic_text(p)])
            else:
                parts.append(p)
        out.append([parts, f.glob, f.splits, expand.field_static(f), expand.field_known(f), expand.field_text(f)])
    return out


def walk(node, variables, home, out):
    for c in node.children:
        r = c.rule
        if r == "word" or r == "cmd_name":
            out.append(fields_of(expand.expand_word(c, variables, home, True)))
            out.append(fields_of(expand.expand_word(c, variables, home, False)))
        elif r == "assignment":
            value = None
            for k in c.children:
                if k.rule == "word":
                    value = k
            out.append(fields_of([expand.expand_assignment(value, variables, home)]))
        walk(c, variables, home, out)
    return out


def expand_all(rt, command, values, home):
    try:
        p = syntax.parse(rt, command)
    except zgram.ParseError:
        return "no"
    except ValueError:
        return "no"
    # (values: (name, value, is a list) tuples, a tuple a list's items: a
    # Python dict or list given is shared, Python's)
    variables = expand.Variables({})
    for name, v, is_list in values:
        variables.values[name] = [x for x in v] if is_list else v
    out = walk(p.tree, variables, home, [])
    for d in p.docs:
        if d.body is not None:
            out.append(fields_of([expand.expand_heredoc(d.body, variables)]))
    after = []
    for k, v in variables.values.items():
        after.append([k, "UNKNOWN" if expand.is_unknown(v) else v])
    return [out, after]


@pytest.fixture(scope="module")
def program():
    return shared.program()


@pytest.mark.parametrize("mode", ["python", "compiled"])
def test_as_recorded(program, mode):
    cases = load_golden("bash_expand")
    got = []
    for c in cases:
        command, k, home = c["in"]
        given = tuple((n, tuple(v) if isinstance(v, list) else v, isinstance(v, list)) for n, v in VARIABLES[k].items())
        got.append(program.call("expand", command, given, home, mode=mode))
    compare("bash_expand", cases, got)
