"""The oracles (tools/oracle), with `pytest --oracle`: commands run for
real, what they did against what vetter decided. Linux: the bash corpus
vetter allows, and every attack's variants it allows, run in bubblewrap
under strace: none did what vetter didn't see. Windows (from WSL): the
cmd and PowerShell proofs, and their variants vetter allows, on the real
shells: each proof's effect happens and vetter stops it; no variant it
allows has the effect."""

import shutil
import subprocess

import pytest

from tools.oracle import linux, windows


@pytest.fixture
def oracle(pytestconfig):
    if not pytestconfig.getoption("--oracle"):
        pytest.skip("run for real only with --oracle")


def linux_ready():
    if not shutil.which("bwrap") or not shutil.which("strace"):
        return False
    r = subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/", "/", "true"], capture_output=True)
    return r.returncode == 0


def windows_ready():
    if not shutil.which("cmd.exe") or not shutil.which("powershell.exe"):
        return False
    r = subprocess.run(["cmd.exe", "/d", "/c", "ver"], capture_output=True, cwd="/mnt/c")
    return r.returncode == 0


def test_linux_allowed(oracle, capsys):
    """What the corpus' allowed commands do, run: nothing vetter didn't see."""
    if not linux_ready():
        pytest.skip("needs bubblewrap and strace")
    code = linux.main([])
    assert code == 0, capsys.readouterr().out


def test_linux_variants(oracle, capsys):
    """Every attack written ~40 ways: none vetter allows does what it does."""
    if not linux_ready():
        pytest.skip("needs bubblewrap and strace")
    code = linux.main(["--mutate"])
    assert code == 0, capsys.readouterr().out


def test_windows_proofs(oracle, capsys):
    """The audits' cmd and PowerShell proofs: Windows does them, vetter stops them."""
    if not windows_ready():
        pytest.skip("needs Windows' cmd.exe and powershell.exe (WSL)")
    code = windows.main([])
    assert code == 0, capsys.readouterr().out


def test_windows_variants(oracle, capsys):
    """Reading, writing, deleting in a protected folder ~1,400 ways: none vetter allows does it."""
    if not windows_ready():
        pytest.skip("needs Windows' cmd.exe and powershell.exe (WSL)")
    code = windows.main(["--mutate"])
    assert code == 0, capsys.readouterr().out
