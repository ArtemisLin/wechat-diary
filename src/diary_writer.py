"""日记写入核心:LLM 轻度润色 + 追加到当日 md 文件。

契约:
- write(user_id, text, is_voice) 永不抛异常,LLM 失败时回落写原文
- 只 append,不改写历史段落
- 文件名用北京时间日期,跨时区安全
- undo_last_block / finalize_today 为 UX 辅助操作
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

import config
import logger as app_logger
import paths
import users
import welcome

_AI_LOG = app_logger.get_logger("ai", paths.AI_LOG)

POLISH_PROMPT = """你是日记助理。用户刚说了一段话(可能是语音转写,有口语痕迹)。
请轻度润色:去掉"嗯""那个""这个"这类语气词,理顺断句,适当分段。
禁止:改变第一人称、改写语义、加入用户没说的内容、做总结或点评。
保留用户的表达风格和情绪。

用户原话:
{raw_text}

直接输出润色后的文本,不要任何前缀说明。"""


AI_PROXY_MODE = os.environ.get("AI_PROXY_MODE", "auto").strip().lower() or "auto"


def _normalize_proxy_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        return f"http://{raw}"
    return raw


def _port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _detect_proxy_url() -> str:
    for key in ("AI_PROXY_URL", "NETWORK_PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        url = _normalize_proxy_url(os.environ.get(key, ""))
        if url:
            return url
    for port in (7890, 7897, 7891):
        if _port_open("127.0.0.1", port):
            return f"http://127.0.0.1:{port}"
    return ""


_DIRECT_OPENER = build_opener(ProxyHandler({}))
AI_PROXY_URL = _detect_proxy_url()
_PROXY_OPENER = (
    build_opener(ProxyHandler({"http": AI_PROXY_URL, "https": AI_PROXY_URL}))
    if AI_PROXY_URL else None
)


def _call_llm(prompt: str, timeout: int = 15) -> str | None:
    """调 DeepSeek。成功返回文本,任何失败返回 None(由调用方决定回落策略)。"""
    if not config.AI_API_KEY:
        return None
    payload = {
        "model": config.AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "stream": False,
    }
    req = Request(
        config.AI_BASE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.AI_API_KEY}",
        },
        method="POST",
    )
    openers = [("direct", _DIRECT_OPENER)]
    if AI_PROXY_MODE == "proxy" and _PROXY_OPENER:
        openers = [("proxy", _PROXY_OPENER)]
    elif AI_PROXY_MODE == "auto" and _PROXY_OPENER:
        openers.append(("proxy", _PROXY_OPENER))

    for transport, opener in openers:
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except (HTTPError, URLError, socket.timeout, KeyError, json.JSONDecodeError, ValueError, OSError) as e:
            _AI_LOG.warning(f"{transport} call_failed: {type(e).__name__}: {e}")
            continue
    _AI_LOG.warning("all transports exhausted, LLM call returned None")
    return None


def polish(raw_text: str) -> tuple[str, bool]:
    """润色文本。返回 (text, used_llm)。LLM 失败时返回原文 + False。"""
    raw_text = raw_text.strip()
    if not raw_text:
        return raw_text, False
    prompt = POLISH_PROMPT.format(raw_text=raw_text)
    polished = _call_llm(prompt)
    if polished:
        return polished, True
    return raw_text, False


def _diary_path(user_id: str) -> Path:
    user = users.load(user_id)
    return user.vault_dir / f"{config.today_str()}.md"


def _atomic_write(path: Path, content: str) -> None:
    """先写 .tmp 再 replace,防崩溃丢数据(来自 015fridge 经验)。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def today_has_content(user_id: str) -> bool:
    """当前北京日期对应文件是否存在且非空白。"""
    try:
        path = _diary_path(user_id)
    except (OSError, ValueError, users.UserNotFoundError) as e:
        print(f"  检查今日日记失败({user_id}): {e}")
        return False
    if not path.exists():
        return False
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError as e:
        print(f"  读取今日日记失败({user_id}): {e}")
        return False


def count_blocks(path: Path) -> int:
    """当前文件有多少段(按时间戳行数)。"""
    if not path.exists():
        return 0
    return path.read_text(encoding="utf-8").count("\n**")


CLOSING_MARKER = "_(今日封存于"


def write(user_id: str, text: str, is_voice: bool) -> tuple[str, int]:
    """写入日记。返回 (回复文本, 当前段数)。永不抛。"""
    text = (text or "").strip()
    if not text:
        return "没听清呢,再说一次?", 0

    polished, used_llm = polish(text)
    timestamp = config.hhmm_str()
    new_block = f"\n\n**{timestamp}**\n\n{polished}\n"

    try:
        path = _diary_path(user_id)
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            _atomic_write(path, existing + new_block)
        else:
            header = f"# {config.today_str()}\n"
            _atomic_write(path, header + new_block)
        n = count_blocks(path)
    except (OSError, ValueError, users.UserNotFoundError) as e:
        print(f"  写日记失败({user_id}): {e}")
        return "这段话我收到了,但写入笔记时出了点问题,稍后再试一次?", 0

    voice_mark = "🎤 " if is_voice else ""
    net_note = "" if used_llm else " (网络波动,原文已存)"
    reply = f"{voice_mark}已存入今天笔记(第 {n} 段) ✍️{net_note}\n继续说,或发「结束」收尾"
    return reply, n


def undo_last_block(user_id: str) -> bool:
    """删除当日文件最后一段。返回是否成功删除。
    空文件/仅有 header 的文件返回 False。"""
    try:
        path = _diary_path(user_id)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        # 从末尾往前找最后一个段头 "\n\n**"
        idx = content.rfind("\n\n**")
        if idx < 0:
            return False
        # 如果封存尾注在最后一段之后,连尾注一起砍
        _atomic_write(path, content[:idx])
        return True
    except (OSError, ValueError, users.UserNotFoundError) as e:
        print(f"  撤回最后一段失败({user_id}): {e}")
        return False


def finalize_today(user_id: str) -> bool:
    """今日封存:在文件末尾追加分隔线 + 时间戳注脚。
    重复封存返回 True 但不追加第二次。当日空文件返回 False。"""
    try:
        path = _diary_path(user_id)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return False
        if CLOSING_MARKER in content:
            return True  # 已经封存过,幂等
        stamp = config.hhmm_str()
        footer = f"\n\n---\n{CLOSING_MARKER} {stamp})_\n"
        _atomic_write(path, content + footer)
        return True
    except (OSError, ValueError, users.UserNotFoundError) as e:
        print(f"  今日封存失败({user_id}): {e}")
        return False
