"""日记写入核心:LLM 轻度润色 + 追加到当日 md 文件。

契约:
- write(user_id, text, is_voice) 永不抛异常,LLM 失败时回落写原文
- 只 append,不改写历史段落
- 文件名用北京时间日期,跨时区安全
- undo_last_block / finalize_today 为 UX 辅助操作
"""
from __future__ import annotations

import errno
import json
import os
import re
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


# Phase 0.7: 错误分类 → 微信回复差异化提示
class LLMError(Exception):
    """LLM 调用失败, kind 表示错误类别 (供 polish 上层做差异化提示)。"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind  # one of: auth / balance / rate_limit / network / server / other / no_key


def _classify_error(e: Exception) -> str:
    """把底层异常映射到错误类别。"""
    if isinstance(e, HTTPError):
        if e.code == 401:
            return "auth"
        if e.code == 402:
            return "balance"
        if e.code == 429:
            return "rate_limit"
        if 500 <= e.code < 600:
            return "server"
        return "other"
    if isinstance(e, (URLError, socket.timeout)):
        return "network"
    return "other"  # KeyError / JSONDecodeError / ValueError / OSError 等


# 写日记时根据 LLM 错误类别给用户的友好提示 (用于 write 函数 net_note 拼接)
NET_NOTE_BY_KIND: dict[str | None, str] = {
    None: "",
    "auth": " (AI Key 好像不对呢, 检查下 .env, 原文已存)",
    "balance": " (AI 余额用完啦, 充值后试试, 原文已存)",
    "rate_limit": " (AI 调用太频繁, 原文已存)",
    "network": " (AI 暂时不通, 原文已存)",
    "server": " (AI 服务异常, 原文已存)",
    "other": " (AI 出了点小问题, 原文已存)",
    "no_key": " (没配 AI Key, 原文已存)",
}


def _call_llm(prompt: str, timeout: int = 15) -> str:
    """调 DeepSeek。成功返回文本; 失败抛 LLMError(kind=...)。"""
    if not config.AI_API_KEY:
        raise LLMError("no_key")
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

    last_kind = "other"
    last_detail = ""
    for transport, opener in openers:
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except (HTTPError, URLError, socket.timeout, KeyError, json.JSONDecodeError, ValueError, OSError) as e:
            last_kind = _classify_error(e)
            last_detail = f"{type(e).__name__}: {e}"
            _AI_LOG.warning(f"{transport} call_failed [{last_kind}]: {last_detail}")
            continue
    _AI_LOG.warning(f"all transports exhausted, last_kind={last_kind}")
    raise LLMError(last_kind, last_detail)


def polish(raw_text: str) -> tuple[str, bool, str | None]:
    """润色文本。返回 (text, used_llm, error_kind)。LLM 失败时返回原文 + False + kind。

    error_kind: None=成功; 否则 LLMError.kind 之一 (auth/balance/rate_limit/
    network/server/other/no_key), 供 write 选择友好提示文案。
    """
    raw_text = raw_text.strip()
    if not raw_text:
        return raw_text, False, None
    prompt = POLISH_PROMPT.format(raw_text=raw_text)
    try:
        polished = _call_llm(prompt)
    except LLMError as e:
        return raw_text, False, e.kind
    if polished:
        return polished, True, None
    # _call_llm 成功但返回空字符串 (理论上 .strip() 后还是空), 当作 other 错误
    return raw_text, False, "other"


def _diary_path(user_id: str) -> Path:
    user = users.load(user_id)
    today = config.today_str()
    year_dir = user.diary_dir / today[:4]
    year_dir.mkdir(parents=True, exist_ok=True)
    return year_dir / f"{today}.md"


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
    """当前文件有多少时间戳段头 (legacy: 按 \\n** 出现次数)。

    Phase 0.8 起同分钟会合并段头, 所以"段头数"≠"消息数"。
    给用户回复"第 N 段"应使用 count_messages, 此函数仅作为外部 API 兼容保留。
    """
    if not path.exists():
        return 0
    return path.read_text(encoding="utf-8").count("\n**")


# Phase 0.8: 时间戳段头正则 (匹配 **HH:MM** 整行)
_HEADER_RE = re.compile(r"\*\*(\d{1,2}:\d{2})\*\*")


def _last_header_time(content: str) -> str | None:
    """文件中最后一个时间戳段头的 HH:MM, 没有则 None。"""
    matches = _HEADER_RE.findall(content)
    return matches[-1] if matches else None


def _is_message_block(stripped: str) -> bool:
    """判断一个 \\n\\n 分隔出的块是否是"用户消息"块 (而非 header / 段头 / 分隔 / 尾注)。"""
    if not stripped:
        return False
    if stripped.startswith("# "):
        return False  # 日期 header
    if _HEADER_RE.fullmatch(stripped):
        return False  # 段头独占行
    if stripped.startswith("---"):
        return False  # 分隔线
    if stripped.startswith("_("):
        return False  # 封存尾注
    return True


def count_messages(path: Path) -> int:
    """数文件里的消息条数 (含同分钟合并的多段)。"""
    if not path.exists():
        return 0
    content = path.read_text(encoding="utf-8")
    return sum(1 for block in content.split("\n\n") if _is_message_block(block.strip()))


CLOSING_MARKER = "_(今日封存于"


def write(user_id: str, text: str, is_voice: bool) -> tuple[str, int]:
    """写入日记。返回 (回复文本, 当前消息数)。永不抛。

    Phase 0.8: 同分钟连续消息合并到同一段头下, 不再每条都写新 **HH:MM** 段头。
    """
    text = (text or "").strip()
    if not text:
        return "嗯? 没听清, 再说一次?", 0

    polished, used_llm, error_kind = polish(text)
    if is_voice:
        polished = f"🎤 {polished}"
    timestamp = config.hhmm_str()

    try:
        path = _diary_path(user_id)
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if _last_header_time(existing) == timestamp:
                # 同分钟去重: 不写新段头, 仅追加内容
                new_block = f"\n{polished}\n"
            else:
                new_block = f"\n\n**{timestamp}**\n\n{polished}\n"
            _atomic_write(path, existing + new_block)
        else:
            header = (
                "---\n"
                f"date: {config.today_str()}\n"
                f"weekday: {config.weekday_str()}\n"
                "source: wechat-diary\n"
                "---\n\n"
                f"# {config.today_str()}\n"
            )
            new_block = f"\n\n**{timestamp}**\n\n{polished}\n"
            _atomic_write(path, header + new_block)
        n = count_messages(path)
    except (OSError, ValueError, users.UserNotFoundError) as e:
        print(f"  写日记失败({user_id}): {e}")
        _AI_LOG.error(f"diary write failed for {user_id}: {type(e).__name__}: {e}")
        if isinstance(e, OSError) and e.errno == errno.ENOSPC:
            return "存日记失败! 磁盘可能满了 💾 请检查 DIARY_DIR 所在盘", 0
        return "收到啦, 但写入时出了点问题, 等会儿再试试?", 0

    voice_mark = "🎤 " if is_voice else ""
    net_note = "" if used_llm else NET_NOTE_BY_KIND.get(error_kind, NET_NOTE_BY_KIND["other"])
    reply = f"{voice_mark}嗯, 记下来啦~ 这是今天第 {n} 段 ✍️{net_note}\n继续说, 或发「结束」收尾"
    return reply, n


def undo_last_block(user_id: str) -> bool:
    """删除最后一条消息。返回是否成功删除。

    Phase 0.8: 同分钟可能合并多段, undo 只删最后一段消息;
    若该消息是其段头下的唯一一段, 顺带删掉孤儿段头。
    """
    try:
        path = _diary_path(user_id)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        parts = content.split("\n\n")

        # 倒序找最后一个 message 块
        last_msg_i = -1
        for i in range(len(parts) - 1, -1, -1):
            if _is_message_block(parts[i].strip()):
                last_msg_i = i
                break
        if last_msg_i < 0:
            return False

        new_parts = parts[:last_msg_i]
        # 清理末尾的孤儿段头 / 空块
        while new_parts:
            tail = new_parts[-1].strip()
            if not tail or _HEADER_RE.fullmatch(tail):
                new_parts.pop()
            else:
                break

        new_content = "\n\n".join(new_parts)
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"
        _atomic_write(path, new_content)
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
