#!/usr/bin/env python3
"""
gt.py — Safe Git workflow CLI.

Usage:
    python gt.py <command> [options]

Commands:
    init         Set up gt for this repository (run once per repo/developer)
    configure    View or update your personal settings
    status       Full diagnostic of your current branch
    check        Validate state and simulate a merge — no changes made
    sync         Rebase your branch onto the protected branch and push
    merge        Integrate your branch into the protected branch

Options:
    --verbose, -v   Show every git command executed
    --show          [configure] Print the effective config
    --reset         [configure] Remove your personal settings
    --help, -h      Show this message
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gt",
        description="Safe Git workflow tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "  init         Set up gt for this repository\n"
            "  configure    View or update your personal settings\n"
            "  status       Full branch diagnostic\n"
            "  check        Validate state + dry-run merge\n"
            "  sync         Rebase your branch onto the protected branch\n"
            "  merge        Integrate your branch into the protected branch"
        ),
    )
    p.add_argument(
        "command",
        choices=["init", "configure", "status", "check", "sync", "merge"],
        metavar="command",
    )
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Show every git command executed")
    p.add_argument("--show",  action="store_true",
                   help="[configure] Print effective config")
    p.add_argument("--reset", action="store_true",
                   help="[configure] Remove personal settings")
    return p


def main() -> None:
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)

    args, extra = _build_parser().parse_known_args()

    # `init` is handled by init.py and does not need the config module loaded.
    if args.command == "init":
        import subprocess
        init_script = Path(__file__).parent / "init.py"
        sys.exit(subprocess.call([sys.executable, str(init_script)] + extra))

    # All other commands import from _core, which loads config at import time.
    # If config is missing, _core/config.py exits with code 2 and a clear message.
    #
    from _core import ui
    from _core.commands import (
        cmd_status,
        cmd_check,
        cmd_sync,
        cmd_merge,
        cmd_configure,
    )

    ui.set_verbose(args.verbose)

    try:
        if args.command == "configure":
            cmd_configure(show=args.show, reset=args.reset)
        elif args.command == "status":
            cmd_status()
        elif args.command == "check":
            cmd_check()
        elif args.command == "sync":
            cmd_sync()
        elif args.command == "merge":
            cmd_merge()
    except KeyboardInterrupt:
        ui.blank()
        ui.warn("Interrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
