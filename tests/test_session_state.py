"""session_state 持久化与跨天 reset 测试。"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    state_file = tmp_path / "session_state.json"
    monkeypatch.setenv("USER_ID", "u-abc")
    monkeypatch.setenv("VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    import config, paths, session_state
    importlib.reload(config)
    importlib.reload(paths)
    importlib.reload(session_state)
    monkeypatch.setattr(session_state, "STATE_FILE", state_file)
    return session_state, state_file


def test_load_default_when_missing(setup):
    ss, _ = setup
    s = ss.load_or_reset("u-abc")
    assert s.mode == "chat"
    assert s.chat_count_today == 0
    assert s.entered_date  # not empty


def test_save_then_load(setup, monkeypatch):
    ss, _ = setup
    import config
    monkeypatch.setattr(config, "today_str", lambda: "2026-04-24")
    ss.save("u-abc", ss.SessionState(mode="diary", entered_date="2026-04-24", chat_count_today=0))
    s = ss.load_or_reset("u-abc")
    assert s.mode == "diary"
    assert s.entered_date == "2026-04-24"


def test_cross_day_resets_to_chat(setup, monkeypatch):
    ss, _ = setup
    ss.save("u-abc", ss.SessionState(mode="diary", entered_date="2026-04-23", chat_count_today=5))
    import config
    monkeypatch.setattr(config, "today_str", lambda: "2026-04-24")
    s = ss.load_or_reset("u-abc")
    assert s.mode == "chat"
    assert s.entered_date == "2026-04-24"
    assert s.chat_count_today == 0


def test_same_day_keeps_state(setup, monkeypatch):
    ss, _ = setup
    ss.save("u-abc", ss.SessionState(mode="diary", entered_date="2026-04-24", chat_count_today=3))
    import config
    monkeypatch.setattr(config, "today_str", lambda: "2026-04-24")
    s = ss.load_or_reset("u-abc")
    assert s.mode == "diary"
    assert s.chat_count_today == 3


def test_enter_diary_resets_chat_count(setup, monkeypatch):
    ss, _ = setup
    import config
    monkeypatch.setattr(config, "today_str", lambda: "2026-04-24")
    ss.save("u-abc", ss.SessionState(mode="chat", entered_date="2026-04-24", chat_count_today=4))
    ss.enter_diary("u-abc")
    s = ss.load_or_reset("u-abc")
    assert s.mode == "diary"
    assert s.chat_count_today == 0


def test_exit_diary_resets_to_chat(setup, monkeypatch):
    ss, _ = setup
    import config
    monkeypatch.setattr(config, "today_str", lambda: "2026-04-24")
    ss.save("u-abc", ss.SessionState(mode="diary", entered_date="2026-04-24", chat_count_today=0))
    ss.exit_diary("u-abc")
    s = ss.load_or_reset("u-abc")
    assert s.mode == "chat"


def test_increment_chat_count(setup, monkeypatch):
    ss, _ = setup
    import config
    monkeypatch.setattr(config, "today_str", lambda: "2026-04-24")
    ss.load_or_reset("u-abc")
    ss.increment_chat_count("u-abc")
    ss.increment_chat_count("u-abc")
    s = ss.load_or_reset("u-abc")
    assert s.chat_count_today == 2


def test_atomic_write(setup, monkeypatch):
    """保存时先写 .tmp 再 replace, 不留半截文件。"""
    ss, state_file = setup
    import config
    monkeypatch.setattr(config, "today_str", lambda: "2026-04-24")
    ss.save("u-abc", ss.SessionState(mode="chat", entered_date="2026-04-24", chat_count_today=0))
    assert state_file.exists()
    # 临时文件不应残留
    assert not state_file.with_suffix(".json.tmp").exists()
    # 内容能解析
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "u-abc" in data
