from pathlib import Path
from unittest.mock import MagicMock
import pytest

from agy_switcher.vault import FileVault
from agy_switcher.pool import AccountPool, ACTIVE_TARGET
from agy_switcher.coder import run_agy_delegation, QuotaExhaustedError, is_quota_error


def test_is_quota_error():
    assert is_quota_error("Error: individual quota reached for model gemini-3.8-flash")
    assert is_quota_error("HTTP 429 Too Many Requests: resource_exhausted")
    assert is_quota_error("Capacity exceeded, retry in 60s")
    assert not is_quota_error("SyntaxError: invalid syntax in file main.py")


def test_run_delegation_success(tmp_path: Path):
    vault = FileVault(tmp_path / "vault.json")
    vault.set(ACTIVE_TARGET, "token-active")
    pool = AccountPool(vault=vault, config_path=tmp_path / "pool.json")
    pool.save_slot("work", secret="token-work")

    runner = MagicMock()
    runner.return_value = MagicMock(returncode=0, stdout="Code generated successfully", stderr="")

    result = run_agy_delegation("implement fibonacci", pool=pool, runner=runner)
    assert result.exit_code == 0
    assert result.stdout == "Code generated successfully"
    assert result.attempts == 1


def test_run_delegation_quota_rotation(tmp_path: Path):
    vault = FileVault(tmp_path / "vault.json")
    vault.set(ACTIVE_TARGET, "token-1")
    pool = AccountPool(vault=vault, config_path=tmp_path / "pool.json")
    pool.save_slot("slot1", secret="token-1")
    pool.save_slot("slot2", secret="token-2")
    pool.switch_slot("slot1")

    runner = MagicMock()
    # First invocation fails with quota error, second succeeds
    fail_proc = MagicMock(returncode=1, stdout="", stderr="Error: individual quota reached")
    succ_proc = MagicMock(returncode=0, stdout="Done on slot2", stderr="")
    runner.side_effect = [fail_proc, succ_proc]

    result = run_agy_delegation("test prompt", pool=pool, runner=runner)
    assert result.exit_code == 0
    assert result.attempts == 2
    assert result.slot_used == "slot2"


def test_run_delegation_all_exhausted(tmp_path: Path):
    vault = FileVault(tmp_path / "vault.json")
    vault.set(ACTIVE_TARGET, "token-1")
    pool = AccountPool(vault=vault, config_path=tmp_path / "pool.json")
    pool.save_slot("slot1", secret="token-1")

    runner = MagicMock()
    runner.return_value = MagicMock(returncode=1, stdout="", stderr="Error 429: Too many requests. resource_exhausted")

    with pytest.raises(QuotaExhaustedError):
        run_agy_delegation("test prompt", pool=pool, runner=runner)
