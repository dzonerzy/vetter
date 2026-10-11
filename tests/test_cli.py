"""The command line: check, check --json, why (--all, --rule), test
(--coverage), lint, on fixed commands and policies, written as recorded in
tests/golden/cli.json.gz (from the Python vetter that came before)."""

import contextlib
import io
import os

import pytest

from golden import load_golden
from vetter import cli

BAD_POLICY = """policy bad
let unused = /opt
allow "build" maek
deny "rm" rm
deny "rm again" rm -rf
ask "git" git pusj
tests
  deny rm -rf x
  allow git status
  ask ls
"""

BROKEN_POLICY = "policy broken\nallow \"x\" run maek\n"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as e:
            code = e.code
    return out.getvalue(), err.getvalue(), code


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    d = tmp_path_factory.mktemp("cli")
    (d / "stock-log-off.vet").write_text("policy t\nlog off\nuse stock\n")
    (d / "bad.vet").write_text(BAD_POLICY)
    (d / "broken.vet").write_text(BROKEN_POLICY)
    return str(d)


def test_as_recorded(tmp):
    for case in load_golden("cli"):
        argv = [a.replace("$TMP", tmp).replace("$STOCK", str(cli.STOCK)) for a in case["argv"]]
        out, err, code = run(argv)
        expect = [case[k].replace("$TMP", tmp).replace("$STOCK", str(cli.STOCK)) for k in ("stdout", "stderr")]
        assert (out, err, code) == (expect[0], expect[1], case["code"]), argv


LOAD_ERRORS = {
    "nouse.vet": ('policy x\nuse nothing\n', "nouse.vet:2: use nothing: there's no policy nothing"),
    "nodrop.vet": ('policy x\nallow "a" git status\ndrop "nope"\n',
                   "nodrop.vet:3: drop 'nope': no rule before has that reason"),
    "syntax.vet": ('policy x\nallow "unterminated git\n', "syntax.vet: line 3, col 1: expected '\\\\' or '\"'"),
}


def test_policies_that_dont_load(tmp_path):
    """The loader's errors: check says them (on stderr, `policy: ...`),
    lint and test (on stdout); exit 2"""
    for name, (text, message) in LOAD_ERRORS.items():
        path = tmp_path / name
        path.write_text(text)
        where = str(tmp_path / message)
        assert run(["check", "--policy", str(path), "ls"]) == ("", f"policy: {where}\n", 2)
        assert run(["lint", "--policy", str(path)]) == (f"{where}\n", "", 2)
        assert run(["test", "--policy", str(path)]) == (f"{where}\n", "", 2)


def test_cwd_relative_policy(tmp, monkeypatch):
    """--policy relative to the working directory, as the shell gives it"""
    monkeypatch.chdir(tmp)
    out, _, code = run(["check", "--policy", "stock-log-off.vet", "--cwd", "/home/u/p", "--home", "/home/u",
                        "git status"])
    assert code == 0 and out.startswith("allow: ")
    assert os.path.exists(os.path.join(tmp, "stock-log-off.vet"))
