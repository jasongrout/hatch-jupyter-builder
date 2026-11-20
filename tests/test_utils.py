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


@pytest.fixture(autouse=True)
def git_home(tmp_path_factory, monkeypatch):
    """Keep the user's and the system's git config (e.g. core.hooksPath) out of the tests."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return home


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
def test_install_pre_commit_hook_existing(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _git("init", str(repo), cwd=tmp_path)
    monkeypatch.chdir(repo)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("custom hook")
    utils.install_pre_commit_hook()
    assert hook.read_text() == "custom hook"


@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
@pytest.mark.parametrize("scope", ["local", "global"])
def test_install_pre_commit_hook_hooks_path(tmp_path, monkeypatch, caplog, git_home, scope):
    # Like `pre-commit install`, no hook is installed when core.hooksPath is set.
    repo = tmp_path / "repo"
    hooks_path = tmp_path / "custom-hooks"
    _git("init", str(repo), cwd=tmp_path)
    _git("config", f"--{scope}", "core.hooksPath", str(hooks_path), cwd=repo)
    assert (git_home / ".gitconfig").exists() == (scope == "global")
    monkeypatch.chdir(repo)
    utils.install_pre_commit_hook()
    assert not hooks_path.exists()
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()
    assert "core.hooksPath is set" in caplog.text


@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
def test_install_pre_commit_hook_subdirectory(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _git("init", str(repo), cwd=tmp_path)
    (repo / "package").mkdir()
    monkeypatch.chdir(repo / "package")
    utils.install_pre_commit_hook()
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


def test_install_pre_commit_hook_marks_hook_as_pre_commit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(".git/hooks")
    utils.install_pre_commit_hook()
    # `pre-commit install` replaces hooks that contain this ID instead of chaining them.
    assert "138fd403232d2ddd5efb44317e38bf03" in Path(".git/hooks/pre-commit").read_text()


def _fake_executable(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / name
    exe.write_text(f'#!/bin/sh\necho "{name} $*"\n')
    exe.chmod(0o755)
    return exe


def _install_and_run_hook(tmp_path, monkeypatch, python, path_dirs=()):
    monkeypatch.setattr(sys, "executable", str(python))
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    monkeypatch.chdir(repo)
    utils.install_pre_commit_hook()
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([*map(str, path_dirs), env["PATH"]])
    return subprocess.run(
        [str(repo / ".git" / "hooks" / "pre-commit")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="runs the hook with bash")
def test_install_pre_commit_hook_runs_install_python(tmp_path, monkeypatch):
    # The path to the Python is quoted in the hook.
    python = _fake_executable(tmp_path / "env with space" / "bin", "python")
    result = _install_and_run_hook(tmp_path, monkeypatch, python)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("python -m pre_commit hook-impl")


@pytest.mark.skipif(sys.platform == "win32", reason="runs the hook with bash")
def test_install_pre_commit_hook_falls_back_to_path(tmp_path, monkeypatch):
    # E.g. uv builds in a temporary environment that is deleted after the build.
    python = tmp_path / "deleted-env" / "bin" / "python"
    bin_dir = tmp_path / "bin"
    _fake_executable(bin_dir, "pre-commit")
    result = _install_and_run_hook(tmp_path, monkeypatch, python, [bin_dir])
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("pre-commit hook-impl")


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


@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
def test_install_pre_commit_hook_ignores_git_dir(tmp_path, monkeypatch):
    # GIT_DIR (set e.g. inside git hooks) must not redirect the hook to another repository.
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    _git("init", str(repo), cwd=tmp_path)
    _git("init", str(other), cwd=tmp_path)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.chdir(repo)
    utils.install_pre_commit_hook()
    assert (repo / ".git" / "hooks" / "pre-commit").exists()
    assert not (other / ".git" / "hooks" / "pre-commit").exists()


def _git_output_unusable_path(cmd, **kwargs):
    # E.g. Cygwin git called from a native Windows Python.
    if "rev-parse" in cmd:
        return "/cygdrive/c/does-not-exist\n.git\n"
    raise subprocess.CalledProcessError(1, cmd)


def _git_not_executable(*args, **kwargs):
    raise PermissionError(13, "Permission denied")


@pytest.mark.parametrize("check_output", [_git_output_unusable_path, _git_not_executable])
def test_install_pre_commit_hook_unusable_git(tmp_path, monkeypatch, check_output):
    # Problems running git fall back to .git/hooks instead of raising.
    monkeypatch.chdir(tmp_path)
    os.makedirs(".git/hooks")
    monkeypatch.setattr(utils, "which", lambda _: "git")
    monkeypatch.setattr(utils.subprocess, "check_output", check_output)
    utils.install_pre_commit_hook()
    assert Path(".git/hooks/pre-commit").exists()
