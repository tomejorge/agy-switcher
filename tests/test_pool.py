import time
from pathlib import Path
import pytest

from agy_switcher.vault import FileVault
from agy_switcher.pool import AccountPool, ACTIVE_TARGET, SLOT_TARGET_PREFIX


def setup_pool(tmp_path: Path) -> AccountPool:
    vault = FileVault(tmp_path / "vault.json")
    config_path = tmp_path / "pool.json"
    vault.set(ACTIVE_TARGET, "token-initial")
    return AccountPool(vault=vault, config_path=config_path)


def test_save_and_switch_slot(tmp_path: Path):
    pool = setup_pool(tmp_path)

    # Save active as 'work'
    assert pool.save_slot("work", email="work@example.com")
    assert pool.active_slot == "work"
    assert pool.vault.get(f"{SLOT_TARGET_PREFIX}work") == "token-initial"

    # Save custom secret as 'personal'
    assert pool.save_slot("personal", email="personal@example.com", secret="token-personal")
    assert pool.vault.get(f"{SLOT_TARGET_PREFIX}personal") == "token-personal"

    # Switch to personal
    assert pool.switch_slot("personal")
    assert pool.active_slot == "personal"
    assert pool.vault.get(ACTIVE_TARGET) == "token-personal"


def test_rotate_slot_on_cooldown(tmp_path: Path):
    pool = setup_pool(tmp_path)
    pool.save_slot("acc1", secret="tok1")
    pool.save_slot("acc2", secret="tok2")
    pool.save_slot("acc3", secret="tok3")

    pool.switch_slot("acc1")
    assert pool.active_slot == "acc1"

    # Rotate with cooldown
    next_slot = pool.rotate_slot(cooldown_seconds=100)
    assert next_slot in ("acc2", "acc3")
    assert pool.active_slot == next_slot

    # Verify acc1 is on cooldown
    status = pool.get_status()
    acc1_info = next(s for s in status["slots"] if s["name"] == "acc1")
    assert acc1_info["is_on_cooldown"] is True


def test_all_slots_on_cooldown(tmp_path: Path):
    pool = setup_pool(tmp_path)
    pool.save_slot("acc1", secret="tok1")
    pool.switch_slot("acc1")

    # Rotate when only 1 slot exists marks it and returns None
    pool.mark_cooldown("acc1", seconds=3600)
    next_slot = pool.rotate_slot(cooldown_seconds=3600)
    assert next_slot is None


def test_remove_slot(tmp_path: Path):
    pool = setup_pool(tmp_path)
    pool.save_slot("work", secret="tok1")
    pool.save_slot("personal", secret="tok2")

    assert pool.remove_slot("work")
    assert "work" not in [s["name"] for s in pool.list_slots()]
    assert not pool.remove_slot("nonexistent")
