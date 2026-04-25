"""模式状态持久化: chat / diary 双态 + 每日 chat 计数 + 跨天自动 reset。

数据流:
- mode 切换由 main._handle 触发 (enter_diary / exit_diary)
- 每条 chat 后 main 调 increment_chat_count
- 每次进 _handle 先 load_or_reset 拿当前态; 跨天自动归位 chat

存储: data/session_state.json
{
  "u-abc": {
    "mode": "chat",
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
    mode: str  # "chat" | "diary"
    entered_date: str  # YYYY-MM-DD (北京时间)
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


def load_or_reset(user_id: str) -> SessionState:
    """读取用户当前 session; 若跨天则重置为 chat 模式。返回最新状态。"""
    today = config.today_str()
    with _lock:
        data = _read_all()
        raw = data.get(user_id)
        if raw is None or raw.get("entered_date") != today:
            fresh = SessionState(mode="chat", entered_date=today, chat_count_today=0)
            data[user_id] = asdict(fresh)
            _write_all(data)
            return fresh
        return SessionState(
            mode=raw.get("mode", "chat"),
            entered_date=raw["entered_date"],
            chat_count_today=int(raw.get("chat_count_today", 0)),
        )


def save(user_id: str, s: SessionState) -> None:
    with _lock:
        data = _read_all()
        data[user_id] = asdict(s)
        _write_all(data)


def enter_diary(user_id: str) -> None:
    """切到 diary 模式; chat 计数清零; 标记今天日期。"""
    today = config.today_str()
    save(user_id, SessionState(mode="diary", entered_date=today, chat_count_today=0))


def exit_diary(user_id: str) -> None:
    """切回 chat 模式 (用户发"结束"成功封存后调用)。"""
    today = config.today_str()
    save(user_id, SessionState(mode="chat", entered_date=today, chat_count_today=0))


def increment_chat_count(user_id: str) -> int:
    """chat 模式下每条消息后 +1; 返回新值 (供 main 决定是否追加成本提示)。"""
    today = config.today_str()
    with _lock:
        data = _read_all()
        raw = data.get(user_id, {})
        if raw.get("entered_date") != today:
            new_count = 1
            data[user_id] = asdict(SessionState(mode="chat", entered_date=today, chat_count_today=1))
        else:
            new_count = int(raw.get("chat_count_today", 0)) + 1
            raw["chat_count_today"] = new_count
            data[user_id] = raw
        _write_all(data)
        return new_count
