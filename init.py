#!/usr/bin/env python3
"""
init.py — Set up gt for a repository.

Run this once per repository, per developer:

    python /path/to/gt/init.py

What it does:
  1. Checks you are inside a git repository
  2. Asks for your personal configuration:
       - Your local develop branch  (e.g. feature/dev)
       - The protected branch       (e.g. pre-release)
       - The remote name            (e.g. origin)
  3. Validates that both branches exist locally or in the remote
  4. Saves config to .git/config [gt]  — never uploaded
  5. Installs hooks into .git/hooks/

If any step fails, nothing is written and nothing is installed.

Options:
  --uninstall    Remove hooks and personal config from this repository
  --dry-run      Preview without making any changes
  --force        Skip the confirmation prompt
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HOOKS    = ["pre-commit", "pre-push", "post-checkout", "pre-rebase"]
GT_ROOT  = Path(__file__).parent.resolve()
IS_WIN   = platform.system() == "Windows"

_WIN_SHIM = """\
@echo off
python "%~dp0{name}" %*
exit /b %errorlevel%
"""

# git config key names
_CFG = {
    "develop_branch":   "develop-branch",
    "protected_branch": "protected-branch",
    "remote":           "remote",
}


# ── Terminal output ───────────────────────────────────────────────────────────

def _color() -> bool:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(  # type: ignore[attr-defined]
                ctypes.windll.kernel32.GetStdHandle(-11), 7,
            )
            return True
        except Exception:
            return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_C = _color()

class C:
    R = "\033[0m"  if _C else ""
    B = "\033[1m"  if _C else ""
    D = "\033[2m"  if _C else ""
    G = "\033[32m" if _C else ""
    Y = "\033[33m" if _C else ""
    E = "\033[31m" if _C else ""
    I = "\033[36m" if _C else ""

def _ok(m: str)   -> None: print(f"{C.G}✔{C.R}  {C.B}{m}{C.R}")
def _info(m: str) -> None: print(f"{C.I}→{C.R}  {m}")
def _warn(m: str) -> None: print(f"{C.Y}⚠{C.R}  {m}")
def _err(m: str)  -> None: print(f"{C.E}✖{C.R}  {C.B}{m}{C.R}", file=sys.stderr)
def _step(t: str) -> None: print(f"\n{C.B}{C.I}── {t}{C.R}")
def _ask(p: str)  -> str:
    try:
        return input(f"  {C.Y}?{C.R}  {p}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# ── Git helpers ───────────────────────────────────────────────────────────────

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw,
    )


def _find_repo(start: Path) -> Path | None:
    cur = start.resolve()
    for _ in range(20):
        if (cur / ".git").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _branch_exists(branch: str, remote: str) -> tuple[bool, str]:
    # Local
    if branch in _run(["git", "branch", "--list", branch]).stdout:
        return True, "local"
    # Remote (live check)
    r = _run(["git", "ls-remote", "--heads", remote, branch])
    if r.returncode == 0 and branch in r.stdout:
        return True, "remote"
    # Cached remote ref
    if _run(["git", "rev-parse", "--verify", f"{remote}/{branch}"]).returncode == 0:
        return True, "remote (cached)"
    return False, ""


def _cfg_write(key: str, value: str) -> bool:
    git_key = _CFG.get(key, key.replace("_", "-"))
    return _run(["git", "config", "--local", f"gt.{git_key}", value]).returncode == 0


def _cfg_remove_section() -> None:
    _run(["git", "config", "--local", "--remove-section", "gt"])


# ── Hook file helpers ─────────────────────────────────────────────────────────

def _make_executable(path: Path) -> None:
    if not IS_WIN:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_hook(name: str, hooks_dir: Path, *, dry_run: bool) -> bool:
    src  = GT_ROOT / "hooks" / name
    dest = hooks_dir / name

    if not src.exists():
        _err(f"Hook source not found: {src}")
        return False

    if dry_run:
        _info(f"[dry-run] Would {'overwrite' if dest.exists() else 'install'}: {name}")
        return True

    if dest.exists():
        dest.rename(dest.with_suffix(".bak"))

    shutil.copy2(src, dest)
    _make_executable(dest)

    if IS_WIN:
        (hooks_dir / f"{name}.cmd").write_text(
            _WIN_SHIM.format(name=name), encoding="utf-8",
        )
        _ok(f"{name}  (+ .cmd shim for Windows)")
    else:
        _ok(name)

    return True


def _uninstall_hook(name: str, hooks_dir: Path, *, dry_run: bool) -> None:
    dest = hooks_dir / name
    bak  = dest.with_suffix(".bak")
    shim = hooks_dir / f"{name}.cmd"

    if dry_run:
        if dest.exists():
            _info(f"[dry-run] Would remove: {name}")
        return

    if dest.exists():
        dest.unlink()
    if shim.exists():
        shim.unlink()

    if bak.exists():
        bak.rename(dest)
        _info(f"Restored backup: {name}")
    elif not dest.exists():
        _ok(f"Removed {name}")


# ── Setup wizard ──────────────────────────────────────────────────────────────

def _collect_config() -> dict[str, str] | None:
    """Prompt for required values. Returns dict or None if the user cancels."""
    print(
        f"\n  {C.D}Saved to .git/config — never uploaded to the remote.{C.R}\n"
        f"  {C.D}Press Enter to keep the value shown in [brackets].{C.R}\n"
    )

    results: dict[str, str] = {}

    for key, label, example in (
        ("develop_branch",   "Your local develop branch",           "e.g. feature/dev"),
        ("protected_branch", "Protected branch (integration target)", "e.g. pre-release"),
        ("remote",           "Remote name",                          "origin"),
    ):
        current = _run(
            ["git", "config", "--local", f"gt.{_CFG[key]}"]
        ).stdout.strip() or ("origin" if key == "remote" else "")

        hint = f" [{current}]" if current else f"  ({example})"
        answer = _ask(f"{label}{hint}: ")

        value = answer or current
        if not value:
            _err(f"{label} is required.")
            return None
        results[key] = value

    if results["develop_branch"] == results["protected_branch"]:
        _err(
            f"develop branch and protected branch cannot be the same "
            f"('{results['develop_branch']}').\n"
            "   The protected branch is where you integrate, not where you develop."
        )
        return None

    return results


def _validate(cfg: dict[str, str]) -> bool:
    _info("Fetching remote refs to validate branches…")
    fetch = _run(["git", "fetch", cfg["remote"]])
    if fetch.returncode != 0:
        _warn(f"Could not fetch from '{cfg['remote']}'. Validating from local refs only.")

    ok = True
    for key, label in (("develop_branch", "develop"), ("protected_branch", "protected")):
        exists, where = _branch_exists(cfg[key], cfg["remote"])
        if exists:
            _ok(f"{label} branch '{cfg[key]}' found ({where}).")
        else:
            _err(
                f"{label} branch '{cfg[key]}' not found locally or in '{cfg['remote']}'.\n"
                f"   Create it first, or check for typos."
            )
            ok = False
    return ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gt init",
        description="Set up gt for the current repository.",
    )
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--uninstall",  action="store_true")
    parser.add_argument(
        "--repo", metavar="PATH", default=".",
        help="Target repository (default: current directory)",
    )
    args = parser.parse_args()

    repo_root = _find_repo(Path(args.repo))
    if repo_root is None:
        _err("Not inside a git repository.")
        sys.exit(1)

    hooks_dir = repo_root / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    # ── Uninstall ─────────────────────────────────────────────────────────────
    if args.uninstall:
        _step("Uninstall")
        for hook in HOOKS:
            _uninstall_hook(hook, hooks_dir, dry_run=args.dry_run)
        if not args.dry_run:
            _cfg_remove_section()
            _ok("Personal config removed from .git/config.")
        _ok("gt uninstalled from this repository.")
        return

    # ── Init ──────────────────────────────────────────────────────────────────
    print(f"\n{C.B}gt init{C.R}  —  {repo_root}")
    if args.dry_run:
        _warn("dry-run: nothing will be written.\n")

    _step("Step 1 — Personal configuration")
    cfg = _collect_config()
    if cfg is None:
        _err("Setup cancelled. Nothing was installed.")
        sys.exit(1)

    _step("Step 2 — Validating branches")
    if not _validate(cfg):
        _err("Branch validation failed. Fix the errors above and run gt init again.")
        sys.exit(1)

    if not args.force and not args.dry_run:
        _step("Step 3 — Confirm")
        print()
        print(f"  {'develop branch':<22} {C.G}{cfg['develop_branch']}{C.R}")
        print(f"  {'protected branch':<22} {C.I}{cfg['protected_branch']}{C.R}")
        print(f"  {'remote':<22} {cfg['remote']}")
        print()
        answer = _ask("Save config and install hooks? [Y/n]: ").lower()
        if answer and answer not in ("y", "yes"):
            _err("Setup cancelled. Nothing was installed.")
            sys.exit(1)

    _step("Step 4 — Saving config")
    if not args.dry_run:
        failed = [k for k, v in cfg.items() if not _cfg_write(k, v)]
        if failed:
            _err(f"Could not write to .git/config: {', '.join(failed)}")
            sys.exit(1)
        _ok("Config saved to .git/config (never uploaded).")
    else:
        for k, v in cfg.items():
            _info(f"[dry-run] gt.{_CFG[k]} = {v}")

    _step("Step 5 — Installing hooks")
    if not all(_install_hook(h, hooks_dir, dry_run=args.dry_run) for h in HOOKS):
        _err("Some hooks failed to install.")
        sys.exit(1)

    print()
    if args.dry_run:
        _ok("Dry-run complete. Run without --dry-run to apply.")
    else:
        _ok("gt is ready.\n")
        _info(f"  gt sync    rebase '{cfg['develop_branch']}' onto '{cfg['remote']}/{cfg['protected_branch']}'")
        _info(f"  gt merge   integrate '{cfg['develop_branch']}' into '{cfg['protected_branch']}'")
        _info(f"  gt status  full diagnostic")
        print()


if __name__ == "__main__":
    main()
