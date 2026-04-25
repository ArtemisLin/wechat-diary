"""chat_handler LLM 闲聊调用测试 (LLM 全程 mock)。"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("USER_ID", "u-abc")
    monkeypatch.setenv("VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("AI_API_KEY", "fake-key")
    monkeypatch.setenv("AI_BASE_URL", "https://example.com/chat")
    monkeypatch.setenv("AI_MODEL", "deepseek-v4-flash")
    import config, paths, diary_writer, chat_handler
    importlib.reload(config)
    importlib.reload(paths)
    importlib.reload(diary_writer)
    importlib.reload(chat_handler)
    return chat_handler


def test_chat_calls_llm_and_returns_reply(setup):
    ch = setup
    ch.reset_history("u-abc")
    with patch.object(ch, "_call_chat_llm", return_value="嗨~ 在的"):
        reply = ch.chat("u-abc", "你好啊")
    assert reply == "嗨~ 在的"


def test_chat_history_appends_user_and_assistant(setup):
    ch = setup
    ch.reset_history("u-abc")
    with patch.object(ch, "_call_chat_llm", return_value="A1"):
        ch.chat("u-abc", "U1")
    with patch.object(ch, "_call_chat_llm") as mock_llm:
        mock_llm.return_value = "A2"
        ch.chat("u-abc", "U2")
        # 第二次调用时 messages 应该包含: system + 之前的 (U1, A1) + 当前 U2
        call_args = mock_llm.call_args[0][0]
        roles = [m["role"] for m in call_args]
        assert roles[0] == "system"
        assert roles[-1] == "user"
        contents = [m["content"] for m in call_args]
        assert "U1" in contents
        assert "A1" in contents
        assert "U2" in contents


def test_chat_history_caps_at_5_turns(setup):
    """超过 5 轮历史时, 最早的轮被截断。"""
    ch = setup
    ch.reset_history("u-abc")
    with patch.object(ch, "_call_chat_llm", return_value="reply"):
        for i in range(7):
            ch.chat("u-abc", f"msg-{i}")

    with patch.object(ch, "_call_chat_llm") as mock_llm:
        mock_llm.return_value = "reply"
        ch.chat("u-abc", "latest")
        call_args = mock_llm.call_args[0][0]
        contents = [m["content"] for m in call_args]
        # 最早的 msg-0, msg-1 应已被滚出
        assert "msg-0" not in contents
        assert "msg-1" not in contents
        # 最近的应在
        assert "msg-6" in contents
        assert "latest" in contents


def test_chat_falls_back_when_llm_fails(setup):
    ch = setup
    ch.reset_history("u-abc")
    with patch.object(ch, "_call_chat_llm", return_value=None):
        reply = ch.chat("u-abc", "你好")
    assert reply in ch.CHAT_FALLBACK_REPLIES


def test_reset_history_clears_user(setup):
    ch = setup
    with patch.object(ch, "_call_chat_llm", return_value="X"):
        ch.chat("u-abc", "msg")
    ch.reset_history("u-abc")
    with patch.object(ch, "_call_chat_llm") as mock_llm:
        mock_llm.return_value = "Y"
        ch.chat("u-abc", "new")
        contents = [m["content"] for m in mock_llm.call_args[0][0]]
        assert "msg" not in contents


def test_chat_no_api_key_returns_fallback(setup, monkeypatch):
    import config
    monkeypatch.setattr(config, "AI_API_KEY", "")
    ch = setup
    ch.reset_history("u-abc")
    reply = ch.chat("u-abc", "你好")
    assert reply in ch.CHAT_FALLBACK_REPLIES
