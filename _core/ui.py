"""
_core/ui.py

Terminal output helpers: colors, structured messages, confirmation prompts.
Color support is detected automatically — works on Mac, Linux, and Windows Terminal.
Verbose mode is set once by the CLI via set_verbose() before any command runs.
"""
from __future__ import annotations

import os
import sys


# ── ANSI color support ────────────────────────────────────────────────────────

def _supports_color() -> bool:
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


_COLOR = _supports_color()


class C:
    """ANSI escape codes. Empty strings when color is not supported."""
    RESET  = "\033[0m"  if _COLOR else ""
    BOLD   = "\033[1m"  if _COLOR else ""
    DIM    = "\033[2m"  if _COLOR else ""
    RED    = "\033[31m" if _COLOR else ""
    GREEN  = "\033[32m" if _COLOR else ""
    YELLOW = "\033[33m" if _COLOR else ""
    CYAN   = "\033[36m" if _COLOR else ""


# ── Verbose flag ──────────────────────────────────────────────────────────────

_verbose = False


def set_verbose(value: bool) -> None:
    global _verbose
    _verbose = value


def is_verbose() -> bool:
    return _verbose


# ── Output functions ──────────────────────────────────────────────────────────

def step(title: str) -> None:
    """Section header — always shown."""
    print(f"\n{C.BOLD}{C.CYAN}── {title}{C.RESET}")


def info(msg: str) -> None:
    """Key status message — always shown."""
    print(f"{C.CYAN}→{C.RESET}  {msg}")


def success(msg: str) -> None:
    """Positive confirmation — always shown."""
    print(f"{C.GREEN}✔{C.RESET}  {C.BOLD}{msg}{C.RESET}")


def warn(msg: str) -> None:
    """Non-fatal warning — always shown."""
    print(f"{C.YELLOW}⚠{C.RESET}  {msg}")


def error(msg: str) -> None:
    """Fatal error — always shown, goes to stderr."""
    print(f"{C.RED}✖{C.RESET}  {C.BOLD}{msg}{C.RESET}", file=sys.stderr)


def detail(msg: str) -> None:
    """Verbose-only detail (git commands, divergence counts, etc.)."""
    if _verbose:
        print(f"  {C.DIM}{msg}{C.RESET}")


def blank() -> None:
    print()


# ── User prompts ──────────────────────────────────────────────────────────────

def confirm(prompt: str, default: bool = False) -> bool:
    """
    Show a yes/no prompt. Returns the user's answer.
    default=False → Enter means No (safe default for destructive operations).
    """
    hint = "[y/N]" if not default else "[Y/n]"
    try:
        answer = input(f"{C.YELLOW}?{C.RESET}  {prompt} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        blank()
        return False
    if answer == "":
        return default
    return answer in ("y", "yes")


def ask(prompt: str) -> str:
    """Free-form input prompt. Returns stripped string."""
    try:
        return input(f"{C.YELLOW}?{C.RESET}  {prompt}").strip()
    except (EOFError, KeyboardInterrupt):
        blank()
        return ""


# ── Abort helper ──────────────────────────────────────────────────────────────

def abort(msg: str, code: int = 1) -> None:
    """Print an error message and exit."""
    error(msg)
    sys.exit(code)
