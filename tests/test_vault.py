import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest
from agy_switcher.vault import FileVault, Win32Vault, MacOSVault, LinuxVault, get_vault


def test_file_vault_crud(tmp_path: Path):
    vault_file = tmp_path / "vault.json"
    vault = FileVault(vault_file)

    assert vault.get("gemini:antigravity") is None
    assert vault.set("gemini:antigravity", "token-active")
    assert vault.get("gemini:antigravity") == "token-active"

    assert vault.set("gemini:antigravity:slot:work", "token-work")
    targets = vault.list_targets("gemini:antigravity")
    assert "gemini:antigravity" in targets
    assert "gemini:antigravity:slot:work" in targets

    assert vault.delete("gemini:antigravity:slot:work")
    assert vault.get("gemini:antigravity:slot:work") is None
    assert not vault.delete("gemini:antigravity:slot:work")


def test_win32_vault_mock(tmp_path: Path):
    fallback = FileVault(tmp_path / "fallback.json")
    with patch("sys.platform", "win32"), patch("ctypes.windll") as mock_windll:
        mock_advapi = MagicMock()
        mock_windll.advapi32 = mock_advapi

        # Mock CredWriteW
        mock_advapi.CredWriteW.return_value = 1
        # Mock CredReadW
        mock_advapi.CredReadW.return_value = 0
        with patch("ctypes.GetLastError", return_value=1168):
            vault = Win32Vault(fallback_vault=fallback)
            vault.set("gemini:antigravity", "my-secret")
            # When Windows CredReadW returns 1168 (ERROR_NOT_FOUND), falls back
            assert vault.get("gemini:antigravity") == "my-secret"


def test_macos_vault_mock(tmp_path: Path):
    fallback = FileVault(tmp_path / "fallback.json")
    vault = MacOSVault(fallback_vault=fallback)

    with patch("subprocess.run") as mock_run:
        # Mock successful find-generic-password
        mock_res = MagicMock(returncode=0, stdout="token-macos\n")
        mock_run.return_value = mock_res

        secret = vault.get("gemini:antigravity")
        assert secret == "token-macos"
        mock_run.assert_called_with(
            ["/usr/bin/security", "find-generic-password", "-s", "gemini", "-a", "antigravity", "-w"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_linux_vault_mock(tmp_path: Path):
    fallback = FileVault(tmp_path / "fallback.json")
    vault = LinuxVault(fallback_vault=fallback)

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock(returncode=0, stdout="token-linux\n")
        mock_run.return_value = mock_res

        secret = vault.get("gemini:antigravity:slot:work")
        assert secret == "token-linux"
        mock_run.assert_called_with(
            ["secret-tool", "lookup", "service", "gemini:slot", "username", "work"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_get_vault_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGY_VAULT_BACKEND", "file")
    v = get_vault()
    assert isinstance(v, FileVault)
