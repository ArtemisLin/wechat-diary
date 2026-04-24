"""main._handle / _on_message 路由测试。

不启动 iLink/scheduler,只测消息路由到正确分支。
"""
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
    monkeypatch.setenv("VAULT_DIR", str(vault))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("AI_API_KEY", "fake-key")
    import config, users, diary_writer, welcome_store, main
    importlib.reload(config)
    importlib.reload(users)
    importlib.reload(diary_writer)
    importlib.reload(welcome_store)
    importlib.reload(main)
    # welcome_store 重定向到 tmp
    monkeypatch.setattr(welcome_store, "STORE_FILE", tmp_path / "welcomed.json")
    return main, diary_writer, welcome_store, vault


def test_help_intent_returns_help_text(setup):
    main, *_ = setup
    reply = main._handle("u-abc", "帮助", is_voice=False)
    assert "日记小伙计" in reply or "使用指南" in reply


def test_undo_removes_last_block(setup):
    main, diary_writer, _, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="第一段"):
        main._handle("u-abc", "a", is_voice=False)
    reply = main._handle("u-abc", "撤回", is_voice=False)
    assert "删" in reply or "🗑" in reply


def test_undo_when_nothing_written(setup):
    main, *_ = setup
    reply = main._handle("u-abc", "撤回", is_voice=False)
    assert "没啥可撤" in reply or "还没" in reply


def test_finalize_returns_closing_line(setup):
    main, diary_writer, _, _ = setup
    with patch.object(diary_writer, "_call_llm", return_value="内容"):
        main._handle("u-abc", "xx", is_voice=False)
    reply = main._handle("u-abc", "结束", is_voice=False)
    # 结束语 10 选 1,都应该比"今天还没写"长
    assert reply and "还没" not in reply


def test_finalize_when_nothing_written(setup):
    main, *_ = setup
    reply = main._handle("u-abc", "结束", is_voice=False)
    assert "还没" in reply


def test_diary_write_returns_confirm(setup):
    main, diary_writer, _, _ = setup
    with patch.object(diary_writer, "_call_llm", return_value="今天"):
        reply = main._handle("u-abc", "今天吃了面", is_voice=False)
    assert "第 1 段" in reply


def test_nudge_every_4_blocks(setup):
    main, diary_writer, _, _ = setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        r1 = main._handle("u-abc", "a", is_voice=False)
        r2 = main._handle("u-abc", "b", is_voice=False)
        r3 = main._handle("u-abc", "c", is_voice=False)
        r4 = main._handle("u-abc", "d", is_voice=False)
        r5 = main._handle("u-abc", "e", is_voice=False)
    assert "还有吗" not in r1 and "还有吗" not in r2 and "还有吗" not in r3
    assert "还有吗" in r4 or "小册子" in r4, "第 4 段应追加劝收尾"
    assert "还有吗" not in r5, "第 5 段不再追加"


def test_first_message_prepends_welcome(setup):
    main, diary_writer, welcome_store, _ = setup
    with patch.object(diary_writer, "_call_llm", return_value="内容"):
        reply = main._on_message("u-abc", "你好", is_voice=False)
    assert "日记小伙计" in reply, "首次消息应前置欢迎致辞"
    assert welcome_store.is_welcomed("u-abc")


def test_second_message_no_welcome(setup):
    main, diary_writer, welcome_store, _ = setup
    welcome_store.mark_welcomed("u-abc")
    with patch.object(diary_writer, "_call_llm", return_value="内容"):
        reply = main._on_message("u-abc", "今天", is_voice=False)
    assert "日记小伙计" not in reply


def test_unknown_user_rejected(setup):
    main, *_ = setup
    reply = main._handle("u-other", "你好", is_voice=False)
    assert "别人的" in reply
