"""Multi-platform credentials vault integration.

Supports:
- Windows Credential Manager via native Win32 Advapi32 (CredReadW, CredWriteW, CredDeleteW)
- macOS Keychain via /usr/bin/security
- Linux Secret Service via secret-tool
- File-based fallback for headless or non-keyring environments (~/.gemini/antigravity_vault.json)
"""

from __future__ import annotations

import abc
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional


class BaseVault(abc.ABC):
    """Abstract interface for vault credential storage."""

    @abc.abstractmethod
    def get(self, target: str) -> Optional[str]:
        """Retrieve credential string for target."""

    @abc.abstractmethod
    def set(self, target: str, secret: str) -> bool:
        """Store credential string for target."""

    @abc.abstractmethod
    def delete(self, target: str) -> bool:
        """Delete credential for target."""

    @abc.abstractmethod
    def list_targets(self, prefix: str = "") -> list[str]:
        """List stored credential target names matching prefix."""


class FileVault(BaseVault):
    """File-backed vault fallback with secure permissions."""

    def __init__(self, path: Optional[Path] = None) -> None:
        if path is None:
            gemini_dir = Path.home() / ".gemini"
            gemini_dir.mkdir(parents=True, exist_ok=True)
            self.path = gemini_dir / "antigravity_vault.json"
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_data(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_data(self, data: dict[str, str]) -> None:
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if os.name == "posix":
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
        temp_path.replace(self.path)

    def get(self, target: str) -> Optional[str]:
        return self._read_data().get(target)

    def set(self, target: str, secret: str) -> bool:
        data = self._read_data()
        data[target] = secret
        self._write_data(data)
        return True

    def delete(self, target: str) -> bool:
        data = self._read_data()
        if target in data:
            del data[target]
            self._write_data(data)
            return True
        return False

    def list_targets(self, prefix: str = "") -> list[str]:
        data = self._read_data()
        return [k for k in data.keys() if k.startswith(prefix)]


class Win32Vault(BaseVault):
    """Windows Credential Manager via native Win32 Advapi32."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self, fallback_vault: Optional[BaseVault] = None) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32Vault is only supported on Windows")
        self._advapi32 = ctypes.windll.advapi32
        self._fallback = fallback_vault or FileVault()

        # Struct definitions
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", ctypes.c_uint32),
                ("Type", ctypes.c_uint32),
                ("TargetName", ctypes.c_wchar_p),
                ("Comment", ctypes.c_wchar_p),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", ctypes.c_uint32),
                ("CredentialBlob", ctypes.c_char_p),
                ("Persist", ctypes.c_uint32),
                ("AttributeCount", ctypes.c_uint32),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", ctypes.c_wchar_p),
                ("UserName", ctypes.c_wchar_p),
            ]

        self._CREDENTIALW = CREDENTIALW
        self._PCREDENTIALW = ctypes.POINTER(CREDENTIALW)

        # Function signatures
        self._CredReadW = self._advapi32.CredReadW
        self._CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(self._PCREDENTIALW)]
        self._CredReadW.restype = ctypes.c_bool

        self._CredWriteW = self._advapi32.CredWriteW
        self._CredWriteW.argtypes = [self._PCREDENTIALW, ctypes.c_uint32]
        self._CredWriteW.restype = ctypes.c_bool

        self._CredDeleteW = self._advapi32.CredDeleteW
        self._CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        self._CredDeleteW.restype = ctypes.c_bool

        self._CredFree = self._advapi32.CredFree
        self._CredFree.argtypes = [ctypes.c_void_p]
        self._CredFree.restype = None

    def get(self, target: str) -> Optional[str]:
        pcred = self._PCREDENTIALW()
        success = self._CredReadW(target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pcred))
        if not success:
            err = ctypes.GetLastError()
            if err == self.ERROR_NOT_FOUND:
                return self._fallback.get(target)
            return None
        try:
            cred = pcred.contents
            blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            return blob.decode("utf-8", errors="replace")
        finally:
            self._CredFree(pcred)

    def set(self, target: str, secret: str) -> bool:
        blob = secret.encode("utf-8")
        cred = self._CREDENTIALW()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = blob
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "antigravity"
        success = bool(self._CredWriteW(ctypes.byref(cred), 0))
        if success:
            # Also keep track in metadata list
            self._fallback.set(target, secret)
        return success

    def delete(self, target: str) -> bool:
        self._fallback.delete(target)
        success = bool(self._CredDeleteW(target, self.CRED_TYPE_GENERIC, 0))
        return success or (ctypes.GetLastError() == self.ERROR_NOT_FOUND)

    def list_targets(self, prefix: str = "") -> list[str]:
        return self._fallback.list_targets(prefix)


class MacOSVault(BaseVault):
    """macOS Keychain via /usr/bin/security."""

    def __init__(self, fallback_vault: Optional[BaseVault] = None) -> None:
        self._fallback = fallback_vault or FileVault()

    def _target_to_service_account(self, target: str) -> tuple[str, str]:
        if target == "gemini:antigravity":
            return "gemini", "antigravity"
        if target.startswith("gemini:antigravity:slot:"):
            slot_name = target.split(":", 3)[3]
            return "gemini:slot", slot_name
        return "gemini", target

    def get(self, target: str) -> Optional[str]:
        service, account = self._target_to_service_account(target)
        cmd = ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                return res.stdout.strip()
        except FileNotFoundError:
            pass
        return self._fallback.get(target)

    def set(self, target: str, secret: str) -> bool:
        service, account = self._target_to_service_account(target)
        cmd = ["/usr/bin/security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secret]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                self._fallback.set(target, secret)
                return True
        except FileNotFoundError:
            pass
        return self._fallback.set(target, secret)

    def delete(self, target: str) -> bool:
        service, account = self._target_to_service_account(target)
        cmd = ["/usr/bin/security", "delete-generic-password", "-s", service, "-a", account]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            pass
        return self._fallback.delete(target)

    def list_targets(self, prefix: str = "") -> list[str]:
        return self._fallback.list_targets(prefix)


class LinuxVault(BaseVault):
    """Linux Secret Service via secret-tool."""

    def __init__(self, fallback_vault: Optional[BaseVault] = None) -> None:
        self._fallback = fallback_vault or FileVault()

    def _target_to_service_account(self, target: str) -> tuple[str, str]:
        if target == "gemini:antigravity":
            return "gemini", "antigravity"
        if target.startswith("gemini:antigravity:slot:"):
            slot_name = target.split(":", 3)[3]
            return "gemini:slot", slot_name
        return "gemini", target

    def get(self, target: str) -> Optional[str]:
        service, account = self._target_to_service_account(target)
        cmd = ["secret-tool", "lookup", "service", service, "username", account]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout:
                return res.stdout.strip()
        except FileNotFoundError:
            pass
        return self._fallback.get(target)

    def set(self, target: str, secret: str) -> bool:
        service, account = self._target_to_service_account(target)
        cmd = ["secret-tool", "store", f"--label=Antigravity Vault ({target})", "service", service, "username", account]
        try:
            res = subprocess.run(cmd, input=secret, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                self._fallback.set(target, secret)
                return True
        except FileNotFoundError:
            pass
        return self._fallback.set(target, secret)

    def delete(self, target: str) -> bool:
        service, account = self._target_to_service_account(target)
        cmd = ["secret-tool", "clear", "service", service, "username", account]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            pass
        return self._fallback.delete(target)

    def list_targets(self, prefix: str = "") -> list[str]:
        return self._fallback.list_targets(prefix)


def get_vault(backend: Optional[str] = None) -> BaseVault:
    """Factory creating the appropriate vault backend for the host OS."""
    choice = (backend or os.environ.get("AGY_VAULT_BACKEND", "auto")).lower()

    if choice == "file":
        return FileVault()
    if choice == "win32":
        return Win32Vault()
    if choice == "macos":
        return MacOSVault()
    if choice == "linux":
        return LinuxVault()

    # Auto-detection
    if sys.platform == "win32":
        try:
            return Win32Vault()
        except Exception:
            return FileVault()
    elif sys.platform == "darwin":
        try:
            return MacOSVault()
        except Exception:
            return FileVault()
    elif sys.platform.startswith("linux"):
        try:
            return LinuxVault()
        except Exception:
            return FileVault()

    return FileVault()
