"""
_core/config.py

All settings come exclusively from .git/config [gt] section,
written by `gt init` (the setup wizard).

Required keys — abort with a clear message if any are missing:
    gt.develop-branch      Your personal working branch  (e.g. feature/dev)
    gt.protected-branch    The branch you integrate into (e.g. pre-release)
    gt.remote              Remote name                   (e.g. origin)

Optional keys — have safe built-in defaults:
    gt.merge-commit-template
    gt.confirm-steps
"""
from __future__ import annotations

import subprocess
import sys

# git config key names (underscores are not valid in git config keys)
_KEYS = {
    "develop_branch":        "develop-branch",
    "protected_branch":      "protected-branch",
    "remote":                "remote",
    "merge_commit_template": "merge-commit-template",
    "confirm_steps":         "confirm-steps",
}

_REQUIRED = ("develop_branch", "protected_branch", "remote")

_DEFAULTS = {
    "merge_commit_template": "Merge branch '{branch}' into {target}",
    "confirm_steps":         "merge_real,push_protected",
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _read(python_key: str) -> str | None:
    git_key = _KEYS[python_key]
    r = _run(["git", "config", "--local", f"gt.{git_key}"])
    value = r.stdout.strip()
    return value if r.returncode == 0 and value else None


def write(python_key: str, value: str) -> bool:
    """Write a key to .git/config [gt]. Used by `gt configure`."""
    git_key = _KEYS.get(python_key, python_key.replace("_", "-"))
    r = _run(["git", "config", "--local", f"gt.{git_key}", value])
    return r.returncode == 0


def unset(python_key: str) -> bool:
    """Remove a key from .git/config [gt]. Used by `gt configure --reset`."""
    git_key = _KEYS.get(python_key, python_key.replace("_", "-"))
    r = _run(["git", "config", "--local", "--unset", f"gt.{git_key}"])
    return r.returncode in (0, 5)  # 5 = key did not exist — that is fine


def remove_section() -> None:
    _run(["git", "config", "--local", "--remove-section", "gt"])


def _load() -> dict[str, str]:
    """
    Load all configuration. Aborts with exit code 2 if required keys are missing,
    printing a clear message pointing the user to `gt init`.
    """
    cfg: dict[str, str] = {}
    missing: list[str] = []

    for key in _REQUIRED:
        value = _read(key)
        if value is None:
            missing.append(key)
        else:
            cfg[key] = value

    if missing:
        lines = [
            "",
            "\033[31m✖\033[0m  \033[1mgt is not configured for this repository.\033[0m",
            "",
            "   Run the setup wizard:",
            "",
            "       python /path/to/gt/init.py",
            "",
            f"   Missing: {', '.join(missing)}",
            "",
        ]
        print("\n".join(lines), file=sys.stderr)
        sys.exit(2)

    for key, default in _DEFAULTS.items():
        cfg[key] = _read(key) or default

    return cfg


# ── Module-level constants ────────────────────────────────────────────────────
# Loaded once at import time. Any command that imports this module will trigger
# the validation above.

_cfg = _load()

DEVELOP_BRANCH:         str      = _cfg["develop_branch"]
PROTECTED_BRANCH:       str      = _cfg["protected_branch"]
REMOTE:                 str      = _cfg["remote"]
MERGE_COMMIT_TEMPLATE:  str      = _cfg["merge_commit_template"]
CONFIRM_STEPS:          set[str] = set(s.strip() for s in _cfg["confirm_steps"].split(","))


# ── Helpers used by `gt configure` ───────────────────────────────────────────

EDITABLE_KEYS = ("develop_branch", "protected_branch", "remote")


def as_dict() -> dict[str, object]:
    """Return the full effective config as a plain dict."""
    return {
        "develop_branch":        DEVELOP_BRANCH,
        "protected_branch":      PROTECTED_BRANCH,
        "remote":                REMOTE,
        "merge_commit_template": MERGE_COMMIT_TEMPLATE,
        "confirm_steps":         list(CONFIRM_STEPS),
    }
