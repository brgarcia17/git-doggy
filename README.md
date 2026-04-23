# git-doggy — Safe Git Workflow CLI

A zero-dependency CLI tool that automates the `develop → protected branch` workflow with built-in safety checks, interactive conflict resolution, merge simulation, and git hooks. Works on **Linux**, **macOS**, and **Windows**. Requires **Python 3.8+**.

---

## Features

- **Automated rebase & push** — `gt sync` keeps your branch up to date with `--force-with-lease` safety.
- **Interactive conflict resolution** — when `gt sync` hits a rebase conflict, a terminal UI lets you resolve each file with `theirs`, `ours`, or by editing directly in your IDE. No manual `git add` needed.
- **IDE-aware file opening** — detects VS Code, Cursor, Windsurf, and JetBrains terminals automatically and opens conflicted files in the right editor.
- **Real-time watcher** — monitors files saved in your IDE and updates resolution state automatically when conflict markers are removed.
- **Simulated merge** — `gt merge` dry-runs before touching the protected branch.
- **Git hooks** — blocks direct pushes to the protected branch, conflict markers in commits, and sensitive files.
- **Per-repo, per-developer config** — stored in `.git/config`, never pushed to the remote.
- **Zero dependencies** — pure Python stdlib, no `pip install` required.

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
gt init --mode safe    # install hooks in non-blocking mode (warnings only) [default]
gt init --mode strict  # install hooks in blocking mode (aborts invalid actions)
gt init --uninstall    # remove hooks and config from this repo
gt init --repo PATH    # target a different repository
```

---

## Commands

| Command                | Description                                                       |
| ---------------------- | ----------------------------------------------------------------- |
| `gt init`              | Run the setup wizard                                              |
| `gt status`            | Full branch diagnostic — never modifies anything                  |
| `gt check`             | Validate state and simulate a merge (dry run)                     |
| `gt sync`              | Rebase onto the protected branch, resolve any conflicts, and push |
| `gt merge`             | Integrate your branch into the protected branch (6-phase flow)    |
| `gt configure`         | Edit your personal config interactively                           |
| `gt configure --show`  | Display the effective configuration                               |
| `gt configure --reset` | Remove personal settings (requires `gt init` again)               |

All commands accept `--verbose` (`-v`) to display every git command executed.

---

## Interactive Conflict Resolution

When `gt sync` encounters a rebase conflict, instead of stopping and printing raw git output, it launches an interactive terminal UI:

```
✖  Rebase conflict on branch feature/dev.

── Resolve conflicts ──────────────────────────────────── 2 files ──

  › src/api.py          (1 conflict)   [✓ theirs] ◀ ▶
    src/utils.py        (2 conflicts)  [IDE →   ]

↑↓ navigate  ·  ←→ theirs/ours  ·  ↵ open IDE  ·  c continue  ·  a abort

Progress: 1 resolved  ·  1 in IDE
[███████████████░░░░░░░░░░░░░░░] 50%
```

### Keybindings

| Key       | Action                                              |
| --------- | --------------------------------------------------- |
| `↑` / `↓` | Navigate the file list                              |
| `←` / `→` | Toggle between **theirs** (incoming) and **ours**   |
| `Enter`   | Open the file in your IDE for manual editing        |
| `c`       | Continue — apply all selections and resume rebase   |
| `a`       | Abort — cancel and restore the original state       |
| `Ctrl+C`  | Emergency abort — always cleans up the rebase state |

### File states

| State         | Meaning                                                       |
| ------------- | ------------------------------------------------------------- |
| `[pending]`   | Not yet decided                                               |
| `[✓ theirs]`  | Will use the incoming version (protected branch)              |
| `[✓ ours]`    | Will keep your version                                        |
| `[IDE →]`     | File is open in your editor — watcher is monitoring for saves |
| `[✓ manual]`  | Conflict markers removed in IDE — automatically detected      |
| `[⚠ markers]` | Saved in IDE but conflict markers still present               |

### IDE detection

When you press `Enter` to open a file, this tool detects which IDE is hosting your terminal and opens the file there directly:

| IDE                             | Detection                              | Opens with                    |
| ------------------------------- | -------------------------------------- | ----------------------------- |
| VS Code                         | `TERM_PROGRAM=vscode`                  | `code <file>`                 |
| Windsurf                        | `TERM_PROGRAM=windsurf`                | `code <file>`                 |
| Cursor                          | `TERM_PROGRAM=cursor`                  | `cursor <file>`               |
| JetBrains (IntelliJ, WebStorm…) | `TERMINAL_EMULATOR=JetBrains-JediTerm` | platform open                 |
| Apple Terminal / other          | fallback                               | `open` / `xdg-open` / `start` |

### Real-time watcher

Once a file is opened in your IDE, this tool monitors it in the background. When you save the file:

- **Conflict markers removed** → state transitions to `[✓ manual]` automatically.
- **Markers still present** → state shows `[⚠ markers]` so you know to keep editing.

No need to switch back to the terminal to update the status.

### Multi-commit rebases

If your branch has multiple commits that each conflict, the TUI re-opens for each commit automatically until the entire rebase completes.

### Safety guarantees

- **Any interruption** (Ctrl+C, terminal close, unexpected error) triggers `git rebase --abort` automatically — the repository is never left in a broken state.
- `gt merge` does **not** resolve conflicts interactively. If its internal `gt sync` step encounters a conflict, it exits with a clear error instructing you to run `gt sync` first.
- **No silent destructive actions** — a summary and explicit confirmation are required before git operations are applied.

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

> **Note**: By default, hooks are installed in **safe** mode, which means they will only output warnings. To enforce the blocking behavior described above, initialize with `gt init --mode strict`.

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

This tool handles this automatically. When a conflict is detected, the interactive TUI opens. Use `←→` to choose `theirs`/`ours`, or press `Enter` to open the file in your IDE. Press `c` to continue once all files are resolved.

If you need to bail out entirely, press `a` or `Ctrl+C` — the rebase will be aborted cleanly.

### Merge simulation detects conflicts

This means your branch and the protected branch have incompatible changes. Run `gt sync` first to resolve them interactively, then retry:

```bash
gt sync     # resolve conflicts interactively
gt merge    # retry the merge
```

### "gt is not configured for this repository"

Run the setup wizard:

```bash
gt init
```

### File opens in the wrong application

This tool detects your IDE via the `TERM_PROGRAM` or `TERMINAL_EMULATOR` environment variable set by VS Code, Cursor, Windsurf, and JetBrains. If you are using a different terminal or editor, the file will open with the platform default (`open` on macOS, `xdg-open` on Linux, `start` on Windows).

---

## Running Tests

The test suite creates real git repositories in a temporary directory and runs end-to-end. No mocks.

```bash
python run_tests.py                   # run all tests
python run_tests.py -v                # verbose output
python run_tests.py -k sync           # filter by keyword
python run_tests.py -k "merge or config"
python run_tests.py --list            # list all test names
```

---

## Contributing

Contributions are welcome. Please open an issue before submitting a pull request for significant changes.

---

## License

MIT — see [LICENSE](LICENSE).
