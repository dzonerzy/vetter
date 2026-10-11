"""A policy's checks (vetter/policy/checks.py): errors stop it loading,
warnings say what's probably a typo."""

import os
import tempfile

import pytest

from vetter.cli import PolicyError, load_policy
from vetter.policy.language import POLICIES


def warnings(text):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.vet")
        with open(path, "w") as f:
            f.write("policy t\nlog off\nuse stock\n" + text)
        return load_policy(path)[1]


def test_builtin_policies_are_clean():
    for name in ("prelude", "stock"):
        path = POLICIES / f"{name}.vet"
        assert load_policy(str(path))[1] == []


def test_unknown_place_is_an_error():
    with pytest.raises(PolicyError, match=r"t.vet:4:16: buld isn't a place .*did you mean build\?"):
        warnings("deny delete in buld\n")


def test_places_that_are_paths():
    assert warnings("deny delete in ~/x, /etc, C:/Windows, $project/{a,b}, $home/x, HKCU:/Software, *.log\n") == []


def test_project_and_home_are_marked():
    with pytest.raises(PolicyError, match=r"project here is a folder named project: did you mean \$project\?"):
        warnings("deny delete in project/x\n")
    with pytest.raises(PolicyError, match=r"did you mean \$project\?"):
        warnings("deny delete outside project\n")
    with pytest.raises(PolicyError, match=r"\$proj isn't one of vetter's places .*did you mean \$project\?"):
        warnings("deny delete in $proj/x\n")
    assert warnings("deny delete in ./project/x\n") == []
    with pytest.raises(PolicyError, match=r"did you mean \$temp\?"):
        warnings("deny run in temp\n")
    assert warnings("deny run in $temp/x, $home/y\n") == []


def test_program_typos():
    w = warnings('allow "a" gti status\nallow "b" mypy, tsc, cmake\n')
    assert len(w) == 1 and "gti" in w[0] and "did you mean git?" in w[0]


def test_list_name_typo():
    w = warnings('allow "a" wraper\n')
    assert "did you mean wrapper?" in w[0]


def test_subcommands_and_flags():
    w = warnings('allow "a" git pussh, status unless --txtconv, --ext-diff\nallow "b" npm run build\n')
    assert any("git has no subcommand pussh" in x and "push" in x for x in w)
    assert any("--txtconv" in x and "--textconv" in x for x in w)
    assert len(w) == 2


def test_unused_list_and_same_reason():
    w = warnings('let mine = ~/notes\nlet used = ~/x\nask "r" read used\nask "r" write used\n')
    assert any("let mine is never used" in x for x in w)
    assert any('reason "r"' in x for x in w)


def test_redefined_list():
    with pytest.raises(PolicyError, match="redefined|already"):
        warnings("let a = /x\nlet a = /y\nask read a\n")
