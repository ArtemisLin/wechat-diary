"""只读 MCP server 的 Streamable HTTP 外壳 (赛事评测/远程接入用)。

复用 mcp_server.py 的全部 JSON-RPC 处理逻辑 —— 物理上同样无写入路径。
默认服务 docs/demo-vault (合成演示数据), 绝不默认暴露真实日记。

用法:
    python src/mcp_http.py [端口]              # 默认 8977, 演示库
    DIARY_DIR=/path python src/mcp_http.py     # 显式指定库 (自担风险)

协议: MCP Streamable HTTP (无状态最小实现)
- POST /mcp (或 /): body 为单条 JSON-RPC 消息 → application/json 响应
- 通知 (无 id) → 202 无 body; GET → 405 (不提供 SSE 流)
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcp_server  # noqa: E402

DEFAULT_PORT = 8977
MAX_BODY = 1 * 1024 * 1024  # 1MB: 只读查询接口用不到更大的请求


def _resolve_diary_dir() -> str:
    if os.environ.get("DIARY_DIR"):
        return mcp_server.load_diary_dir()
    demo = Path(__file__).resolve().parent.parent / "docs" / "demo-vault"
    return str(demo)


DIARY_DIR = _resolve_diary_dir()


class MCPHTTPHandler(BaseHTTPRequestHandler):
    server_version = "wechat-diary-mcp/1.0"

    def _send(self, status: int, body: bytes = b"", ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept, Mcp-Session-Id, MCP-Protocol-Version")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204)

    def do_GET(self) -> None:  # noqa: N802
        info = {
            "name": "wechat-diary",
            "note": "MCP Streamable HTTP endpoint. POST JSON-RPC to this URL.",
            "tools": [t["name"] for t in mcp_server.TOOLS],
            "readonly": True,
        }
        self._send(200, json.dumps(info, ensure_ascii=False).encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send(400, b'{"error": "bad content-length"}')
            return
        try:
            msg = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, b'{"error": "invalid json"}')
            return

        if isinstance(msg, list):  # 批量: 逐条处理, 过滤通知
            resps = [r for r in (mcp_server.handle_message(m, DIARY_DIR) for m in msg if isinstance(m, dict)) if r]
            if not resps:
                self._send(202)
                return
            self._send(200, json.dumps(resps, ensure_ascii=False).encode("utf-8"))
            return

        if not isinstance(msg, dict):
            self._send(400, b'{"error": "invalid message"}')
            return
        resp = mcp_server.handle_message(msg, DIARY_DIR)
        if resp is None:  # 通知无响应
            self._send(202)
            return
        self._send(200, json.dumps(resp, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))


def main() -> None:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"无效端口: {sys.argv[1]}")
            raise SystemExit(1)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), MCPHTTPHandler)
    print(f"=== wechat-diary 只读 MCP (Streamable HTTP) ===")
    print(f"  监听: http://127.0.0.1:{port}/  (POST JSON-RPC)")
    print(f"  库: {DIARY_DIR}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
