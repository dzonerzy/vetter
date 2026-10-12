"""`pytest --update-golden`: the recorded expectations (golden.py) written
from what vetter gives now, not compared. Every test has a home of its own:
what the hook remembers (~/.local/state/vetter) never the user's."""

import os

import golden
import pytest
import zrun

# (zrun's cache where it is for this user, fixed now: the tests' homes are
# their own, and a cache found from one of them was thrown away with it,
# vetter compiled again each run)
zrun.configure(cache=os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "zrun"))


@pytest.fixture(autouse=True)
def own_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true",
                     help="record what vetter gives now as tests/golden's expectations")
    # (building the executable and libvetter with Zig takes minutes: only
    # asked for, and kept in .pytest_cache for the same sources)
    parser.addoption("--build", action="store_true",
                     help="build the standalone hook and libvetter, and test them")
    # (running the corpus for real takes a minute or more, and bubblewrap,
    # strace, or Windows from WSL: only asked for)
    parser.addoption("--oracle", action="store_true",
                     help="run the corpus and its variants for real (tools/oracle): Linux, and Windows from WSL")


def pytest_configure(config):
    if config.getoption("--update-golden"):
        golden.UPDATE.append(True)
    if not hasattr(config, "workerinput") and not config.getoption("collectonly"):
        # (vetter compiled once, here, before pytest-xdist's workers start:
        # they load it from zrun's cache)
        import shared

        shared.warm()
