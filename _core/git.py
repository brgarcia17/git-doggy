"""
_core/git.py

All git subprocess calls go through this module.
Commands are logged in --verbose mode via ui.detail().
Failures raise GitError — never swallowed silently.
"""
from __future__ import annotations

import subprocess
from . import ui


class GitError(Exception):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd        = cmd
        self.returncode = returncode
        self.stderr     = stderr
        super().__init__(f"git {' '.join(cmd[1:])} → exit {returncode}\n{stderr}")


def _run(
    args: list[str],
    *,
    capture: bool = True,
    allow_fail: bool = False,
) -> subprocess.CompletedProcess:
    ui.detail(f"$ {' '.join(args)}")
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    if not allow_fail and result.returncode != 0:
        raise GitError(args, result.returncode, result.stderr or "")
    return result


# ── Read operations ───────────────────────────────────────────────────────────

def current_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def is_clean() -> bool:
    return _run(["git", "status", "--porcelain"]).stdout.strip() == ""


def dirty_files() -> list[str]:
    r = _run(["git", "status", "--porcelain"])
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def divergence(remote_ref: str, local_ref: str) -> tuple[int, int]:
    """Return (behind, ahead) of local vs remote_ref."""
    r = _run([
        "git", "rev-list", "--left-right", "--count",
        f"{remote_ref}...{local_ref}",
    ])
    parts = r.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])


def log_oneline(base: str, tip: str, max_count: int = 10) -> list[str]:
    r = _run([
        "git", "log", "--oneline",
        f"--max-count={max_count}",
        f"{base}..{tip}",
    ])
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


# ── Write operations ──────────────────────────────────────────────────────────

def fetch(remote: str) -> None:
    _run(["git", "fetch", remote], capture=False)


def checkout(branch: str) -> None:
    _run(["git", "checkout", branch], capture=False)


def pull_ff(remote: str, branch: str) -> None:
    _run(["git", "pull", "--ff-only", remote, branch], capture=False)


def rebase(onto: str) -> subprocess.CompletedProcess:
    """Rebase current branch onto `onto`. Caller checks returncode."""
    return _run(["git", "rebase", onto], allow_fail=True)


def rebase_abort() -> None:
    _run(["git", "rebase", "--abort"], allow_fail=True)


def merge_simulate(branch: str) -> subprocess.CompletedProcess:
    """Dry-run merge (--no-commit --no-ff). Caller must abort afterward."""
    return _run(["git", "merge", "--no-commit", "--no-ff", branch], allow_fail=True)


def merge_abort() -> None:
    _run(["git", "merge", "--abort"], allow_fail=True)


def merge_commit(branch: str, message: str) -> None:
    _run(["git", "merge", "--no-ff", branch, "-m", message], capture=False)


def push(remote: str, branch: str, *, force_with_lease: bool = False) -> None:
    cmd = ["git", "push", remote, branch]
    if force_with_lease:
        cmd.append("--force-with-lease")
    _run(cmd, capture=False)
