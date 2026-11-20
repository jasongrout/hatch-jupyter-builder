import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hatch_jupyter_builder import utils


def test_ensure_targets(tmp_path):
    os.chdir(tmp_path)
    Path("foo.txt").touch()
    os.mkdir("bar")
    Path("bar/fizz.md").touch()
    utils.ensure_targets(["foo.txt", "bar/fizz.md"])

    with pytest.raises(ValueError):
        utils.ensure_targets(["bar.txt"])


def test_run():
    cmd = f"{sys.executable} --version"
    utils.run(cmd)
    utils.run(shlex.split(cmd))


def test_normalize_kwargs():
    kwargs = {"foo-bar": "2", "fizz_buzz": "1"}
    result = utils.normalize_kwargs(kwargs)
    assert result == {"foo_bar": "2", "fizz_buzz": "1"}


def test_normalize_cmd():
    cmd = f"{sys.executable} --version"
    assert utils.normalize_cmd(cmd) == shlex.split(cmd)
    assert utils.normalize_cmd(shlex.split(cmd)) == shlex.split(cmd)
    with pytest.raises(ValueError):
        utils.normalize_cmd("does_not_exist")


def test_get_build_func(tmp_path):
    os.chdir(tmp_path)
    test = Path("test.py")
    text = "def foo(target_name, version):\n    return(target_name)\n"
    test.write_text(text, encoding="utf-8")
    callback = utils.get_build_func("test.foo")
    assert callback("fizz", "buzz") == "fizz"

    with pytest.raises(ImportError):
        utils.get_build_func("does_not_exist.bar")

    with pytest.raises(AttributeError):
        utils.get_build_func("test.bar")

    del sys.modules["test"]


def test_should_skip(tmp_path):
    assert not utils.should_skip("a")
    assert not utils.should_skip([])
    os.chdir(tmp_path)
    Path(tmp_path).joinpath("foo.txt").touch()
    assert utils.should_skip(["foo.txt"])
    assert not utils.should_skip(["foo.txt", "bar.txt"])
    Path(tmp_path).joinpath("bar.txt").touch()
    assert utils.should_skip(["bar.txt"])
    assert utils.should_skip(["foo.txt", "bar.txt"])


def test_install_pre_commit_hook(tmp_path):
    os.chdir(tmp_path)
    utils.install_pre_commit_hook()
    assert not os.path.exists(".git/hooks")
    os.makedirs(".git/hooks")
    utils.install_pre_commit_hook()
    assert os.path.exists(".git/hooks/pre-commit")


def _git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
def test_install_pre_commit_hook_git_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _git("init", str(repo), cwd=tmp_path)
    monkeypatch.chdir(repo)
    utils.install_pre_commit_hook()
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    if sys.platform != "win32":
        assert os.access(hook, os.X_OK)


@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
def test_install_pre_commit_hook_worktree(tmp_path, monkeypatch):
    # In a linked worktree, .git is a file and hooks live in the main repository.
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    _git("init", str(repo), cwd=tmp_path)
    _git("commit", "--allow-empty", "-m", "initial", cwd=repo)
    _git("worktree", "add", str(worktree), cwd=repo)
    assert (worktree / ".git").is_file()
    monkeypatch.chdir(worktree)
    utils.install_pre_commit_hook()
    assert (repo / ".git" / "hooks" / "pre-commit").exists()


def test_install_pre_commit_hook_broken_git_file(tmp_path, monkeypatch):
    # A .git file that git cannot use must not raise.
    monkeypatch.chdir(tmp_path)
    Path(".git").write_text("gitdir: does-not-exist\n")
    utils.install_pre_commit_hook()
    assert not (tmp_path / "does-not-exist").exists()
