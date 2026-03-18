# git-doggy — Safe Git Workflow CLI

A zero-dependency CLI tool that automates the `develop → protected branch` workflow with built-in safety checks, merge simulation, and git hooks. Works on **Linux**, **macOS**, and **Windows**. Requires **Python 3.8+**.

---

## Features

- **Automated rebase & push** — `gt sync` keeps your branch up to date with `--force-with-lease` safety.
- **Simulated merge** — `gt merge` dry-runs before touching the protected branch.
- **Conflict detection** — stops immediately if conflicts are found, before any damage.
- **Git hooks** — blocks direct pushes to the protected branch, conflict markers in commits, and sensitive files.
- **Per-repo, per-developer config** — stored in `.git/config`, never pushed to the remote.
- **Zero dependencies** — pure Python, no pip install required.

---

## Installation

### Linux / macOS

1. Clone or copy the project to a stable path:

   ```bash
   git clone https://github.com/brgarcia17/git-doggy.git ~/tools/gt
   ```

2. Add a shell alias to your profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):

   ```bash
   alias gt="python3 ~/tools/gt/cli.py"
   ```

3. Reload your shell:

   ```bash
   source ~/.zshrc   # or ~/.bashrc
   ```

4. Verify:

   ```bash
   gt --help
   ```

### Windows

1. Clone or copy the project to a stable path:

   ```powershell
   git clone https://github.com/brgarcia17/git-doggy.git $HOME\tools\gt
   ```

2. Add a function to your PowerShell profile (`$PROFILE`):

   ```powershell
   function gt { python "$HOME\tools\gt\cli.py" @args }
   ```

3. Reload PowerShell:

   ```powershell
   . $PROFILE
   ```

4. Verify:

   ```powershell
   gt --help
   ```

---

## Getting Started

Run the setup wizard **once per repository, per developer**:

```bash
cd /path/to/my-repo
gt init
```

The wizard walks you through five steps:

| Step                      | Description                                            |
| ------------------------- | ------------------------------------------------------ |
| 1. Personal configuration | Your develop branch, protected branch, and remote name |
| 2. Branch validation      | Fetches remote refs and verifies both branches exist   |
| 3. Confirmation           | Summary and explicit confirmation before writing       |
| 4. Save config            | Writes to `.git/config [gt]` (never uploaded)          |
| 5. Install hooks          | Copies hooks to `.git/hooks/`                          |

If any step fails, **nothing is written and nothing is installed**.

### Init options

```bash
gt init                # interactive setup
gt init --dry-run      # preview without making changes
gt init --force        # skip the confirmation prompt
gt init --uninstall    # remove hooks and config from this repo
gt init --repo PATH    # target a different repository
```

---

## Commands

| Command                | Description                                                         |
| ---------------------- | ------------------------------------------------------------------- |
| `gt init`              | Run the setup wizard                                                |
| `gt status`            | Full branch diagnostic — never modifies anything                    |
| `gt check`             | Validate state and simulate a merge (dry run)                       |
| `gt sync`              | Rebase onto the protected branch and push with `--force-with-lease` |
| `gt merge`             | Integrate your branch into the protected branch (6-phase flow)      |
| `gt configure`         | Edit your personal config interactively                             |
| `gt configure --show`  | Display the effective configuration                                 |
| `gt configure --reset` | Remove personal settings (requires `gt init` again)                 |

All commands accept `--verbose` (`-v`) to display every git command executed.

---

## Merge Workflow

`gt merge` runs a controlled 6-phase process:

```
Phase 1 — Preparation     Validates clean working tree, runs gt sync automatically
Phase 2 — Simulation      Dry-run merge (--no-commit --no-ff) to detect conflicts
Phase 3 — Confirmation    Explicit user confirmation before modifying the protected branch
Phase 4 — Merge           Real merge with --no-ff and standard commit message
Phase 5 — Push            Pushes the protected branch to the remote
Phase 6 — Return          Switches back to your original branch
```

If the simulation detects conflicts, the process **aborts immediately** — the protected branch is never modified.

### Daily workflow

```bash
gt status             # check current state
gt sync               # rebase onto protected branch (do this frequently)
# ... work normally with git add / git commit ...
gt check              # simulate merge before committing to it
gt merge              # integrate into the protected branch
```

---

## Configuration

All settings are stored in `.git/config` under the `[gt]` section. They are **local-only** and never pushed to the remote.

| Key                        | Description                                     | Example                                 |
| -------------------------- | ----------------------------------------------- | --------------------------------------- |
| `gt.develop-branch`        | Your personal working branch                    | `feature/dev`                           |
| `gt.protected-branch`      | The integration target branch                   | `pre-release`                           |
| `gt.remote`                | Remote name                                     | `origin`                                |
| `gt.merge-commit-template` | Merge commit message template                   | `Merge branch '{branch}' into {target}` |
| `gt.confirm-steps`         | Comma-separated steps that require confirmation | `merge_real,push_protected`             |

View your current config:

```bash
gt configure --show
```

Update interactively:

```bash
gt configure
```

---

## Hooks & Protections

The following hooks are installed automatically by `gt init`:

| Hook              | Behavior                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **pre-push**      | Blocks direct pushes to the protected branch. Blocks pushes when your branch is behind the protected branch.                                |
| **pre-commit**    | Blocks commits containing git conflict markers (`<<<<<<<`). Blocks commits of sensitive files (`.env`, `id_rsa`, `credentials.json`, etc.). |
| **post-checkout** | Warns when switching to the protected branch. Warns when your branch is behind the protected branch.                                        |
| **pre-rebase**    | Blocks rebasing the protected branch directly. Warns when rebasing onto a non-standard base.                                                |

`gt merge` is the **only** path to push to the protected branch. It sets `GT_BYPASS_HOOK=1` internally to allow its own controlled push through the pre-push hook.

To bypass a hook in exceptional cases:

```bash
git commit --no-verify    # bypass pre-commit
```

---

## Multi-Developer Setup

Each developer runs `gt init` in their own clone. Configs are independent and local:

```
Alice:  develop-branch = alice/dev    protected-branch = pre-release
Bob:    develop-branch = bob/dev      protected-branch = pre-release
```

When Alice merges first, Bob runs `gt sync` to incorporate her changes before running `gt merge`.

---

## Troubleshooting

### Rebase conflicts during `gt sync`

```bash
# 1. Fix conflicts in the affected files
# 2. Stage resolved files
git add <files>
# 3. Continue the rebase
git rebase --continue
# 4. Run sync again to push
gt sync
```

### Merge simulation detects conflicts

This means your branch and the protected branch have incompatible changes. Resolve on your branch, then retry:

```bash
# Fix conflicts on your branch, commit, then:
gt sync
gt merge
```

### "gt is not configured for this repository"

Run the setup wizard:

```bash
gt init
```

---

## Running Tests

The test suite creates real git repositories in `/tmp` and runs end-to-end. No mocks.

```bash
python run_tests.py                   # run all tests
python run_tests.py -v                # verbose output
python run_tests.py -k sync           # filter by keyword
python run_tests.py -k "merge or config"
python run_tests.py --list            # list all test names
```
