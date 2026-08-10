"""只读 MCP server: 把日记库以标准 MCP 协议暴露给任意 AI 客户端。

README 说"用什么 Agent (Claude Code / Codex / ...) 管理这个库是你的自由"——
本文件是这句话的工程兑现: 任何支持 MCP 的客户端接上即可读日记, 不必自己解析
数据契约。

- 零依赖: MCP stdio 传输就是"每行一条 JSON-RPC 2.0 消息", 标准库足够
  (官方 mcp SDK 要 Python 3.10+, 本项目部署机可能是 3.9)。刻意不 import
  config: 那会连带 zoneinfo, 在没装 tzdata 的 Windows 裸 Python 上启动即崩,
  而本文件只需要 DIARY_DIR 一个配置
- 只读是硬约束: 本文件不 import diary_writer, 物理上不存在写入路径。
  写入永远只经微信管道一条路, 保证日记每个字都出自用户之口
- 协议层防崩溃: 单条畸形消息 (批量数组 / 标量 / 坏参数) 回 JSON-RPC 错误,
  绝不拖垮进程——stdio server 崩溃即客户端断连

用法:
    python src/mcp_server.py              # DIARY_DIR 读 .env
    DIARY_DIR=/path/vault python src/mcp_server.py

Claude Code 接入:
    claude mcp add wechat-diary -- python /绝对路径/src/mcp_server.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from pathlib import Path

SERVER_NAME = "wechat-diary"
SERVER_VERSION = "1.0.1"
# 我们按 2024-11-05 语义实现 (无批量请求); 2025-06-18 移除了批量, 同样兼容。
# 2025-03-26 客户端可发批量请求, 本实现不支持, 协商时回落到自己的版本。
PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-06-18"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_HEADER_RE = re.compile(r"^\*\*(\d{2}:\d{2})\*\*$")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_diary_dir() -> str:
    """DIARY_DIR: 环境变量优先, 其次 .env。极简解析, 与 config.py 同规则。"""
    if os.environ.get("DIARY_DIR"):
        return os.environ["DIARY_DIR"]
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DIARY_DIR") and "=" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# === 日记读取 (纯函数, 独立可测) ===

def diary_file(diary_dir: Path, date: str) -> Path:
    """按数据契约定位某天的文件: DIARY_DIR/YYYY/YYYY-MM-DD.md。"""
    return diary_dir / date[:4] / f"{date}.md"


def _read_text(f: Path) -> str:
    # errors=replace: 单个被 GBK 另存过的坏文件降级为乱码, 不让全库操作失败
    return f.read_text(encoding="utf-8", errors="replace")


def list_dates(diary_dir: Path) -> list[str]:
    """全库日期列表, 升序。只认 YYYY/YYYY-MM-DD.md 布局, 其余文件不碰。"""
    dates = []
    if not diary_dir.is_dir():
        return dates
    for year_dir in diary_dir.iterdir():
        if not (year_dir.is_dir() and re.fullmatch(r"\d{4}", year_dir.name)):
            continue
        for f in year_dir.glob("*.md"):
            if _DATE_RE.match(f.stem) and f.stem[:4] == year_dir.name:
                dates.append(f.stem)
    return sorted(dates)


def message_blocks(text: str) -> list[tuple[str, str]]:
    """按契约规则 6 切消息块: 返回 [(时间, 块内容)]。

    一个 \n\n 分隔块为一条消息; 排除 `# ` / `**HH:MM**` / `---` / `_(`
    开头的块; frontmatter 整体跳过。时间取块上方最近的 `**HH:MM**` 段头。
    """
    body = text
    if body.startswith("---\n"):
        end = body.find("\n---", 4)
        if end != -1:
            body = body[end + 4:]
    blocks, current_time = [], ""
    for raw in body.split("\n\n"):
        block = raw.strip()
        if not block:
            continue
        m = _TIME_HEADER_RE.match(block)
        if m:
            current_time = m.group(1)
            continue
        if block.startswith(("# ", "---", "_(")):
            continue
        blocks.append((current_time, block))
    return blocks


def read_day(diary_dir: Path, date: str) -> str:
    f = diary_file(diary_dir, date)
    if not f.exists():
        return f"{date} 没有日记。"
    return _read_text(f)


def search(diary_dir: Path, query: str, limit: int = 10,
           date_from: str = "", date_to: str = "") -> str:
    """全库子串检索 (大小写不敏感), 按日期倒序返回命中消息块。"""
    q = query.strip().lower()
    if not q:
        return "query 不能为空。"
    hits = []
    for date in reversed(list_dates(diary_dir)):
        if date_from and date < date_from:
            continue
        if date_to and date > date_to:
            continue
        try:
            text = _read_text(diary_file(diary_dir, date))
        except OSError:
            continue
        for time_str, block in message_blocks(text):
            if q in block.lower():
                stamp = f"{date} {time_str}".strip()
                hits.append(f"「{stamp}」\n{block}")
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break
    if not hits:
        return f"没有找到包含「{query}」的日记。"
    return "\n\n".join(hits)


def recent(diary_dir: Path, n: int = 7) -> str:
    """最近 n 天概览: 日期 + 消息数 + 是否封存。"""
    dates = list_dates(diary_dir)[-n:]
    if not dates:
        return "日记库是空的。"
    lines = []
    for date in reversed(dates):
        try:
            text = _read_text(diary_file(diary_dir, date))
        except OSError:
            continue
        count = len(message_blocks(text))
        sealed = "已封存" if "_(今日封存于" in text else "未封存"
        lines.append(f"{date} · {count} 条消息 · {sealed}")
    return "\n".join(lines)


# === 工具注册表 ===

TOOLS = [
    {
        "name": "diary_read",
        "description": "读取某一天的日记原文 (markdown, 含 frontmatter 与时间戳段头)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "日期, 格式 YYYY-MM-DD"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "diary_search",
        "description": "全库检索日记内容, 返回命中的消息块及其日期时间, 按日期倒序",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词 (子串匹配, 大小写不敏感)"},
                "limit": {"type": "integer", "description": "最多返回条数, 默认 10, 上限 50"},
                "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD, 可选"},
                "date_to": {"type": "string", "description": "结束日期 YYYY-MM-DD, 可选"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "diary_recent",
        "description": "最近 n 天的日记概览 (日期/消息数/是否封存), 用于了解记录情况",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "天数, 默认 7, 上限 60"},
            },
        },
    },
]


def _clamp(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def call_tool(diary_dir, name: str, args: dict) -> str:
    """分发工具调用, 返回纯文本结果。参数在这里统一校验。"""
    if not diary_dir or not Path(diary_dir).is_dir():
        return "DIARY_DIR 未配置或目录不存在。请在 .env 里设置 DIARY_DIR。"
    diary_dir = Path(diary_dir)
    if name == "diary_read":
        date = str(args.get("date", "")).strip()
        if not _DATE_RE.match(date):
            return "date 格式应为 YYYY-MM-DD。"
        return read_day(diary_dir, date)
    if name == "diary_search":
        date_from = str(args.get("date_from", "") or "").strip()
        date_to = str(args.get("date_to", "") or "").strip()
        if date_from and not _DATE_RE.match(date_from):
            return "date_from 格式应为 YYYY-MM-DD。"
        if date_to and not _DATE_RE.match(date_to):
            return "date_to 格式应为 YYYY-MM-DD。"
        return search(
            diary_dir,
            str(args.get("query", "")),
            limit=_clamp(args.get("limit"), 1, 50, 10),
            date_from=date_from,
            date_to=date_to,
        )
    if name == "diary_recent":
        return recent(diary_dir, n=_clamp(args.get("n"), 1, 60, 7))
    raise KeyError(name)


# === JSON-RPC 2.0 / MCP 协议层 ===

def handle_message(msg: dict, diary_dir) -> dict | None:
    """处理一条 JSON-RPC 消息 (须为 dict)。返回响应 dict; 通知类消息返回 None。"""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if msg_id is None:  # notification (initialized 等), 不需要响应
        return None
    params = msg.get("params")
    if not isinstance(params, dict):
        params = {}

    def ok(result) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        client_ver = params.get("protocolVersion")
        ver = client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return ok({
            "protocolVersion": ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        raw = msg.get("params")
        if not isinstance(raw, dict):
            return err(-32602, "params must be an object")
        name = raw.get("name", "")
        args = raw.get("arguments")
        if not isinstance(args, dict):
            args = {}
        try:
            text = call_tool(diary_dir, name, args)
        except KeyError:
            return err(-32602, f"unknown tool: {name}")
        except Exception as e:  # 防御: 单次调用失败不拖垮 server
            return ok({"content": [{"type": "text", "text": f"工具执行出错: {e}"}],
                       "isError": True})
        return ok({"content": [{"type": "text", "text": text}], "isError": False})
    return err(-32601, f"method not found: {method}")


def process_line(line: str, diary_dir) -> str | None:
    """一行进, 一行出 (或 None)。所有畸形输入在这里化为 JSON-RPC 错误, 绝不抛异常。"""
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return json.dumps({"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32700, "message": "parse error"}},
                          ensure_ascii=False)
    if not isinstance(msg, dict):
        # 含 JSON-RPC 批量数组: 本实现按 2024-11-05/2025-06-18 语义, 不支持批量
        return json.dumps({"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32600, "message": "invalid request"}},
                          ensure_ascii=False)
    try:
        resp = handle_message(msg, diary_dir)
    except Exception as e:  # 最后防线: 任何未预期异常回错误而非杀进程
        msg_id = msg.get("id")
        resp = {"jsonrpc": "2.0", "id": msg_id if msg_id is not None else None,
                "error": {"code": -32603, "message": f"internal error: {e}"}}
    if resp is None:
        return None
    return json.dumps(resp, ensure_ascii=False)


def main() -> None:
    # Windows 部署机 locale 可能是 GBK: 管道 stdin/stdout 都强制 UTF-8,
    # 否则客户端发来的中文 query 解码即崩 (config.py 只包了 stdout, 且本文件不用它)
    if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    diary_dir = load_diary_dir()
    for line in sys.stdin:
        out = process_line(line, diary_dir)
        if out is not None:
            print(out, flush=True)


if __name__ == "__main__":
    main()
