"""Utilities for hatch_jupyter_builder."""
from __future__ import annotations

import importlib
import logging
import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from shutil import which
from typing import Any, cast

if sys.platform == "win32":  # pragma: no cover
    from subprocess import list2cmdline
else:

    def list2cmdline(cmd_list: Any) -> str:
        """Implementation of list2cmdline for posix systems."""
        return " ".join(map(shlex.quote, cmd_list))


_logger = None


def _get_log() -> logging.Logger:
    global _logger  # noqa: PLW0603
    if _logger:
        return _logger  # type:ignore[unreachable]
    _logger = logging.getLogger(__name__)
    _logger.setLevel(logging.INFO)
    logging.basicConfig(level=logging.INFO)
    return _logger


def npm_builder(
    target_name: str,  # noqa: ARG001
    version: str,
    path: str = ".",
    build_dir: str | None = None,
    source_dir: str | None = None,
    build_cmd: str | None = "build",
    force: bool = False,
    npm: str | list[Any] | None = None,
    editable_build_cmd: str | None = None,
) -> None:
    """Build function for managing an npm installation.

    Parameters
    ----------
    target_name: str
        The build target name ("wheel" or "sdist").
    version: str
        The version name ("standard" or "editable").
    path: str, optional
        The base path of the node package. Defaults to the current directory.
    build_dir: str, optional
        The target build directory.  If this and source_dir are given,
        the JavaScript will only be built if necessary.
    source_dir: str, optional
        The source code directory.
    build_cmd: str, optional
        The npm command to build assets to the build_dir.
    editable_build_cmd: str, optional.
        The npm command to build assets to the build_dir when building in editable mode.
    npm: str or list, optional.
        The npm executable name, or a tuple of ['node', executable].

    Notes
    -----
    The function is a no-op if the `--skip-npm` cli flag is used
        or HATCH_JUPYTER_BUILDER_SKIP_NPM env is set.
    """

    # Check if we are building a wheel from an sdist.
    abs_path = Path(path).resolve()
    log = _get_log()

    if "--skip-npm" in sys.argv or os.environ.get("HATCH_JUPYTER_BUILDER_SKIP_NPM") == "1":
        log.info("Skipping npm install as requested.")
        skip_npm = True
        if "--skip-npm" in sys.argv:
            sys.argv.remove("--skip-npm")
    else:
        skip_npm = False

    if skip_npm:
        log.info("Skipping npm-installation")
        return

    if version == "editable":
        build_cmd = editable_build_cmd or build_cmd

    if isinstance(npm, str):
        npm = [npm]

    # Find a suitable default for the npm command.
    if npm is None:
        is_yarn = (abs_path / "yarn.lock").exists()
        if is_yarn and not which("yarn"):
            log.warning("yarn not found, ignoring yarn.lock file")
            is_yarn = False

        npm = ["yarn"] if is_yarn else ["npm"]

    npm_cmd = normalize_cmd(npm)

    if build_dir and source_dir and not force:
        should_build = is_stale(build_dir, source_dir)
    else:
        should_build = True

    if should_build:
        log.info("Installing build dependencies with npm.  This may take a while...")
        run([*npm_cmd, "install"], cwd=str(abs_path))
        if build_cmd:
            run([*npm_cmd, "run", build_cmd], cwd=str(abs_path))
    else:
        log.info("No build required")


def is_stale(target: str | Path, source: str | Path) -> bool:
    """Test whether the target file/directory is stale based on the source
    file/directory.
    """
    if not Path(source).exists():
        return False
    if not Path(target).exists():
        return True
    target_mtime = recursive_mtime(target) or 0
    return compare_recursive_mtime(source, cutoff=target_mtime)


def compare_recursive_mtime(path: str | Path, cutoff: float, newest: bool = True) -> bool:
    """Compare the newest/oldest mtime for all files in a directory.
    Cutoff should be another mtime to be compared against. If an mtime that is
    newer/older than the cutoff is found it will return True.
    E.g. if newest=True, and a file in path is newer than the cutoff, it will
    return True.
    """
    path = Path(path)
    if path.is_file():
        mt = mtime(path)
        if newest:
            if mt > cutoff:
                return True
        elif mt < cutoff:
            return True
    for dirname, _, filenames in os.walk(str(path), topdown=False):
        for filename in filenames:
            mt = mtime(Path(dirname) / filename)
            if newest:  # Put outside of loop?
                if mt > cutoff:
                    return True
            elif mt < cutoff:
                return True
    return False


def recursive_mtime(path: str | Path, newest: bool = True) -> float:
    """Gets the newest/oldest mtime for all files in a directory."""
    path = Path(path)
    if path.is_file():
        return mtime(path)
    current_extreme = -1.0
    for dirname, _, filenames in os.walk(str(path), topdown=False):
        for filename in filenames:
            mt = mtime(Path(dirname) / filename)
            if newest:  # Put outside of loop?
                if mt >= (current_extreme or mt):
                    current_extreme = mt
            elif mt <= (current_extreme or mt):
                current_extreme = mt
    return current_extreme


def mtime(path: str | Path) -> float:
    """shorthand for mtime"""
    return Path(path).stat().st_mtime


def get_build_func(build_func_str: str) -> Callable[..., None]:
    """Get a build function by name."""
    # Get the build function by importing it.
    mod_name, _, func_name = build_func_str.rpartition(".")

    # If the module fails to import, try importing as a local script.
    try:
        sys.path.insert(0, str(Path.cwd()))
        mod = importlib.import_module(mod_name)
    finally:
        sys.path.pop(0)

    return cast(Callable[..., None], getattr(mod, func_name))


def normalize_cmd(cmd: str | list[Any]) -> list[str]:
    """Normalize a subprocess command."""
    if not isinstance(cmd, list | tuple):
        cmd = shlex.split(cmd, posix=os.name != "nt")
    if not Path(cmd[0]).is_absolute():
        # If a command is not an absolute path find it first.
        cmd_path = which(cmd[0])
        if not cmd_path:
            msg = (
                f"Aborting. Could not find cmd ({cmd[0]}) in path. "
                "If command is not expected to be in user's path, "
                "use an absolute path."
            )
            raise ValueError(msg)
        cmd[0] = cmd_path
    return cmd


def normalize_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the key names in a kwargs input dictionary"""
    result = {}
    for key, value in kwargs.items():
        if isinstance(value, bool):
            value = str(value)  # noqa: PLW2901
        result[key.replace("-", "_")] = value
    return result


def run(cmd: str | list[Any], **kwargs: Any) -> int:
    """Echo a command before running it."""
    kwargs.setdefault("shell", os.name == "nt")
    cmd = normalize_cmd(cmd)
    log = _get_log()
    log.info("> %s", list2cmdline(cmd))
    return subprocess.check_call(cmd, **kwargs)


def ensure_targets(ensured_targets: list[str]) -> None:
    """Ensure that target files are available"""
    for target in ensured_targets:
        if not Path(target).exists():
            msg = f'Ensured target "{target}" does not exist'
            raise ValueError(msg)
    _get_log().info("Ensured target(s) exist!")


def should_skip(skip_if_exists: Any) -> bool:
    """Detect whether all the paths in skip_if_exists exist"""
    if not isinstance(skip_if_exists, list) or not len(skip_if_exists):
        return False
    return all(Path(p).exists() for p in skip_if_exists)


# Environment variables that make git use a repository other than the one
# found from the current directory.
_GIT_REPO_ENV_VARS = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"})


def _get_git_hooks_dir() -> Path | None:
    """Get the hooks directory of the git repository rooted at the current directory.

    In a linked worktree (``git worktree add``) or a submodule, ``.git`` is a
    file pointing at the real git directory, and the hooks directory is in the
    repository's common git directory. Ask git for it rather than assuming
    ``.git/hooks``. ``core.hooksPath`` is deliberately not followed, since it
    may point at a directory shared by other repositories.

    Returns None if the current directory is not the top level of a git
    working tree.
    """
    if not Path(".git").exists():
        return None
    git = which("git")
    if git:
        # Make git find the repository from the current directory, rather than
        # from variables such as GIT_DIR, which are set e.g. inside git hooks.
        env = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_ENV_VARS}
        try:
            toplevel, common_dir = subprocess.check_output(
                [git, "rev-parse", "--show-toplevel", "--git-common-dir"],
                stderr=subprocess.DEVNULL,
                text=True,
                env=env,
            ).splitlines()
            # If ./.git is not a valid git directory, git may have found an
            # enclosing repository instead; ignore it in that case.
            if Path(toplevel).samefile("."):
                return Path(common_dir) / "hooks"
        except (OSError, subprocess.CalledProcessError, ValueError):
            # OSError: git could not be run, or it printed a path this Python
            # cannot open (e.g. Cygwin git with a native Windows Python).
            pass
    if Path(".git").is_dir():
        return Path(".git/hooks")
    return None


def install_pre_commit_hook() -> None:
    """Install a pre-commit hook."""
    data = f"""#!/usr/bin/env bash
INSTALL_PYTHON={sys.executable}
ARGS=(hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit)
HERE="$(cd "$(dirname "$0")" && pwd)"
ARGS+=(--hook-dir "$HERE" -- "$@")
exec "$INSTALL_PYTHON" -m pre_commit "${{ARGS[@]}}"
"""
    log = _get_log()
    hooks_dir = _get_git_hooks_dir()
    if hooks_dir is None:
        log.warning("Refusing to install pre-commit hook since this is not a git repository")
        return

    hooks_dir.mkdir(parents=True, exist_ok=True)
    path = hooks_dir / "pre-commit"
    if not path.exists():
        log.info("Writing pre-commit hook")
        with path.open("w") as fid:
            fid.write(data)
    else:
        log.warning("Refusing to overwrite pre-commit hook")

    mode = path.stat().st_mode
    mode |= (mode & 0o444) >> 2  # copy R bits to X
    path.chmod(mode)
