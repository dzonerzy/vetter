"""`pytest --update-golden`: the recorded expectations (golden.py) written
from what vetter gives now, not compared. Every test has a home of its own:
what the hook remembers (~/.local/state/vetter) never the user's."""

import golden
import pytest


@pytest.fixture(autouse=True)
def own_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true",
                     help="record what vetter gives now as tests/golden's expectations")


def pytest_configure(config):
    if config.getoption("--update-golden"):
        golden.UPDATE.append(True)
