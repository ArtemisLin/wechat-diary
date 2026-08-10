"""mcp_server 只读 MCP 接口的测试: 消息块解析 / 三个工具 / JSON-RPC 协议层。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import mcp_server

DAY_MD = """---
date: 2026-08-01
weekday: 周六
source: wechat-diary
---

# 2026-08-01

**21:04**

今天排了三个盘, 有点累。

🎤 晚上散步的时候想到那个客户的事。

**22:10**

明天要早起。

---
_(今日封存于 22:30)_
"""


def _vault(tmp_path: Path) -> Path:
    d = tmp_path / "vault" / "2026"
    d.mkdir(parents=True)
    (d / "2026-08-01.md").write_text(DAY_MD, encoding="utf-8")
    (d / "2026-08-03.md").write_text(
        "---\ndate: 2026-08-03\n---\n\n# 2026-08-03\n\n**09:00**\n\n新的一天。\n",
        encoding="utf-8",
    )
    # 干扰项: 非日期文件与非年份目录不应被扫到
    (tmp_path / "vault" / "notes").mkdir()
    (tmp_path / "vault" / "notes" / "2026-01-01.md").write_text("x", encoding="utf-8")
    (d / "draft.md").write_text("x", encoding="utf-8")
    return tmp_path / "vault"


# === 消息块解析 (契约规则 6) ===

def test_message_blocks_follows_contract():
    blocks = mcp_server.message_blocks(DAY_MD)
    assert [t for t, _ in blocks] == ["21:04", "21:04", "22:10"]
    assert blocks[0][1] == "今天排了三个盘, 有点累。"
    assert blocks[1][1].startswith("🎤")
    # 标题/时间头/分隔线/封存标记都不算消息
    assert all("封存" not in b for _, b in blocks)


def test_list_dates_ignores_stray_files(tmp_path):
    vault = _vault(tmp_path)
    assert mcp_server.list_dates(vault) == ["2026-08-01", "2026-08-03"]


# === 工具 ===

def test_diary_read(tmp_path):
    vault = _vault(tmp_path)
    assert "排了三个盘" in mcp_server.call_tool(vault, "diary_read", {"date": "2026-08-01"})
    assert "没有日记" in mcp_server.call_tool(vault, "diary_read", {"date": "2026-08-02"})


def test_diary_read_rejects_bad_date(tmp_path):
    vault = _vault(tmp_path)
    out = mcp_server.call_tool(vault, "diary_read", {"date": "../../etc/passwd"})
    assert "格式" in out


def test_diary_search_hits_and_range(tmp_path):
    vault = _vault(tmp_path)
    out = mcp_server.call_tool(vault, "diary_search", {"query": "客户"})
    assert "2026-08-01 21:04" in out and "🎤" in out
    out2 = mcp_server.call_tool(
        vault, "diary_search", {"query": "一天", "date_from": "2026-08-02"})
    assert "2026-08-03" in out2 and "2026-08-01" not in out2
    assert "没有找到" in mcp_server.call_tool(vault, "diary_search", {"query": "不存在的词"})


def test_diary_recent(tmp_path):
    vault = _vault(tmp_path)
    out = mcp_server.call_tool(vault, "diary_recent", {})
    lines = out.splitlines()
    assert lines[0].startswith("2026-08-03") and "未封存" in lines[0]
    assert lines[1].startswith("2026-08-01") and "3 条消息" in lines[1] and "已封存" in lines[1]


def test_missing_diary_dir():
    out = mcp_server.call_tool(Path("/nonexistent"), "diary_recent", {})
    assert "DIARY_DIR" in out


# === 协议层 ===

def test_initialize_echoes_client_version(tmp_path):
    resp = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18"}}, _vault(tmp_path))
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["serverInfo"]["name"] == "wechat-diary"


def test_notification_gets_no_response(tmp_path):
    resp = mcp_server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, _vault(tmp_path))
    assert resp is None


def test_tools_list_and_call(tmp_path):
    vault = _vault(tmp_path)
    listed = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, vault)
    names = [t["name"] for t in listed["result"]["tools"]]
    assert names == ["diary_read", "diary_search", "diary_recent"]
    called = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "diary_read", "arguments": {"date": "2026-08-01"}}}, vault)
    assert called["result"]["isError"] is False
    assert "排了三个盘" in called["result"]["content"][0]["text"]


def test_unknown_tool_and_method(tmp_path):
    vault = _vault(tmp_path)
    bad_tool = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "diary_write", "arguments": {}}}, vault)
    assert bad_tool["error"]["code"] == -32602
    bad_method = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"}, vault)
    assert bad_method["error"]["code"] == -32601


def test_unsupported_protocol_version_falls_back(tmp_path):
    resp = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26"}}, _vault(tmp_path))
    assert resp["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION


# === process_line 防崩溃防线 (单条畸形消息不得拖垮 server) ===

def _pl(line: str, vault) -> dict | None:
    out = mcp_server.process_line(line, vault)
    return None if out is None else __import__("json").loads(out)


def test_process_line_rejects_batch_and_scalars(tmp_path):
    vault = _vault(tmp_path)
    for bad in ['[{"jsonrpc":"2.0","id":1,"method":"ping"}]', '[]', '"hi"', '123', 'null']:
        resp = _pl(bad, vault)
        assert resp["error"]["code"] == -32600, bad


def test_process_line_parse_error_and_blank(tmp_path):
    vault = _vault(tmp_path)
    assert _pl("{not json", vault)["error"]["code"] == -32700
    assert _pl("   ", vault) is None


def test_process_line_nondict_params(tmp_path):
    vault = _vault(tmp_path)
    resp = _pl('{"jsonrpc":"2.0","id":7,"method":"tools/call","params":[1,2]}', vault)
    assert resp["error"]["code"] == -32602
    # initialize 带畸形 params 也不能崩, 按默认版本回
    resp2 = _pl('{"jsonrpc":"2.0","id":8,"method":"initialize","params":[1]}', vault)
    assert resp2["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION


def test_process_line_survives_internal_error(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    monkeypatch.setattr(mcp_server, "handle_message",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    resp = _pl('{"jsonrpc":"2.0","id":9,"method":"ping"}', vault)
    assert resp["error"]["code"] == -32603 and resp["id"] == 9


# === 环境与坏文件容错 ===

def test_load_diary_dir_env_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text('DIARY_DIR="/from/dotenv"\n', encoding="utf-8")
    monkeypatch.delenv("DIARY_DIR", raising=False)
    assert mcp_server.load_diary_dir() == "/from/dotenv"
    monkeypatch.setenv("DIARY_DIR", "/from/env")
    assert mcp_server.load_diary_dir() == "/from/env"


def test_search_tolerates_bad_encoding_file(tmp_path):
    vault = _vault(tmp_path)
    (vault / "2026" / "2026-08-02.md").write_bytes(
        "# 2026-08-02\n\n**09:00**\n\n乱码文件\n".encode("gbk"))
    out = mcp_server.call_tool(vault, "diary_search", {"query": "客户"})
    assert "2026-08-01" in out  # 坏文件不拖垮全库检索
    assert "3 条" not in mcp_server.call_tool(vault, "diary_recent", {"n": 1})
