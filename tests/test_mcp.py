from unittest.mock import patch, MagicMock
from agy_switcher.mcp_server import handle_initialize, handle_tools_list, handle_tools_call
from agy_switcher.coder import DelegationResult


def test_handle_initialize():
    res = handle_initialize(1)
    assert res["id"] == 1
    assert res["result"]["serverInfo"]["name"] == "agy-switcher"
    assert "tools" in res["result"]["capabilities"]


def test_handle_tools_list():
    res = handle_tools_list(2)
    assert res["id"] == 2
    tools = res["result"]["tools"]
    assert any(t["name"] == "gemini_code" for t in tools)


def test_handle_tools_call_success():
    with patch("agy_switcher.mcp_server.run_agy_delegation") as mock_del:
        mock_del.return_value = DelegationResult(
            stdout="Refactoring complete",
            stderr="",
            exit_code=0,
            slot_used="work",
            attempts=1,
        )
        res = handle_tools_call(3, {"name": "gemini_code", "arguments": {"prompt": "refactor code"}})
        assert res["id"] == 3
        assert res["result"]["isError"] is False
        assert "Refactoring complete" in res["result"]["content"][0]["text"]
