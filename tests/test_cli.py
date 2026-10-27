from pathlib import Path
from unittest.mock import patch
from agy_switcher.cli import main, switch_main, coder_main


def test_cli_save_and_status(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGY_VAULT_BACKEND", "file")
    # Save slot
    assert main(["save", "work", "--email", "work@example.com", "--secret", "tok1"]) == 0
    # Status
    assert main(["status"]) == 0
    # Switch
    assert switch_main(["work"]) == 0
    # List
    assert switch_main(["-l"]) == 0


def test_coder_cli_mock(monkeypatch):
    monkeypatch.setenv("AGY_VAULT_BACKEND", "file")
    with patch("agy_switcher.cli.run_agy_delegation") as mock_del:
        from agy_switcher.coder import DelegationResult
        mock_del.return_value = DelegationResult(stdout="Code generated", stderr="", exit_code=0, slot_used="work", attempts=1)
        assert coder_main(["generate tests"]) == 0
