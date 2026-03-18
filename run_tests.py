#!/usr/bin/env python3
"""
run_tests.py — Integration test suite for gt.

Every test creates real git repos in /tmp, runs gt commands against them,
and verifies behavior end-to-end. No mocks. No monkeypatching.

Usage:
    python run_tests.py                   run all tests
    python run_tests.py -v                verbose (show gt output)
    python run_tests.py -k sync           only tests whose name contains 'sync'
    python run_tests.py -k "push or cfg"  multiple keywords
    python run_tests.py --list            list all test names
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import traceback
from pathlib import Path

GT_ROOT = Path(__file__).parent.resolve()
PYTHON  = sys.executable
CLI     = GT_ROOT / "cli.py"   # cli.py  — main entry point
INIT    = GT_ROOT / "init.py"  # init.py — setup wizard

# ── Colors ────────────────────────────────────────────────────────────────────

_C = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

class C:
    R = "\033[0m"  if _C else ""
    B = "\033[1m"  if _C else ""
    D = "\033[2m"  if _C else ""
    G = "\033[32m" if _C else ""
    E = "\033[31m" if _C else ""
    I = "\033[36m" if _C else ""

# ── Registry ──────────────────────────────────────────────────────────────────

_TESTS: list[tuple[str, object]] = []

def test(name: str):
    def decorator(fn):
        _TESTS.append((name, fn))
        return fn
    return decorator

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], *, cwd: Path, env: dict | None = None,
        stdin: str = "") -> subprocess.CompletedProcess:
    merged = {**os.environ, "PYTHONPATH": str(GT_ROOT), **(env or {})}
    return subprocess.run(
        cmd, cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        input=stdin, env=merged,
    )


def git(args: list[str], *, cwd: Path, **kw) -> subprocess.CompletedProcess:
    return run(["git"] + args, cwd=cwd, **kw)


def gt(args: list[str], *, cwd: Path, stdin: str = "",
       env: dict | None = None, verbose: bool = False) -> subprocess.CompletedProcess:
    result = run([PYTHON, str(CLI)] + args,
                 cwd=cwd, stdin=stdin, env=env)
    if verbose:
        out = (result.stdout + result.stderr).strip()
        if out:
            print(textwrap.indent(out, "    "))
    return result


def init_gt(*, cwd: Path, develop: str, protected: str,
            remote: str = "origin", verbose: bool = False) -> subprocess.CompletedProcess:
    stdin = f"{develop}\n{protected}\n{remote}\ny\n"
    result = run(
        [PYTHON, str(INIT)],
        cwd=cwd, stdin=stdin,
    )
    if verbose:
        out = (result.stdout + result.stderr).strip()
        if out:
            print(textwrap.indent(out, "    "))
    return result


class Repo:
    """Isolated git environment: one bare remote, one or more clones."""

    def __init__(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="gt-test-"))
        self.bare = self._tmp / "remote.git"
        git(["init", "--bare", "-q", str(self.bare)], cwd=self._tmp)

    def clone(self, alias: str = "dev") -> Path:
        dest = self._tmp / alias
        git(["clone", "-q", str(self.bare), str(dest)], cwd=self._tmp)
        git(["config", "user.email", "test@gt.dev"], cwd=dest)
        git(["config", "user.name",  "Test"], cwd=dest)
        return dest

    def bootstrap(self, path: Path, *branches: str) -> None:
        """Create initial commit then create and push each branch."""
        (path / "README.md").write_text("init\n")
        git(["add", "."], cwd=path)
        git(["commit", "-q", "-m", "chore: init"], cwd=path)
        git(["push", "-q", "origin", "HEAD"], cwd=path)
        for branch in branches:
            git(["checkout", "-q", "-b", branch], cwd=path)
            git(["push", "-q", "origin", branch], cwd=path)
        if branches:
            git(["checkout", "-q", branches[0]], cwd=path)

    def cleanup(self):
        shutil.rmtree(self._tmp, ignore_errors=True)


# ── Assertions ────────────────────────────────────────────────────────────────

class Fail(AssertionError):
    pass

def assert_ok(r: subprocess.CompletedProcess, label: str = "command") -> None:
    if r.returncode != 0:
        out = (r.stdout + r.stderr).strip()
        raise Fail(f"{label} exited {r.returncode} (expected 0).\n{textwrap.indent(out, '  ')}")

def assert_fail(r: subprocess.CompletedProcess, label: str = "command") -> None:
    if r.returncode == 0:
        raise Fail(f"{label} exited 0 (expected non-zero).")

def assert_in(fragment: str, text: str, label: str = "output") -> None:
    if fragment not in text:
        raise Fail(f"{label} does not contain {repr(fragment)}.\nActual:\n{textwrap.indent(text, '  ')}")

def assert_not_in(fragment: str, text: str, label: str = "output") -> None:
    if fragment in text:
        raise Fail(f"{label} should NOT contain {repr(fragment)}.")

def assert_branch(path: Path, expected: str) -> None:
    actual = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path).stdout.strip()
    if actual != expected:
        raise Fail(f"Branch is '{actual}', expected '{expected}'.")

def assert_cfg(path: Path, key: str, expected: str) -> None:
    actual = git(["config", "--local", key], cwd=path).stdout.strip()
    if actual != expected:
        raise Fail(f".git/config {key} = '{actual}', expected '{expected}'.")

def assert_hooks(path: Path, hooks: list[str], *, installed: bool = True) -> None:
    hooks_dir = path / ".git" / "hooks"
    for h in hooks:
        exists = (hooks_dir / h).exists()
        if installed and not exists:
            raise Fail(f"Hook not installed: {h}")
        if not installed and exists:
            raise Fail(f"Hook should not be installed: {h}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════════════════════════

@test("no_config_blocks_all_commands")
def _(verbose):
    """Commands abort with a clear message when .git/config [gt] is not set."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)

        for cmd in ("status", "check", "sync", "merge"):
            r = gt([cmd], cwd=dev, verbose=verbose)
            assert_fail(r, label=f"gt {cmd}")
            assert_in("not configured", r.stdout + r.stderr, label=f"gt {cmd}")
            assert_in("init.py", r.stdout + r.stderr, label=f"gt {cmd}")
    finally:
        repo.cleanup()


@test("init_happy_path")
def _(verbose):
    """gt init: valid config → writes .git/config and installs all hooks."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)

        r = init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)
        assert_ok(r, label="gt init")
        assert_in("gt is ready", r.stdout)

        assert_cfg(dev, "gt.develop-branch",   "demo/dev")
        assert_cfg(dev, "gt.protected-branch",  "pre-release")
        assert_cfg(dev, "gt.remote",            "origin")
        assert_hooks(dev, ["pre-commit", "pre-push", "post-checkout", "pre-rebase"])
    finally:
        repo.cleanup()


@test("init_invalid_branch_blocks_install")
def _(verbose):
    """gt init: non-existent branch → nothing installed, nothing written."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release")

        r = init_gt(cwd=dev, develop="ghost/branch", protected="pre-release", verbose=verbose)
        assert_fail(r, label="gt init with bad branch")
        assert_in("not found", r.stdout + r.stderr)

        r2 = git(["config", "--local", "gt.develop-branch"], cwd=dev)
        if r2.returncode == 0 and r2.stdout.strip():
            raise Fail("gt.develop-branch was written despite failure")
        assert_hooks(dev, ["pre-push"], installed=False)
    finally:
        repo.cleanup()


@test("init_same_branch_rejected")
def _(verbose):
    """gt init: develop == protected → rejected before validation."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release")

        r = init_gt(cwd=dev, develop="pre-release", protected="pre-release", verbose=verbose)
        assert_fail(r, label="gt init same branch")
        assert_in("cannot be the same", r.stdout + r.stderr)
    finally:
        repo.cleanup()


@test("status_shows_branch_info")
def _(verbose):
    """gt status: shows correct branch name after init."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        r = gt(["status"], cwd=dev, verbose=verbose)
        assert_ok(r, label="gt status")
        assert_in("demo/dev", r.stdout)
    finally:
        repo.cleanup()


@test("sync_rebases_and_pushes")
def _(verbose):
    """gt sync: rebases onto origin/protected and pushes successfully."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)

        # Add a commit to pre-release (simulates a merged PR from someone else)
        git(["checkout", "-q", "pre-release"], cwd=dev)
        (dev / "hotfix.txt").write_text("hotfix\n")
        git(["add", "."], cwd=dev)
        git(["commit", "-q", "-m", "fix: hotfix"], cwd=dev)
        git(["push", "-q", "origin", "pre-release"], cwd=dev)

        # Developer's own work
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        (dev / "feature.txt").write_text("feature\n")
        git(["add", "."], cwd=dev)
        git(["commit", "-q", "-m", "feat: new feature"], cwd=dev)
        git(["push", "-q", "origin", "demo/dev"], cwd=dev)

        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        r = gt(["sync"], cwd=dev, verbose=verbose)
        assert_ok(r, label="gt sync")
        assert_in("synced successfully", r.stdout)

        log = git(["log", "--oneline", "demo/dev"], cwd=dev).stdout
        assert_in("hotfix", log, label="rebase result")
    finally:
        repo.cleanup()


@test("sync_already_uptodate")
def _(verbose):
    """gt sync: no-op and clean exit when already up to date."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        r = gt(["sync"], cwd=dev, verbose=verbose)
        assert_ok(r, label="gt sync uptodate")
        assert_in("up to date", r.stdout)
    finally:
        repo.cleanup()


@test("sync_blocked_when_dirty")
def _(verbose):
    """gt sync: aborts when working tree is dirty."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        (dev / "dirty.txt").write_text("uncommitted\n")

        r = gt(["sync"], cwd=dev, verbose=verbose)
        assert_fail(r, label="gt sync dirty")
        assert_in("not clean", r.stdout + r.stderr)
    finally:
        repo.cleanup()


@test("pre_push_blocks_direct_push_to_protected")
def _(verbose):
    """pre-push hook blocks direct git push to protected branch."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        git(["checkout", "-q", "pre-release"], cwd=dev)
        (dev / "bad.txt").write_text("bad\n")
        git(["add", "."], cwd=dev)
        git(["commit", "-q", "-m", "bad: direct"], cwd=dev)

        r = git(["push", "origin", "pre-release"], cwd=dev)
        assert_fail(r, label="direct push to protected")
        assert_in("not allowed", r.stdout + r.stderr)
    finally:
        repo.cleanup()


@test("pre_push_bypass_allows_gt_merge_push")
def _(verbose):
    """GT_BYPASS_HOOK=1 allows gt merge to push to the protected branch."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        git(["checkout", "-q", "pre-release"], cwd=dev)
        (dev / "legit.txt").write_text("legit\n")
        git(["add", "."], cwd=dev)
        git(["commit", "-q", "-m", "chore: merge commit"], cwd=dev)

        r = git(["push", "origin", "pre-release"], cwd=dev,
                env={"GT_BYPASS_HOOK": "1"})
        assert_ok(r, label="bypass push")
    finally:
        repo.cleanup()


@test("merge_full_flow_no_conflicts")
def _(verbose):
    """gt merge: completes full flow, lands feature on protected branch."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)

        (dev / "feature.txt").write_text("feature\n")
        git(["add", "."], cwd=dev)
        git(["commit", "-q", "-m", "feat: new feature"], cwd=dev)
        git(["push", "-q", "origin", "demo/dev"], cwd=dev)

        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        r = gt(["merge"], cwd=dev, stdin="y\ny\n", verbose=verbose)
        assert_ok(r, label="gt merge")
        assert_in("integrated into", r.stdout)
        assert_branch(dev, "demo/dev")

        git(["fetch", "origin"], cwd=dev)
        log = git(["log", "--oneline", "origin/pre-release"], cwd=dev).stdout
        assert_in("feat: new feature", log, label="feature on protected branch")
    finally:
        repo.cleanup()


@test("merge_blocked_when_dirty")
def _(verbose):
    """gt merge: aborts immediately when working tree is dirty."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        (dev / "dirty.txt").write_text("uncommitted\n")

        r = gt(["merge"], cwd=dev, verbose=verbose)
        assert_fail(r, label="gt merge dirty")
        assert_in("not clean", r.stdout + r.stderr)
    finally:
        repo.cleanup()


@test("two_developers_same_protected_branch")
def _(verbose):
    """Alice and Bob work on different branches and both integrate into pre-release."""
    repo = Repo()
    try:
        setup = repo.clone("setup")
        repo.bootstrap(setup, "pre-release", "alice/dev", "bob/dev")

        # Alice
        alice = repo.clone("alice")
        git(["checkout", "-q", "-b", "alice/dev", "--track", "origin/alice/dev"], cwd=alice)
        (alice / "alice.txt").write_text("alice\n")
        git(["add", "."], cwd=alice)
        git(["commit", "-q", "-m", "feat: alice"], cwd=alice)
        git(["push", "-q", "origin", "alice/dev"], cwd=alice)
        init_gt(cwd=alice, develop="alice/dev", protected="pre-release", verbose=verbose)

        # Bob
        bob = repo.clone("bob")
        git(["checkout", "-q", "-b", "bob/dev", "--track", "origin/bob/dev"], cwd=bob)
        (bob / "bob.txt").write_text("bob\n")
        git(["add", "."], cwd=bob)
        git(["commit", "-q", "-m", "feat: bob"], cwd=bob)
        git(["push", "-q", "origin", "bob/dev"], cwd=bob)
        init_gt(cwd=bob, develop="bob/dev", protected="pre-release", verbose=verbose)

        # Alice merges first
        r = gt(["merge"], cwd=alice, stdin="y\ny\n", verbose=verbose)
        assert_ok(r, label="alice merge")

        # Bob syncs (picks up Alice's work) then merges
        r = gt(["sync"], cwd=bob, verbose=verbose)
        assert_ok(r, label="bob sync")
        r = gt(["merge"], cwd=bob, stdin="y\ny\n", verbose=verbose)
        assert_ok(r, label="bob merge")

        git(["fetch", "origin"], cwd=setup)
        log = git(["log", "--oneline", "origin/pre-release"], cwd=setup).stdout
        assert_in("alice", log, label="alice on pre-release")
        assert_in("bob",   log, label="bob on pre-release")
    finally:
        repo.cleanup()


@test("configure_show_and_update")
def _(verbose):
    """gt configure --show displays config; gt configure updates values."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev", "demo/v2")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        r = gt(["configure", "--show"], cwd=dev, verbose=verbose)
        assert_ok(r, label="configure --show")
        assert_in("demo/dev",  r.stdout)
        assert_in("pre-release", r.stdout)
        assert_in(".git/config", r.stdout)

        # Update develop_branch to demo/v2
        r2 = gt(["configure"], cwd=dev, stdin="demo/v2\n\n\n", verbose=verbose)
        assert_ok(r2, label="configure update")
        assert_cfg(dev, "gt.develop-branch", "demo/v2")
    finally:
        repo.cleanup()


@test("pre_commit_blocks_conflict_markers")
def _(verbose):
    """pre-commit hook blocks commits that contain git conflict markers."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)

        (dev / "bad.txt").write_text("<<<<<<< HEAD\ncode\n=======\nother\n>>>>>>> branch\n")
        git(["add", "bad.txt"], cwd=dev)

        r = git(["commit", "-m", "bad: conflict markers"], cwd=dev)
        assert_fail(r, label="commit with conflict markers")
        assert_in("Conflict markers", r.stdout + r.stderr)
    finally:
        repo.cleanup()


@test("uninstall_removes_everything")
def _(verbose):
    """gt init --uninstall removes hooks and .git/config [gt] section."""
    repo = Repo()
    try:
        dev = repo.clone()
        repo.bootstrap(dev, "pre-release", "demo/dev")
        git(["checkout", "-q", "demo/dev"], cwd=dev)
        init_gt(cwd=dev, develop="demo/dev", protected="pre-release", verbose=verbose)
        assert_hooks(dev, ["pre-push", "pre-commit"])

        r = run(
            [PYTHON, str(INIT), "--uninstall"],
            cwd=dev,
        )
        assert_ok(r, label="gt init --uninstall")
        assert_hooks(dev, ["pre-push", "pre-commit", "post-checkout", "pre-rebase"],
                     installed=False)

        r2 = git(["config", "--local", "gt.develop-branch"], cwd=dev)
        if r2.returncode == 0 and r2.stdout.strip():
            raise Fail("gt config should have been removed after uninstall")
    finally:
        repo.cleanup()


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="gt integration tests")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show gt output for each test")
    parser.add_argument("-k", metavar="KEYWORD",
                        help="Filter tests by keyword (use 'or' for multiple)")
    parser.add_argument("--list", action="store_true",
                        help="List all tests and exit")
    args = parser.parse_args()

    if args.list:
        print("\nTests:\n")
        for name, _ in _TESTS:
            print(f"  {name}")
        print()
        return

    tests = [
        (name, fn) for name, fn in _TESTS
        if not args.k
        or any(kw.strip() in name for kw in args.k.split("or"))
    ]

    total   = len(tests)
    skipped = len(_TESTS) - total
    passed  = failed = 0

    print(f"\n{C.B}gt test suite{C.R}  ({total} tests)\n")

    for name, fn in tests:
        print(f"  {C.D}{name:<52}{C.R}", end="", flush=True)
        try:
            fn(verbose=args.verbose)
            print(f"{C.G}PASS{C.R}")
            passed += 1
        except (AssertionError, Fail) as e:
            print(f"{C.E}FAIL{C.R}")
            print(f"\n{C.E}  ✖  {e}{C.R}\n")
            failed += 1
        except Exception:
            print(f"{C.E}ERROR{C.R}")
            traceback.print_exc()
            failed += 1

    color = C.G if failed == 0 else C.E
    skip_note = f"   {skipped} skipped" if skipped else ""
    fail_note = f"   {failed} failed"   if failed  else ""
    print(f"\n{color}{C.B}{'─'*56}")
    print(f"  {passed}/{total} passed{fail_note}{skip_note}")
    print(f"{'─'*56}{C.R}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()