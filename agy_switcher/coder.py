"""Quota-aware resilient coding agent delegator for Antigravity CLI."""

from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
import sys
from typing import Callable, Optional

from agy_switcher.pool import AccountPool

QUOTA_PATTERNS = [
    re.compile(r"individual\s+quota\s+reached", re.IGNORECASE),
    re.compile(r"quota\s+exceeded", re.IGNORECASE),
    re.compile(r"resource_exhausted", re.IGNORECASE),
    re.compile(r"rate\s*limit\s*exceeded", re.IGNORECASE),
    re.compile(r"429.*too\s+many\s+requests", re.IGNORECASE),
    re.compile(r"too\s+many\s+requests", re.IGNORECASE),
    re.compile(r"capacity\s+exceeded", re.IGNORECASE),
    re.compile(r"model\s+is\s+overloaded", re.IGNORECASE),
    re.compile(r"exhausted\s+your\s+quota", re.IGNORECASE),
]


class QuotaExhaustedError(RuntimeError):
    """Raised when all available Antigravity accounts in pool are exhausted."""


@dataclass
class DelegationResult:
    stdout: str
    stderr: str
    exit_code: int
    slot_used: Optional[str]
    attempts: int


def is_quota_error(output: str) -> bool:
    """Check if process output matches known Gemini/Antigravity quota exhaustion errors."""
    return any(p.search(output) for p in QUOTA_PATTERNS)


def default_runner(cmd: list[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    """Execute command in subprocess."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def run_agy_delegation(
    prompt: str,
    model: str = "gemini-3.8-flash",
    cwd: Optional[str] = None,
    max_retries: Optional[int] = None,
    cooldown_seconds: int = 3600,
    pool: Optional[AccountPool] = None,
    runner: Optional[Callable[[list[str], Optional[str]], subprocess.CompletedProcess[str]]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> DelegationResult:
    """Run agy with automatic quota exhaustion interception, rotation, and prompt replay."""
    pool = pool or AccountPool()
    runner = runner or default_runner
    log = log_fn or (lambda msg: sys.stderr.write(f"[agy-switcher] {msg}\n"))

    slots = pool.list_slots()
    limit = max_retries if max_retries is not None else max(len(slots), 3)

    attempts = 0
    while attempts < limit:
        attempts += 1
        active = pool.active_slot

        cmd = ["agy", "--model", model, "--dangerously-skip-permissions", "-p", prompt]
        proc = runner(cmd, cwd)

        combined_output = f"{proc.stdout}\n{proc.stderr}"
        if proc.returncode == 0:
            pool.record_success(active)
            return DelegationResult(
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=0,
                slot_used=active,
                attempts=attempts,
            )

        if is_quota_error(combined_output):
            log(f"Quota exhausted on slot '{active or 'unknown'}'. Attempting rotation...")
            next_slot = pool.rotate_slot(cooldown_seconds=cooldown_seconds, reason="quota_exhausted")
            if next_slot is None:
                raise QuotaExhaustedError("All Antigravity accounts in the pool are on cooldown or exhausted.")
            log(f"Rotated to slot '{next_slot}'. Replaying prompt (attempt {attempts + 1}/{limit})...")
            continue

        # Non-quota error, do not rotate
        return DelegationResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            slot_used=active,
            attempts=attempts,
        )

    raise QuotaExhaustedError(f"Exceeded maximum delegation retries ({limit}). Quota exhausted on all accounts.")
