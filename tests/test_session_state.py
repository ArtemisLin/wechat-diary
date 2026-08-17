"""session_state: 逻辑日翻页检测 (v0.3 单模式) + 原子写。"""
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
    monkeypatch.setenv("DIARY_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    import config, paths, session_state
    importlib.reload(config)
    importlib.reload(paths)
    importlib.reload(session_state)
    monkeypatch.setattr(session_state, "STATE_FILE", state_file)
    return session_state, state_file


def test_first_call_returns_none_and_sets_today(setup, monkeypatch):
    ss, _ = setup
    import config
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-04-24")
    assert ss.rollover("u-abc") is None
    assert ss.load_or_reset("u-abc").entered_date == "2026-04-24"


def test_same_day_no_rollover(setup, monkeypatch):
    ss, _ = setup
    import config
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-04-24")
    ss.rollover("u-abc")
    assert ss.rollover("u-abc") is None


def test_cross_day_returns_old_date(setup, monkeypatch):
    """翻页返回旧日期, 供 main 自动封存; 之后 entered_date 已是今天。"""
    ss, _ = setup
    ss.save("u-abc", ss.SessionState(mode="single", entered_date="2026-04-23"))
    import config
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-04-24")
    assert ss.rollover("u-abc") == "2026-04-23"
    assert ss.rollover("u-abc") is None
    assert ss.load_or_reset("u-abc").entered_date == "2026-04-24"


def test_legacy_mode_field_tolerated(setup, monkeypatch):
    """老数据里 mode=diary/chat 照读不炸, 语义忽略。"""
    ss, state_file = setup
    state_file.write_text(json.dumps({"u-abc": {"mode": "diary", "entered_date": "2026-04-24", "chat_count_today": 5}}), encoding="utf-8")
    import config
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-04-24")
    s = ss.load_or_reset("u-abc")
    assert s.mode == "single"
    assert s.entered_date == "2026-04-24"


def test_atomic_write(setup, monkeypatch):
    """保存时先写 .tmp 再 replace, 不留半截文件。"""
    ss, state_file = setup
    ss.save("u-abc", ss.SessionState(mode="single", entered_date="2026-04-24"))
    assert state_file.exists()
    assert not state_file.with_suffix(".json.tmp").exists()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "u-abc" in data
