"""
_core/commands.py

Business logic for every CLI command.
All git calls go through _core/git.py.
All output goes through _core/ui.py.
All config comes from _core/config.py.
"""
from __future__ import annotations

import os
import sys

from . import git as g
from . import ui
from .config import (
    DEVELOP_BRANCH,
    PROTECTED_BRANCH,
    REMOTE,
    MERGE_COMMIT_TEMPLATE,
    CONFIRM_STEPS,
    EDITABLE_KEYS,
    write  as cfg_write,
    unset  as cfg_unset,
    as_dict as cfg_as_dict,
)


# ── Shared guards ─────────────────────────────────────────────────────────────

def _remote_ref(branch: str) -> str:
    return f"{REMOTE}/{branch}"


def _require_clean() -> None:
    if not g.is_clean():
        files = g.dirty_files()
        ui.error("Working tree is not clean. Commit or stash your changes first.")
        for f in files[:10]:
            ui.detail(f"  {f}")
        sys.exit(1)


def _require_not_protected(branch: str) -> None:
    if branch == PROTECTED_BRANCH:
        ui.abort(
            f"You are on '{PROTECTED_BRANCH}', which is the protected branch.\n"
            f"   Switch to '{DEVELOP_BRANCH}' or your feature branch first."
        )


def _fetch() -> None:
    ui.info(f"Fetching from {REMOTE}…")
    try:
        g.fetch(REMOTE)
        ui.detail("Fetch complete.")
    except g.GitError as e:
        ui.abort(f"Fetch failed: {e.stderr.strip()}")


def _rebase_onto_protected(branch: str) -> None:
    target = _remote_ref(PROTECTED_BRANCH)
    ui.info(f"Rebasing onto {target}…")
    result = g.rebase(target)
    if result.returncode != 0:
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        ui.error(f"Rebase conflict on '{branch}'.")
        if output:
            print(output)
        ui.blank()
        ui.info("To resolve:")
        ui.info("  1. Fix the conflicts shown above.")
        ui.info("  2. git add <files>  →  git rebase --continue")
        ui.info("  3. Run this command again.")
        g.rebase_abort()
        sys.exit(1)
    ui.detail("Rebase successful.")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status() -> None:
    """Full diagnostic of the current branch. Never modifies anything."""
    ui.step("Status")

    branch = g.current_branch()
    ui.info(f"Branch:  {branch}")

    if g.is_clean():
        ui.success("Working tree is clean.")
    else:
        files = g.dirty_files()
        ui.warn(f"Working tree has {len(files)} uncommitted change(s):")
        for f in files[:20]:
            ui.detail(f"  {f}")

    try:
        g.fetch(REMOTE)
        ui.detail("Remote refs refreshed.")
    except g.GitError:
        ui.warn("Could not fetch — showing cached remote state.")

    # Divergence vs own remote branch
    try:
        behind, ahead = g.divergence(_remote_ref(branch), branch)
        if behind == 0 and ahead == 0:
            ui.success(f"In sync with {_remote_ref(branch)}.")
        else:
            if behind > 0:
                ui.warn(f"Behind {_remote_ref(branch)} by {behind} commit(s).")
            if ahead > 0:
                ui.info(f"Ahead of {_remote_ref(branch)} by {ahead} commit(s) (unpushed).")
    except g.GitError:
        ui.warn(f"Could not compare against {_remote_ref(branch)}.")

    # Divergence vs protected branch
    try:
        behind_p, _ = g.divergence(_remote_ref(PROTECTED_BRANCH), branch)
        if behind_p == 0:
            ui.success(f"Up to date with {_remote_ref(PROTECTED_BRANCH)}.")
        else:
            ui.warn(
                f"Behind {_remote_ref(PROTECTED_BRANCH)} by {behind_p} commit(s). "
                "Run:  gt sync"
            )
    except g.GitError:
        ui.warn(f"Could not compare against {_remote_ref(PROTECTED_BRANCH)}.")

    # Pending commits
    try:
        commits = g.log_oneline(_remote_ref(PROTECTED_BRANCH), branch)
        if commits:
            ui.info(f"Commits not yet in '{PROTECTED_BRANCH}':")
            for c in commits:
                ui.detail(f"  {c}")
    except g.GitError:
        pass


def cmd_check() -> None:
    """Validate state and simulate a merge — no changes made."""
    ui.step("Check")

    branch = g.current_branch()
    ui.info(f"Branch: {branch}")

    if g.is_clean():
        ui.success("Working tree is clean.")
    else:
        ui.warn("Working tree has uncommitted changes.")
        for f in g.dirty_files():
            ui.detail(f"  {f}")

    try:
        g.fetch(REMOTE)
    except g.GitError:
        ui.warn("Fetch failed — results may be stale.")

    try:
        behind, _ = g.divergence(_remote_ref(PROTECTED_BRANCH), branch)
        if behind == 0:
            ui.success(f"Up to date with {_remote_ref(PROTECTED_BRANCH)}.")
        else:
            ui.warn(f"Behind {_remote_ref(PROTECTED_BRANCH)} by {behind} commit(s).")
    except g.GitError:
        ui.warn(f"Could not compare against {_remote_ref(PROTECTED_BRANCH)}.")

    if branch == PROTECTED_BRANCH:
        return

    ui.info("Simulating merge (dry run)…")
    try:
        g.checkout(PROTECTED_BRANCH)
        g.pull_ff(REMOTE, PROTECTED_BRANCH)
        result = g.merge_simulate(branch)
        g.merge_abort()
        g.checkout(branch)
        if result.returncode != 0:
            ui.warn("Simulation detected potential conflicts.")
            ui.detail((result.stdout or "") + (result.stderr or ""))
        else:
            ui.success("No merge conflicts detected.")
    except g.GitError as e:
        try:
            g.merge_abort()
        except Exception:
            pass
        try:
            g.checkout(branch)
        except Exception:
            pass
        ui.warn(f"Simulation error: {e.stderr.strip()}")


def cmd_sync() -> None:
    """
    Rebase your branch onto origin/<protected> and push safely.

    Steps: validate → fetch → rebase → push --force-with-lease
    """
    ui.step("Sync")

    branch = g.current_branch()
    ui.info(f"Branch: {branch}")

    _require_clean()
    _require_not_protected(branch)
    _fetch()

    try:
        behind, _ = g.divergence(_remote_ref(PROTECTED_BRANCH), branch)
    except g.GitError:
        behind = 1  # assume we need it

    if behind == 0:
        ui.success(f"Already up to date with {_remote_ref(PROTECTED_BRANCH)}.")
    else:
        ui.info(f"Behind by {behind} commit(s) — rebasing…")
        _rebase_onto_protected(branch)

    ui.info(f"Pushing '{branch}'…")
    try:
        g.push(REMOTE, branch, force_with_lease=True)
        ui.success(f"'{branch}' synced successfully.")
    except g.GitError as e:
        ui.abort(
            f"Push failed: {e.stderr.strip()}\n"
            "Tip: if someone force-pushed your branch, pull manually and retry."
        )


def cmd_merge() -> None:
    """
    Safely integrate your branch into the protected branch.

    Phase 1 — Preparation:  validate clean state, run sync
    Phase 2 — Simulation:   dry-run merge to catch conflicts before touching protected
    Phase 3 — Confirmation: explicit user confirmation
    Phase 4 — Merge:        real merge with standard commit message
    Phase 5 — Push:         push protected branch (triggers CI/CD)
    Phase 6 — Return:       switch back to your branch
    """
    ui.step("Merge")

    source = g.current_branch()
    ui.info(f"Source:  {source}")
    ui.info(f"Target:  {PROTECTED_BRANCH}")

    # ── Phase 1 ──────────────────────────────────────────────────────────────
    ui.step("Phase 1 — Preparation")
    _require_clean()
    _require_not_protected(source)
    ui.info("Running sync…")
    cmd_sync()

    # ── Phase 2 ──────────────────────────────────────────────────────────────
    ui.step("Phase 2 — Merge simulation")
    ui.info(f"Switching to '{PROTECTED_BRANCH}'…")

    try:
        g.checkout(PROTECTED_BRANCH)
    except g.GitError as e:
        ui.abort(f"Could not checkout '{PROTECTED_BRANCH}': {e.stderr.strip()}")

    try:
        g.pull_ff(REMOTE, PROTECTED_BRANCH)
        ui.detail(f"'{PROTECTED_BRANCH}' is up to date.")
    except g.GitError as e:
        g.checkout(source)
        ui.abort(
            f"Could not fast-forward '{PROTECTED_BRANCH}': {e.stderr.strip()}\n"
            "The protected branch may have diverged. Check with your team."
        )

    ui.info(f"Simulating merge of '{source}' → '{PROTECTED_BRANCH}'…")
    sim = g.merge_simulate(source)

    if sim.returncode != 0:
        g.merge_abort()
        g.checkout(source)
        output = ((sim.stdout or "") + (sim.stderr or "")).strip()
        ui.blank()
        ui.error(f"Conflicts detected — '{PROTECTED_BRANCH}' was NOT modified.")
        if output:
            print(output)
        ui.blank()
        ui.info("To resolve:")
        ui.info(f"  1. On '{source}', resolve the conflicts manually.")
        ui.info("  2. Run  gt sync  then  gt merge  again.")
        sys.exit(1)

    g.merge_abort()
    ui.success("Simulation passed — no conflicts.")

    # ── Phase 3 ──────────────────────────────────────────────────────────────
    ui.step("Phase 3 — Confirmation")
    ui.blank()
    ui.info(f"Ready to merge '{source}' into '{PROTECTED_BRANCH}'.")
    ui.warn("This will push to the protected branch and may trigger CI/CD pipelines.")

    if "merge_real" in CONFIRM_STEPS:
        if not ui.confirm(f"Proceed with merge into '{PROTECTED_BRANCH}'?", default=False):
            g.checkout(source)
            ui.info("Merge cancelled. No changes were made.")
            sys.exit(0)

    # ── Phase 4 ──────────────────────────────────────────────────────────────
    ui.step("Phase 4 — Merge")

    message = MERGE_COMMIT_TEMPLATE.format(branch=source, target=PROTECTED_BRANCH)
    ui.info(f'Commit message: "{message}"')

    try:
        g.merge_commit(source, message)
        ui.success("Merge committed.")
    except g.GitError as e:
        ui.error(f"Merge failed: {e.stderr.strip()}")
        g.merge_abort()
        g.checkout(source)
        sys.exit(1)

    # ── Phase 5 ──────────────────────────────────────────────────────────────
    ui.step("Phase 5 — Push")

    if "push_protected" in CONFIRM_STEPS:
        if not ui.confirm(f"Push '{PROTECTED_BRANCH}' to {REMOTE}?", default=True):
            ui.warn(
                f"Push skipped. The merge commit exists locally.\n"
                f"Push manually: git push {REMOTE} {PROTECTED_BRANCH}"
            )
            g.checkout(source)
            sys.exit(0)

    # Set bypass env var so the pre-push hook lets this controlled push through
    os.environ["GT_BYPASS_HOOK"] = "1"
    push_err: g.GitError | None = None
    try:
        g.push(REMOTE, PROTECTED_BRANCH)
        ui.success(f"'{PROTECTED_BRANCH}' pushed to {REMOTE}.")
    except g.GitError as e:
        push_err = e
    finally:
        os.environ.pop("GT_BYPASS_HOOK", None)

    if push_err is not None:
        ui.error(f"Push failed: {push_err.stderr.strip()}")
        ui.warn(
            f"The merge commit exists locally but was NOT pushed.\n"
            f"Inspect:      git log {PROTECTED_BRANCH}\n"
            f"Push manually: git push {REMOTE} {PROTECTED_BRANCH}"
        )
        g.checkout(source)
        sys.exit(1)

    # ── Phase 6 ──────────────────────────────────────────────────────────────
    ui.step("Phase 6 — Return")

    try:
        g.checkout(source)
        ui.success(f"Back on '{source}'.")
    except g.GitError:
        ui.warn("Could not return to your branch automatically. Switch manually.")

    ui.blank()
    ui.success(f"Done. '{source}' is now integrated into '{PROTECTED_BRANCH}'.")


def cmd_configure(*, show: bool = False, reset: bool = False) -> None:
    """
    View or update personal settings stored in .git/config [gt].

    --show   Print the effective config.
    --reset  Remove all personal settings (requires re-running gt init).
    """
    ui.step("Configure")

    if show:
        cfg = cfg_as_dict()
        ui.info("Effective configuration for this repo:\n")
        w = max(len(k) for k in cfg) + 2
        for key, value in cfg.items():
            label = f"{ui.C.GREEN}[.git/config]{ui.C.RESET}"
            print(f"  {key:<{w}} {str(value):<35}  {label}")
        ui.blank()
        ui.detail("Edit:   gt configure")
        ui.detail("Remove: gt configure --reset")
        return

    if reset:
        removed = [k for k in EDITABLE_KEYS if cfg_unset(k)]
        if removed:
            ui.success(f"Removed: {', '.join(removed)}")
            ui.warn("gt is now unconfigured. Run  gt init  again to restore settings.")
        else:
            ui.info("No personal config found for this repo.")
        return

    # Interactive update
    cfg = cfg_as_dict()
    ui.info("Update your personal settings. Press Enter to keep current value.\n")

    prompts = [
        ("develop_branch",   "Your local develop branch"),
        ("protected_branch", "Protected branch (integration target)"),
        ("remote",           "Remote name"),
    ]

    new: dict[str, str] = {}
    for key, label in prompts:
        current = str(cfg.get(key, ""))
        answer = ui.ask(f"{label} [{current}]: ")
        new[key] = answer if answer else current

    if new["develop_branch"] == new["protected_branch"]:
        ui.abort(
            f"develop_branch and protected_branch cannot be the same "
            f"('{new['develop_branch']}')."
        )

    failed = [k for k, v in new.items() if not cfg_write(k, v)]
    if failed:
        ui.abort(f"Could not write to .git/config: {', '.join(failed)}")

    ui.blank()
    ui.success("Config updated.\n")
    for key, value in new.items():
        ui.info(f"  {key:<22} {value}")
    ui.blank()
    ui.detail("Verify with:  gt configure --show")
