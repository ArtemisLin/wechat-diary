"""chat 模式的 LLM 闲聊处理。

- 用 .env 配置的 AI_MODEL (默认 deepseek-v4-flash)
- 带最近 5 轮 (user + assistant) 上下文, 内存 deque, 不持久化
- LLM 失败时回落 5 条简短兜底, 保证 bot 不变哑

复用 diary_writer 的 LLM 基础设施 (DIRECT_OPENER / PROXY_OPENER / 代理探测) — 通过模块属性引用 (Python 约定下划线只是私有提示, 不严格)。
后续如果新增第三个 LLM 调用点, 应抽 src/llm.py。
"""
from __future__ import annotations

import json
import random
import socket
from collections import defaultdict, deque
from typing import Deque
from urllib.error import HTTPError, URLError
from urllib.request import Request

import config
import diary_writer

CHAT_SYSTEM_PROMPT = """你是日记 Agent 在闲聊模式下的助手。用户当前不在记录日记的状态, 你陪用户随便聊聊。

关键约束:
- 每次回复短小 (≤50 字), 像朋友闲聊
- 不主动写日记, 因为你不在记录模式
- 当用户明显在描述今天发生的事时, 柔和提醒: "想记下来吗? 发『开始记日记』就开始"
- 保持温暖陪伴语气, 不长篇大论
- 不评判, 不给建议, 不点评

不要做的:
- 不要装专家
- 不要总结、点评
- 不要超过 2 句话"""

CHAT_FALLBACK_REPLIES: list[str] = [
    "嗯~ 我在听呢",
    "好的, 慢慢说",
    "嗯嗯",
    "在的, 继续说",
    "我都听着",
]

_HISTORY_MAX_TURNS = 5
# deque maxlen = turns * 2 (每轮 2 条消息: user + assistant)
_history: dict[str, Deque[dict]] = defaultdict(lambda: deque(maxlen=_HISTORY_MAX_TURNS * 2))


def chat(user_id: str, user_text: str) -> str:
    """单条闲聊。返回 AI 回复 (失败时回落兜底池)。"""
    history = _history[user_id]
    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    reply = _call_chat_llm(messages)
    if not reply:
        reply = random.choice(CHAT_FALLBACK_REPLIES)

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    return reply


def reset_history(user_id: str) -> None:
    """切到 diary 模式时清空闲聊历史 (避免污染下一次 chat 的语境)。"""
    _history.pop(user_id, None)


def _call_chat_llm(messages: list[dict], timeout: int = 15) -> str | None:
    """调 OpenAI 协议 /chat/completions; 失败返 None。"""
    if not config.AI_API_KEY:
        return None

    payload = {
        "model": config.AI_MODEL,
        "messages": messages,
        "temperature": 0.7,
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

    openers = [("direct", diary_writer._DIRECT_OPENER)]
    if diary_writer.AI_PROXY_MODE == "proxy" and diary_writer._PROXY_OPENER:
        openers = [("proxy", diary_writer._PROXY_OPENER)]
    elif diary_writer.AI_PROXY_MODE == "auto" and diary_writer._PROXY_OPENER:
        openers.append(("proxy", diary_writer._PROXY_OPENER))

    for transport, opener in openers:
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except (HTTPError, URLError, socket.timeout, KeyError, json.JSONDecodeError, ValueError, OSError) as e:
            diary_writer._AI_LOG.warning(f"chat {transport} call_failed: {type(e).__name__}: {e}")
            continue
    diary_writer._AI_LOG.warning("chat: all transports exhausted")
    return None
