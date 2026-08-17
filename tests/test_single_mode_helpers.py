"""v0.3 单模式新增纯函数: 逻辑日 / 探活折叠 / 撤回预览 / 分时段收尾。"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

BJ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.delenv("DAY_START_HOUR", raising=False)
    import config
    importlib.reload(config)
    return config


def test_logical_day_boundary_4am(cfg):
    assert cfg.DAY_START_HOUR == 4
    assert cfg.logical_today_str(datetime(2026, 8, 16, 2, 30, tzinfo=BJ)) == "2026-08-15"
    assert cfg.logical_today_str(datetime(2026, 8, 16, 3, 59, tzinfo=BJ)) == "2026-08-15"
    assert cfg.logical_today_str(datetime(2026, 8, 16, 4, 0, tzinfo=BJ)) == "2026-08-16"
    assert cfg.logical_today_str(datetime(2026, 8, 16, 15, 0, tzinfo=BJ)) == "2026-08-16"


def test_day_start_hour_env_and_clamp(monkeypatch):
    import config
    monkeypatch.setenv("DAY_START_HOUR", "6")
    importlib.reload(config)
    assert config.DAY_START_HOUR == 6
    assert config.logical_today_str(datetime(2026, 8, 16, 5, 0, tzinfo=BJ)) == "2026-08-15"
    monkeypatch.setenv("DAY_START_HOUR", "99")
    importlib.reload(config)
    assert config.DAY_START_HOUR == 4, "非法值回落 4"
    monkeypatch.setenv("DAY_START_HOUR", "abc")
    importlib.reload(config)
    assert config.DAY_START_HOUR == 4


def test_is_night_now(cfg):
    assert cfg.is_night_now(datetime(2026, 8, 16, 21, 30, tzinfo=BJ)) is True
    assert cfg.is_night_now(datetime(2026, 8, 16, 2, 0, tzinfo=BJ)) is True, "凌晨 2 点还没过边界, 算夜"
    assert cfg.is_night_now(datetime(2026, 8, 16, 14, 0, tzinfo=BJ)) is False
    assert cfg.is_night_now(datetime(2026, 8, 16, 4, 0, tzinfo=BJ)) is False


def test_weekday_for(cfg):
    assert cfg.weekday_for("2026-08-16") == "周日"
    assert cfg.weekday_for("2026-08-12") == "周三"


def test_ping_variants_and_repeat_fold():
    import intents as I
    for t in ["在吗", "在吗在吗", "在吗在吗在吗", "你在吗", "在不在?", "测试", "hello", "哈喽~"]:
        assert I.detect(t) is I.Intent.CHAT, t
    assert I.detect("在吗我想问你个事") is I.Intent.DIARY, "带内容的不是探活"


def test_detect_ex_suspect_flag():
    import intents as I
    assert I.detect_ex("开始记日记") == (I.Intent.START_DIARY, False)
    assert I.detect_ex("我今天过得还好我们开始记日记吧, 不说这些闲聊的话了") == (I.Intent.START_DIARY, True)
    assert I.detect_ex("今天吃了火锅") == (I.Intent.DIARY, False)


def test_undo_ok_reply_preview():
    import welcome as W
    assert W.undo_ok_reply("今天试了新的手冲豆子花香很明显很满意") == "好的, 撤掉了「今天试了新的手冲豆子花香…」"
    assert W.undo_ok_reply("🎤 早上开会说的三件事") == "好的, 撤掉了「早上开会说的三件事」"
    assert W.undo_ok_reply("![[日记/attachments/2026/x.jpg]]") == "好的, 撤掉了刚才那张图片"
    assert W.undo_ok_reply(None) == "好的, 帮你撤回啦"


def test_closing_pools_by_time(monkeypatch):
    import config, welcome as W
    monkeypatch.setattr(config, "is_night_now", lambda now=None: False)
    for _ in range(20):
        r = W.random_closing(name=None)
        assert "晚安" not in r and "好梦" not in r and "睡" not in r, f"白天不该说晚安: {r!r}"
    monkeypatch.setattr(config, "is_night_now", lambda now=None: True)
    seen_night = any(("晚安" in W.random_closing() or "好梦" in W.random_closing()) for _ in range(20))
    assert seen_night


def test_closing_copy_edits():
    import welcome as W
    all_lines = W.CLOSING_LINES + W.CLOSING_LINES_WITH_NAME
    assert not any("褶皱" in l for l in all_lines), "「一天的褶皱」已删"
    assert not any("日记本盖章" in l for l in all_lines) and any("笔记本盖章" in l for l in all_lines)
    assert not any("明年今日" in l for l in all_lines) and any("时光胶囊, 下次见" in l for l in all_lines)


def test_ping_reply():
    import welcome as W
    assert "已记 3 段" in W.ping_reply(3)
    assert "在的" in W.ping_reply(0) and "已记" not in W.ping_reply(0)
