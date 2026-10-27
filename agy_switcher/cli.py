"""Unified CLI interface for agy-switcher, switch-gemini, and gemini-coder."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from agy_switcher.pool import AccountPool
from agy_switcher.coder import run_agy_delegation, QuotaExhaustedError
from agy_switcher.mcp_server import run_mcp_server


def print_status_table(pool: AccountPool) -> None:
    status = pool.get_status()
    print("=" * 60)
    print(" Antigravity Account Pool Status")
    print("=" * 60)
    print(f" Active slot : {status['active_slot'] or 'None'}")
    print(f" Available   : {status['available_slots']} / {status['total_slots']}")
    print(f" Cooldown    : {status['cooldown_slots']}")
    print("-" * 60)
    print(f"{'SLOT':<15} {'ACTIVE':<8} {'STATUS':<15} {'SUCCESS':<8} {'EMAIL'}")
    print("-" * 60)
    for s in status["slots"]:
        active_mark = "*" if s["is_active"] else ""
        if s["is_on_cooldown"]:
            cooldown_min = s["cooldown_remaining_sec"] // 60
            state = f"Cooldown ({cooldown_min}m)"
        else:
            state = "Ready"
        email = s["email"] or "-"
        print(f"{s['name']:<15} {active_mark:<8} {state:<15} {s['success_count']:<8} {email}")
    print("=" * 60)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agy-switcher",
        description="Multi-account session manager and resilient coding agent delegator for Antigravity CLI.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # save
    p_save = subparsers.add_parser("save", help="Save credentials into a slot")
    p_save.add_argument("name", help="Name of slot (e.g. work, personal)")
    p_save.add_argument("--email", help="Account email identifier")
    p_save.add_argument("--secret", help="Explicit token/cookie string (optional, defaults to active session)")

    # switch
    p_switch = subparsers.add_parser("switch", help="Switch active Antigravity session")
    p_switch.add_argument("name", help="Target slot name")

    # rotate
    p_rotate = subparsers.add_parser("rotate", help="Rotate to next available slot")
    p_rotate.add_argument("--cooldown", type=int, default=3600, help="Cooldown duration in seconds (default: 3600)")

    # list & status
    subparsers.add_parser("list", help="List all slots")
    subparsers.add_parser("status", help="Print detailed pool status")

    # remove
    p_remove = subparsers.add_parser("remove", help="Remove a slot")
    p_remove.add_argument("name", help="Slot name to remove")

    # code
    p_code = subparsers.add_parser("code", help="Delegate prompt to agy with automatic quota rotation")
    p_code.add_argument("prompt", help="Prompt or task for Antigravity agent")
    p_code.add_argument("--model", default="gemini-3.8-flash", help="Model to use (default: gemini-3.8-flash)")
    p_code.add_argument("--cwd", help="Working directory")

    # mcp
    subparsers.add_parser("mcp", help="Start MCP stdio server")

    args = parser.parse_args(argv)
    pool = AccountPool()

    if args.command == "save":
        try:
            pool.save_slot(args.name, email=args.email, secret=args.secret)
            print(f"[OK] Slot '{args.name}' saved successfully.")
            return 0
        except Exception as exc:
            print(f"[ERROR] Failed to save slot: {exc}", file=sys.stderr)
            return 1

    elif args.command == "switch":
        try:
            pool.switch_slot(args.name)
            print(f"[OK] Switched active Antigravity session to '{args.name}'.")
            return 0
        except Exception as exc:
            print(f"[ERROR] Failed to switch: {exc}", file=sys.stderr)
            return 1

    elif args.command == "rotate":
        next_slot = pool.rotate_slot(cooldown_seconds=args.cooldown)
        if next_slot:
            print(f"[OK] Rotated to slot '{next_slot}'.")
            return 0
        else:
            print("[ERROR] All slots are on cooldown.", file=sys.stderr)
            return 1

    elif args.command in ("list", "status") or args.command is None:
        print_status_table(pool)
        return 0

    elif args.command == "remove":
        if pool.remove_slot(args.name):
            print(f"[OK] Slot '{args.name}' removed.")
            return 0
        else:
            print(f"[ERROR] Slot '{args.name}' not found.", file=sys.stderr)
            return 1

    elif args.command == "code":
        try:
            res = run_agy_delegation(prompt=args.prompt, model=args.model, cwd=args.cwd, pool=pool)
            sys.stdout.write(res.stdout)
            sys.stderr.write(res.stderr)
            return res.exit_code
        except QuotaExhaustedError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

    elif args.command == "mcp":
        run_mcp_server()
        return 0

    return 0


def switch_main(argv: Optional[list[str]] = None) -> int:
    """Convenience shortcut CLI for fast session switching."""
    parser = argparse.ArgumentParser(
        prog="switch-gemini",
        description="Quick shortcut to switch or inspect Antigravity accounts.",
    )
    parser.add_argument("slot", nargs="?", help="Slot name to switch to")
    parser.add_argument("-r", "--rotate", action="store_true", help="Rotate to next available slot")
    parser.add_argument("-s", "--status", action="store_true", help="Print pool status")
    parser.add_argument("-l", "--list", action="store_true", help="List slots")

    args = parser.parse_args(argv)
    pool = AccountPool()

    if args.rotate:
        next_slot = pool.rotate_slot()
        if next_slot:
            print(f"[OK] Rotated to slot '{next_slot}'.")
            return 0
        print("[ERROR] All slots are on cooldown.", file=sys.stderr)
        return 1

    if args.status or args.list or (args.slot is None):
        print_status_table(pool)
        return 0

    try:
        pool.switch_slot(args.slot)
        print(f"[OK] Switched to '{args.slot}'.")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


def coder_main(argv: Optional[list[str]] = None) -> int:
    """Convenience shortcut CLI for resilient coding agent delegation."""
    parser = argparse.ArgumentParser(
        prog="gemini-coder",
        description="Delegate task to Antigravity CLI with automatic account rotation on quota limit.",
    )
    parser.add_argument("prompt", help="Prompt or task for the coding agent")
    parser.add_argument("--model", default="gemini-3.8-flash", help="Model to use (default: gemini-3.8-flash)")
    parser.add_argument("--cwd", help="Working directory")

    args = parser.parse_args(argv)
    try:
        res = run_agy_delegation(prompt=args.prompt, model=args.model, cwd=args.cwd)
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        return res.exit_code
    except QuotaExhaustedError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
