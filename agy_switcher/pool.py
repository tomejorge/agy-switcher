"""Multi-account pool management for Antigravity sessions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional

from agy_switcher.vault import BaseVault, get_vault

ACTIVE_TARGET = "gemini:antigravity"
SLOT_TARGET_PREFIX = "gemini:antigravity:slot:"


class AccountPool:
    """Manages slots, switching, cooldowns, and round-robin rotation."""

    def __init__(self, vault: Optional[BaseVault] = None, config_path: Optional[Path] = None) -> None:
        self.vault = vault or get_vault()
        if config_path is None:
            gemini_dir = Path.home() / ".gemini"
            gemini_dir.mkdir(parents=True, exist_ok=True)
            self.config_path = gemini_dir / "agy_pool.json"
        else:
            self.config_path = Path(config_path)
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"active_slot": None, "slots": {}}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"active_slot": None, "slots": {}}
            data.setdefault("active_slot", None)
            data.setdefault("slots", {})
            return data
        except Exception:
            return {"active_slot": None, "slots": {}}

    def _write_config(self, data: dict[str, Any]) -> None:
        temp = self.config_path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(self.config_path)

    @property
    def active_slot(self) -> Optional[str]:
        return self._read_config().get("active_slot")

    def save_slot(self, name: str, email: Optional[str] = None, secret: Optional[str] = None) -> bool:
        """Save credentials into a named slot."""
        name = name.strip()
        if not name:
            raise ValueError("Slot name cannot be empty")

        if secret is None:
            secret = self.vault.get(ACTIVE_TARGET)
            if not secret:
                raise ValueError("No active credential found in vault to save. Provide secret explicitly or log in with agy first.")

        target = f"{SLOT_TARGET_PREFIX}{name}"
        if not self.vault.set(target, secret):
            return False

        config = self._read_config()
        now = datetime.now(timezone.utc).isoformat()
        slot_info = config["slots"].get(name, {
            "created_at": now,
            "failure_count": 0,
            "success_count": 0,
        })
        slot_info["email"] = email or slot_info.get("email")
        slot_info["last_saved"] = now
        slot_info["cooldown_until"] = None
        config["slots"][name] = slot_info

        if config["active_slot"] is None:
            config["active_slot"] = name
            self.vault.set(ACTIVE_TARGET, secret)

        self._write_config(config)
        return True

    def switch_slot(self, name: str) -> bool:
        """Switch active Antigravity session to the specified slot."""
        name = name.strip()
        config = self._read_config()
        if name not in config["slots"]:
            raise KeyError(f"Slot '{name}' does not exist in pool")

        target = f"{SLOT_TARGET_PREFIX}{name}"
        secret = self.vault.get(target)
        if not secret:
            raise ValueError(f"No credential stored for slot '{name}'")

        if not self.vault.set(ACTIVE_TARGET, secret):
            return False

        config["active_slot"] = name
        config["slots"][name]["last_used"] = datetime.now(timezone.utc).isoformat()
        self._write_config(config)
        return True

    def mark_cooldown(self, name: str, seconds: int = 3600) -> None:
        """Put a slot on cooldown for a duration."""
        config = self._read_config()
        if name in config["slots"]:
            until = datetime.now(timezone.utc).timestamp() + seconds
            config["slots"][name]["cooldown_until"] = until
            config["slots"][name]["failure_count"] = config["slots"][name].get("failure_count", 0) + 1
            self._write_config(config)

    def record_success(self, name: Optional[str] = None) -> None:
        """Record successful invocation for slot."""
        config = self._read_config()
        slot = name or config.get("active_slot")
        if slot and slot in config["slots"]:
            config["slots"][slot]["success_count"] = config["slots"][slot].get("success_count", 0) + 1
            self._write_config(config)

    def rotate_slot(self, cooldown_seconds: int = 3600, reason: str = "quota_exhausted") -> Optional[str]:
        """Mark active slot on cooldown and rotate to least-recently-used available slot."""
        config = self._read_config()
        current = config.get("active_slot")
        if current:
            self.mark_cooldown(current, cooldown_seconds)

        # Refresh config
        config = self._read_config()
        now_ts = datetime.now(timezone.utc).timestamp()

        candidates = []
        for name, info in config["slots"].items():
            if name == current and len(config["slots"]) > 1:
                continue
            cooldown_until = info.get("cooldown_until")
            if cooldown_until is not None and cooldown_until > now_ts:
                continue
            last_used = info.get("last_used") or "1970-01-01T00:00:00Z"
            candidates.append((last_used, name))

        if not candidates:
            return None

        # Sort by least recently used
        candidates.sort(key=lambda x: x[0])
        next_slot = candidates[0][1]
        self.switch_slot(next_slot)
        return next_slot

    def list_slots(self) -> list[dict[str, Any]]:
        """List all slots with status details."""
        config = self._read_config()
        now_ts = datetime.now(timezone.utc).timestamp()
        results = []
        active = config.get("active_slot")

        for name, info in config["slots"].items():
            cooldown_until = info.get("cooldown_until")
            is_cooldown = bool(cooldown_until and cooldown_until > now_ts)
            remaining = max(0, int(cooldown_until - now_ts)) if is_cooldown else 0

            results.append({
                "name": name,
                "email": info.get("email"),
                "is_active": (name == active),
                "is_on_cooldown": is_cooldown,
                "cooldown_remaining_sec": remaining,
                "last_used": info.get("last_used"),
                "failure_count": info.get("failure_count", 0),
                "success_count": info.get("success_count", 0),
            })
        return results

    def get_status(self) -> dict[str, Any]:
        """Get summary status of the pool."""
        slots = self.list_slots()
        active = self.active_slot
        available = sum(1 for s in slots if not s["is_on_cooldown"])
        cooldown = sum(1 for s in slots if s["is_on_cooldown"])
        return {
            "active_slot": active,
            "total_slots": len(slots),
            "available_slots": available,
            "cooldown_slots": cooldown,
            "slots": slots,
        }

    def remove_slot(self, name: str) -> bool:
        """Remove slot from pool and vault."""
        config = self._read_config()
        if name not in config["slots"]:
            return False

        del config["slots"][name]
        if config.get("active_slot") == name:
            config["active_slot"] = next(iter(config["slots"].keys()), None)
            if config["active_slot"]:
                target = f"{SLOT_TARGET_PREFIX}{config['active_slot']}"
                sec = self.vault.get(target)
                if sec:
                    self.vault.set(ACTIVE_TARGET, sec)

        self._write_config(config)
        self.vault.delete(f"{SLOT_TARGET_PREFIX}{name}")
        return True
