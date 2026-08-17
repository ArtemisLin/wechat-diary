"""会话状态持久化: 逻辑日翻页检测 (v0.3 单模式)。

v0.3 起不再有 chat/diary 双模式——发什么记什么。本模块只剩一件事:
记住"上一次活动属于哪个逻辑日", 翻页时让 main 自动封存旧的一天。

存储: data/session_state.json (字段保留 mode/chat_count_today 兼容老数据, 不再读写语义)
{
  "u-abc": {
    "mode": "single",
    "entered_date": "2026-04-24",
    "chat_count_today": 0
  }
}
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass

import config
import paths

STATE_FILE = paths.SESSION_STATE
_lock = threading.Lock()


@dataclass
class SessionState:
    mode: str  # v0.3 起恒为 "single"; 字段保留兼容
    entered_date: str  # YYYY-MM-DD 逻辑日 (契约 v1.2: 凌晨 DAY_START_HOUR 点前算前一天)
    chat_count_today: int = 0


def _read_all() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def rollover(user_id: str) -> str | None:
    """检查逻辑日是否翻页。

    返回值: 翻页了 → 旧的 entered_date (供 main 自动封存); 没翻页/首次 → None。
    无论哪种情况, 调用后 entered_date 都已更新为今天的逻辑日。
    """
    today = config.logical_today_str()
    with _lock:
        data = _read_all()
        raw = data.get(user_id)
        old = raw.get("entered_date") if raw else None
        if old == today:
            return None
        data[user_id] = asdict(SessionState(mode="single", entered_date=today, chat_count_today=0))
        _write_all(data)
        return old  # None 表示首次


def load_or_reset(user_id: str) -> SessionState:
    """读取当前 session (兼容旧调用方: webui/测试)。跨逻辑日则重置。"""
    rollover(user_id)
    with _lock:
        raw = _read_all().get(user_id) or {}
    return SessionState(
        mode="single",
        entered_date=raw.get("entered_date", config.logical_today_str()),
        chat_count_today=int(raw.get("chat_count_today", 0)),
    )


def save(user_id: str, s: SessionState) -> None:
    with _lock:
        data = _read_all()
        data[user_id] = asdict(s)
        _write_all(data)
