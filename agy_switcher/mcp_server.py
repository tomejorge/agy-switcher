"""Model Context Protocol (MCP) stdio server exposing gemini_code tool.

Compatible with Claude Code, Codex CLI, and any standard MCP client over stdio.
Zero external runtime dependencies.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

from agy_switcher.coder import run_agy_delegation, QuotaExhaustedError


def send_message(payload: dict[str, Any]) -> None:
    """Send JSON-RPC message formatted with Content-Length header and flush stdout."""
    body = json.dumps(payload, ensure_ascii=False)
    encoded = body.encode("utf-8")
    header = f"Content-Length: {len(encoded)}\r\n\r\n"
    sys.stdout.buffer.write(header.encode("ascii"))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def handle_initialize(req_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "agy-switcher",
                "version": "1.0.0"
            }
        }
    }


def handle_tools_list(req_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "tools": [
                {
                    "name": "gemini_code",
                    "description": "Delegate coding, refactoring, or terminal tasks to Antigravity CLI (agy) with automatic multi-account quota rotation.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "The prompt or coding instruction for the Antigravity agent."
                            },
                            "model": {
                                "type": "string",
                                "description": "Model to run with agy (default: gemini-3.8-flash).",
                                "default": "gemini-3.8-flash"
                            },
                            "working_dir": {
                                "type": "string",
                                "description": "Optional working directory path for execution."
                            }
                        },
                        "required": ["prompt"]
                    }
                }
            ]
        }
    }


def handle_tools_call(req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments", {})

    if name != "gemini_code":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method/Tool '{name}' not found"
            }
        }

    prompt = arguments.get("prompt", "")
    model = arguments.get("model", "gemini-3.8-flash")
    cwd = arguments.get("working_dir")

    try:
        res = run_agy_delegation(prompt=prompt, model=model, cwd=cwd)
        output = f"{res.stdout}\n{res.stderr}".strip()
        if not output:
            output = f"Execution completed with exit code {res.exit_code} (slot: {res.slot_used})."
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": output
                    }
                ],
                "isError": (res.exit_code != 0)
            }
        }
    except QuotaExhaustedError as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: All Antigravity quota exhausted: {exc}"
                    }
                ],
                "isError": True
            }
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error delegating to agy: {exc}"
                    }
                ],
                "isError": True
            }
        }


def run_mcp_server() -> None:
    """Run MCP server reading JSON-RPC messages from stdin."""
    buffer = b""

    while True:
        chunk = sys.stdin.buffer.read(4096)
        if not chunk:
            break
        buffer += chunk

        while True:
            # Check for Content-Length framing
            if b"Content-Length:" in buffer:
                header_end = buffer.find(b"\r\n\r\n")
                if header_end == -1:
                    header_end = buffer.find(b"\n\n")
                    if header_end == -1:
                        break
                    sep_len = 2
                else:
                    sep_len = 4

                header_bytes = buffer[:header_end]
                length = None
                for line in header_bytes.splitlines():
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1].strip())
                        break

                if length is None:
                    buffer = buffer[header_end + sep_len:]
                    continue

                total_len = header_end + sep_len + length
                if len(buffer) < total_len:
                    break

                body = buffer[header_end + sep_len:total_len]
                buffer = buffer[total_len:]

                try:
                    msg = json.loads(body.decode("utf-8"))
                except Exception:
                    continue
            else:
                # Newline-delimited fallback
                if b"\n" not in buffer:
                    break
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except Exception:
                    continue

            # Process JSON-RPC message
            req_id = msg.get("id")
            method = msg.get("method")

            if method == "initialize":
                send_message(handle_initialize(req_id))
            elif method == "notifications/initialized":
                pass
            elif method == "ping":
                if req_id is not None:
                    send_message({"jsonrpc": "2.0", "id": req_id, "result": {}})
            elif method == "tools/list":
                send_message(handle_tools_list(req_id))
            elif method == "tools/call":
                params = msg.get("params", {})
                send_message(handle_tools_call(req_id, params))
            else:
                if req_id is not None:
                    send_message({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method '{method}' not found"
                        }
                    })


if __name__ == "__main__":
    run_mcp_server()
