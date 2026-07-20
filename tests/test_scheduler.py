"""scheduler 测试。"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    monkeypatch.setenv("USER_ID", "u-abc")
    monkeypatch.setenv("DIARY_DIR", str(vault))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("AI_API_KEY", "fake-key")
    monkeypatch.setenv("REMIND_HOUR_1", "22")
    monkeypatch.setenv("REMIND_HOUR_2", "23")
    import config, users, diary_writer, user_profile, scheduler
    importlib.reload(config)
    importlib.reload(users)
    importlib.reload(diary_writer)
    importlib.reload(user_profile)
    importlib.reload(scheduler)
    monkeypatch.setattr(user_profile, "PROFILE_FILE", tmp_path / "user_profiles.json")
    monkeypatch.setattr(user_profile, "LEGACY_FILE", tmp_path / "welcomed_users.json")
    return scheduler, diary_writer, vault


def test_reminder_skipped_when_diary_has_content(setup):
    scheduler, diary_writer, _ = setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        diary_writer.write("u-abc", "x", is_voice=False)

    calls = []
    def fake_send(uid, text):
        calls.append((uid, text))
        return True

    sent = scheduler.check_and_remind("u-abc", "提醒1", fake_send)
    assert not sent
    assert calls == []


def test_reminder_sent_when_diary_empty(setup):
    scheduler, _, _ = setup
    calls = []
    def fake_send(uid, text):
        calls.append((uid, text))
        return True

    sent = scheduler.check_and_remind("u-abc", "提醒1", fake_send)
    assert sent
    assert calls == [("u-abc", "提醒1")]


def test_reminder_returns_false_when_send_fn_returns_false(setup):
    scheduler, _, _ = setup

    sent = scheduler.check_and_remind("u-abc", "提醒1", lambda uid, text: False)
    assert not sent


def test_reminder_handles_send_failure_gracefully(setup):
    scheduler, _, _ = setup
    def failing_send(uid, text):
        raise RuntimeError("network down")

    # 不应向上抛,返回 False 即可
    sent = scheduler.check_and_remind("u-abc", "提醒1", failing_send)
    assert not sent


def test_reminder_unknown_user_skipped(setup):
    scheduler, _, _ = setup
    calls = []
    def fake_send(uid, text):
        calls.append((uid, text))
        return True

    sent = scheduler.check_and_remind("u-unknown", "提醒1", fake_send)
    assert not sent
    assert calls == []


def test_create_scheduler_registers_two_jobs(setup):
    scheduler, _, _ = setup
    sched = scheduler.create_scheduler(lambda uid, t: True)
    try:
        jobs = sched.get_jobs()
        assert len(jobs) == 2
        ids = {j.id for j in jobs}
        assert ids == {"remind_1", "remind_2"}
    finally:
        sched.shutdown(wait=False) if sched.running else None


def test_scheduler_uses_beijing_timezone(setup):
    scheduler, _, _ = setup
    sched = scheduler.create_scheduler(lambda uid, t: True)
    try:
        # APScheduler 存的是 tzinfo,验证时区名字包含 Shanghai
        assert "Shanghai" in str(sched.timezone)
    finally:
        sched.shutdown(wait=False) if sched.running else None


def test_reminder_job_iterates_all_active_users(setup):
    scheduler, _, _ = setup
    calls = []
    def fake_send(uid, text):
        calls.append((uid, text))
        return True

    # 模板需含 {name} 占位 (新签名)
    job = scheduler.make_reminder_job("test text {name}", fake_send)
    job()
    assert len(calls) == 1
    uid, text = calls[0]
    assert uid == "u-abc"
    # 未取名 user 默认填"你"
    assert "你" in text


def test_reminder_uses_user_name(setup):
    """提醒文案应包含用户名字 (active 用户)。"""
    import user_profile
    scheduler, _, _ = setup
    user_profile.mark_welcomed("u-abc")
    user_profile.set_name("u-abc", "谷雨")

    sent = []
    def fake_send(uid, text):
        sent.append((uid, text))
        return True

    job = scheduler.make_reminder_job(scheduler.REMIND_TEXT_1_TEMPLATE, fake_send)
    job()
    assert sent
    assert "谷雨" in sent[0][1], f"提醒文案应含名字: {sent[0][1]!r}"


def test_reminder_falls_back_to_default_for_unnamed(setup):
    """未取名时提醒文案用 '你'。"""
    scheduler, _, _ = setup

    sent = []
    def fake_send(uid, text):
        sent.append((uid, text))
        return True

    job = scheduler.make_reminder_job(scheduler.REMIND_TEXT_1_TEMPLATE, fake_send)
    job()
    assert sent
    assert "你" in sent[0][1] or "今天还没记呢" in sent[0][1]

# === v2 C.2: 错过提醒的启动补偿 ===

from datetime import datetime
from zoneinfo import ZoneInfo


def _fake_now(hour):
    return datetime(2026, 7, 15, hour, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def catchup_setup(setup, monkeypatch, tmp_path):
    scheduler, diary_writer, vault = setup
    monkeypatch.setattr(scheduler, "CATCHUP_FILE", tmp_path / "remind_state.json")
    return scheduler, diary_writer, vault


def test_catchup_skips_before_remind_hour(catchup_setup, monkeypatch):
    scheduler, _, _ = catchup_setup
    monkeypatch.setattr(scheduler.config, "now_bj", lambda: _fake_now(10))
    calls = []
    assert not scheduler.run_catchup(lambda u, t: calls.append((u, t)) or True)
    assert calls == []


def test_catchup_sends_after_hour_once_per_day(catchup_setup, monkeypatch):
    scheduler, _, _ = catchup_setup
    monkeypatch.setattr(scheduler.config, "now_bj", lambda: _fake_now(22))
    calls = []
    assert scheduler.run_catchup(lambda u, t: calls.append((u, t)) or True)
    assert len(calls) == 1
    # 同一天第二次调用不再补发
    assert not scheduler.run_catchup(lambda u, t: calls.append((u, t)) or True)
    assert len(calls) == 1


def test_catchup_skips_when_diary_written(catchup_setup, monkeypatch):
    scheduler, diary_writer, _ = catchup_setup
    # 打桩必须在写日记之前: today_str 派生自 now_bj, 写入与检查要用同一个假日期
    monkeypatch.setattr(scheduler.config, "now_bj", lambda: _fake_now(22))
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        diary_writer.write("u-abc", "x", is_voice=False)
    calls = []
    assert not scheduler.run_catchup(lambda u, t: calls.append((u, t)) or True)
    assert calls == []
