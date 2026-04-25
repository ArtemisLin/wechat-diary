"""diary_writer 测试。"""
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
    import config
    import users
    import diary_writer
    importlib.reload(config)
    importlib.reload(users)
    importlib.reload(diary_writer)
    return config, users, diary_writer, vault


def test_first_write_creates_file_with_header(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="今天吃了面"):
        reply, n = diary_writer.write("u-abc", "嗯今天吃了面", is_voice=False)
    path = vault / f"{config.today_str()}.md"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content.startswith(f"# {config.today_str()}\n")
    assert "今天吃了面" in content
    assert "✍️" in reply
    assert "已存入今天笔记" in reply
    assert "继续说" in reply or "结束" in reply
    assert n == 1


def test_same_day_appends_preserves_old(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="第一段"):
        diary_writer.write("u-abc", "第一段原文", is_voice=False)
    path = vault / f"{config.today_str()}.md"
    before = path.read_text(encoding="utf-8")

    with patch.object(diary_writer, "_call_llm", return_value="第二段"):
        reply, n = diary_writer.write("u-abc", "第二段原文", is_voice=True)
    after = path.read_text(encoding="utf-8")

    assert after.startswith(before), "旧内容必须逐字节保留"
    assert "第二段" in after
    assert after.count("\n**") == 2, "两段时间戳标头"
    assert n == 2


def test_llm_failure_falls_back_to_raw(setup):
    """LLM 抛网络错误 → 原文回落 + 微信回复带"AI 暂时不通"提示。"""
    _, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm",
                      side_effect=diary_writer.LLMError("network", "timeout")):
        reply, _ = diary_writer.write("u-abc", "原文本身就挺好", is_voice=False)
    content = next(vault.glob("*.md")).read_text(encoding="utf-8")
    assert "原文本身就挺好" in content
    assert "AI 暂时不通" in reply or "原文已存" in reply


def test_llm_auth_error_gives_specific_hint(setup):
    """401 → 微信回复带"AI Key 好像不对"。"""
    _, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm",
                      side_effect=diary_writer.LLMError("auth")):
        reply, _ = diary_writer.write("u-abc", "今天累", is_voice=False)
    assert "Key" in reply or ".env" in reply


def test_llm_balance_error_gives_specific_hint(setup):
    """402 → 微信回复带"AI 余额用完啦"。"""
    _, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm",
                      side_effect=diary_writer.LLMError("balance")):
        reply, _ = diary_writer.write("u-abc", "今天累", is_voice=False)
    assert "余额" in reply or "充值" in reply


def test_llm_rate_limit_error_gives_specific_hint(setup):
    """429 → 微信回复带"AI 调用太频繁"。"""
    _, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm",
                      side_effect=diary_writer.LLMError("rate_limit")):
        reply, _ = diary_writer.write("u-abc", "今天累", is_voice=False)
    assert "频繁" in reply or "rate" in reply.lower()


def test_llm_server_error_gives_specific_hint(setup):
    """5xx → 微信回复带"AI 服务异常"。"""
    _, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm",
                      side_effect=diary_writer.LLMError("server")):
        reply, _ = diary_writer.write("u-abc", "今天累", is_voice=False)
    assert "服务" in reply or "异常" in reply


def test_llm_no_key_error_gives_specific_hint(setup):
    """没配 AI Key → 微信回复带"没配 AI Key"。"""
    _, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm",
                      side_effect=diary_writer.LLMError("no_key")):
        reply, _ = diary_writer.write("u-abc", "今天累", is_voice=False)
    assert "Key" in reply


def test_empty_text_returns_friendly_message(setup):
    _, _, diary_writer, vault = setup
    reply, n = diary_writer.write("u-abc", "   ", is_voice=True)
    assert "再说一次" in reply
    assert n == 0
    assert not list(vault.glob("*.md")), "空文本不应创建文件"


def test_today_has_content_true_after_write(setup):
    _, _, diary_writer, _ = setup
    assert not diary_writer.today_has_content("u-abc")
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        diary_writer.write("u-abc", "x", is_voice=False)
    assert diary_writer.today_has_content("u-abc")


def test_voice_mark_in_reply(setup):
    _, _, diary_writer, _ = setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        reply_voice, _ = diary_writer.write("u-abc", "x", is_voice=True)
        reply_text, _ = diary_writer.write("u-abc", "y", is_voice=False)
    assert "🎤" in reply_voice
    assert "🎤" not in reply_text


def test_no_hardcoded_username_or_path():
    """硬约束:代码里 grep 不到硬编码的用户名/个人路径。"""
    import diary_writer as dw
    import users as us
    import config as cf
    for mod in (dw, us, cf):
        src_text = Path(mod.__file__).read_text(encoding="utf-8")
        assert "\u8c37\u96e8" not in src_text, f"{mod.__name__} 含硬编码'谷雨'"  # 谷雨
        assert "Users/Aoc" not in src_text, f"{mod.__name__} 含硬编码个人路径"


def test_atomic_write_leaves_no_tmp(setup):
    _, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="hi"):
        diary_writer.write("u-abc", "hi", is_voice=False)
    tmp_files = list(vault.glob("*.tmp"))
    assert not tmp_files, f"残留 tmp 文件: {tmp_files}"


def test_undo_last_block_removes_only_last(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", side_effect=["第一段", "第二段"]):
        diary_writer.write("u-abc", "a", is_voice=False)
        diary_writer.write("u-abc", "b", is_voice=False)
    path = vault / f"{config.today_str()}.md"
    assert path.read_text(encoding="utf-8").count("\n**") == 2

    ok = diary_writer.undo_last_block("u-abc")
    assert ok
    after = path.read_text(encoding="utf-8")
    assert "第一段" in after
    assert "第二段" not in after
    assert after.count("\n**") == 1


def test_undo_when_no_file(setup):
    _, _, diary_writer, _ = setup
    assert not diary_writer.undo_last_block("u-abc")


def test_undo_when_only_header(setup, monkeypatch):
    config, _, diary_writer, vault = setup
    path = vault / f"{config.today_str()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {config.today_str()}\n", encoding="utf-8")
    assert not diary_writer.undo_last_block("u-abc")


def test_finalize_appends_footer(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="段落"):
        diary_writer.write("u-abc", "xx", is_voice=False)
    ok = diary_writer.finalize_today("u-abc")
    assert ok
    content = (vault / f"{config.today_str()}.md").read_text(encoding="utf-8")
    assert diary_writer.CLOSING_MARKER in content
    assert content.endswith(")_\n") or content.endswith(")_")


def test_finalize_idempotent(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="段落"):
        diary_writer.write("u-abc", "xx", is_voice=False)
    diary_writer.finalize_today("u-abc")
    content1 = (vault / f"{config.today_str()}.md").read_text(encoding="utf-8")
    diary_writer.finalize_today("u-abc")
    content2 = (vault / f"{config.today_str()}.md").read_text(encoding="utf-8")
    assert content1 == content2, "第二次 finalize 不应再追加"


def test_finalize_no_file_returns_false(setup):
    _, _, diary_writer, _ = setup
    assert not diary_writer.finalize_today("u-abc")