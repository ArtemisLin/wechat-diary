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
    import config, users, diary_writer, scheduler
    importlib.reload(config)
    importlib.reload(users)
    importlib.reload(diary_writer)
    importlib.reload(scheduler)
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

    job = scheduler.make_reminder_job("test text", fake_send)
    job()
    assert calls == [("u-abc", "test text")]
