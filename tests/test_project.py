"""$project: the git root (or the folder with a .vetter.vet) above the
working directory, never the home."""

from vetter.places import project_root


def test_git_root(tmp_path):
    (tmp_path / "app" / ".git").mkdir(parents=True)
    deep = tmp_path / "app" / "src" / "x"
    deep.mkdir(parents=True)
    assert project_root(str(deep), str(tmp_path)) == str(tmp_path / "app")


def test_vetter_file(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / ".vetter.vet").write_text("policy p\n")
    (tmp_path / "app" / "lib").mkdir()
    assert project_root(str(tmp_path / "app" / "lib"), str(tmp_path)) == str(tmp_path / "app")


def test_not_the_home(tmp_path):
    (tmp_path / ".git").mkdir()
    work = tmp_path / "work"
    work.mkdir()
    assert project_root(str(work), str(tmp_path)) == str(work)


def test_no_project(tmp_path):
    d = tmp_path / "a"
    d.mkdir()
    assert project_root(str(d), str(tmp_path)) == str(d)
    assert project_root("C:/Users/user/project", "C:/Users/user") == "C:/Users/user/project"
