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
    monkeypatch.setenv("DIARY_DIR", str(vault))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("AI_API_KEY", "fake-key")
    import config
    import users
    import diary_writer
    importlib.reload(config)
    importlib.reload(users)
    importlib.reload(diary_writer)
    return config, users, diary_writer, vault


def _today_path(config, vault: Path) -> Path:
    """v2 数据契约: DIARY_DIR/YYYY/YYYY-MM-DD.md"""
    today = config.today_str()
    return vault / today[:4] / f"{today}.md"


def test_first_write_creates_file_with_header(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="今天吃了面"):
        reply, n = diary_writer.write("u-abc", "嗯今天吃了面", is_voice=False)
    path = _today_path(config, vault)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert f"# {config.today_str()}" in content
    assert "今天吃了面" in content
    assert "✍️" in reply
    assert "记下来啦" in reply or "记下" in reply
    assert "继续说" in reply or "结束" in reply
    assert n == 1


def test_same_day_appends_preserves_old(setup, monkeypatch):
    """两次不同分钟的写入: 段头分别独立, 旧内容字节级保留。"""
    config, _, diary_writer, vault = setup
    hhmm_iter = iter(["14:30", "14:35"])
    monkeypatch.setattr(diary_writer.config, "hhmm_str", lambda: next(hhmm_iter))
    with patch.object(diary_writer, "_call_llm", return_value="第一段"):
        diary_writer.write("u-abc", "第一段原文", is_voice=False)
    path = _today_path(config, vault)
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
    content = next(vault.rglob("*.md")).read_text(encoding="utf-8")
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
    assert not list(vault.rglob("*.md")), "空文本不应创建文件"


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
    tmp_files = list(vault.rglob("*.tmp"))
    assert not tmp_files, f"残留 tmp 文件: {tmp_files}"


def test_undo_last_block_removes_only_last(setup, monkeypatch):
    """两次不同分钟写入后 undo 只删最后段头 + 第二段。"""
    config, _, diary_writer, vault = setup
    hhmm_iter = iter(["14:30", "14:35"])
    monkeypatch.setattr(diary_writer.config, "hhmm_str", lambda: next(hhmm_iter))
    with patch.object(diary_writer, "_call_llm", side_effect=["第一段", "第二段"]):
        diary_writer.write("u-abc", "a", is_voice=False)
        diary_writer.write("u-abc", "b", is_voice=False)
    path = _today_path(config, vault)
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
    path = _today_path(config, vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {config.today_str()}\n", encoding="utf-8")
    assert not diary_writer.undo_last_block("u-abc")


def test_finalize_appends_footer(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="段落"):
        diary_writer.write("u-abc", "xx", is_voice=False)
    ok = diary_writer.finalize_today("u-abc")
    assert ok
    content = _today_path(config, vault).read_text(encoding="utf-8")
    assert diary_writer.CLOSING_MARKER in content
    assert content.endswith(")_\n") or content.endswith(")_")


def test_finalize_idempotent(setup):
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="段落"):
        diary_writer.write("u-abc", "xx", is_voice=False)
    diary_writer.finalize_today("u-abc")
    content1 = _today_path(config, vault).read_text(encoding="utf-8")
    diary_writer.finalize_today("u-abc")
    content2 = _today_path(config, vault).read_text(encoding="utf-8")
    assert content1 == content2, "第二次 finalize 不应再追加"


def test_finalize_no_file_returns_false(setup):
    _, _, diary_writer, _ = setup
    assert not diary_writer.finalize_today("u-abc")


# === Phase 0.8 同分钟段头去重测试 ===

def test_same_minute_merges_into_one_header(setup, monkeypatch):
    """同分钟两条消息共享一个段头, 但消息计数 n 仍递增。"""
    config, _, diary_writer, vault = setup
    monkeypatch.setattr(diary_writer.config, "hhmm_str", lambda: "14:30")
    with patch.object(diary_writer, "_call_llm", side_effect=["第一段", "第二段"]):
        _, n1 = diary_writer.write("u-abc", "a", is_voice=False)
        _, n2 = diary_writer.write("u-abc", "b", is_voice=False)
    path = _today_path(config, vault)
    content = path.read_text(encoding="utf-8")
    assert content.count("**14:30**") == 1, f"段头应只出现一次, 实际:\n{content}"
    assert "第一段" in content and "第二段" in content
    assert n1 == 1
    assert n2 == 2


def test_same_minute_undo_only_last_segment(setup, monkeypatch):
    """同分钟两段, undo 只删最后一段, 段头和前段保留。"""
    config, _, diary_writer, vault = setup
    monkeypatch.setattr(diary_writer.config, "hhmm_str", lambda: "14:30")
    with patch.object(diary_writer, "_call_llm", side_effect=["第一段", "第二段"]):
        diary_writer.write("u-abc", "a", is_voice=False)
        diary_writer.write("u-abc", "b", is_voice=False)

    ok = diary_writer.undo_last_block("u-abc")
    assert ok
    content = _today_path(config, vault).read_text(encoding="utf-8")
    assert "第一段" in content
    assert "第二段" not in content
    assert "**14:30**" in content, "段头应保留 (前段还在)"


def test_same_minute_undo_lone_segment_removes_header(setup, monkeypatch):
    """该段头下唯一一段被 undo, 段头一起删 (避免孤儿)。"""
    config, _, diary_writer, vault = setup
    monkeypatch.setattr(diary_writer.config, "hhmm_str", lambda: "14:30")
    with patch.object(diary_writer, "_call_llm", return_value="只有一段"):
        diary_writer.write("u-abc", "a", is_voice=False)

    ok = diary_writer.undo_last_block("u-abc")
    assert ok
    content = _today_path(config, vault).read_text(encoding="utf-8")
    assert "只有一段" not in content
    assert "**14:30**" not in content, "孤儿段头应被删除"


def test_disk_full_returns_specific_alert(setup, monkeypatch):
    """OSError(ENOSPC) → 微信回复"磁盘可能满了"特定告警, 不是通用错误。"""
    import errno
    _, _, diary_writer, _ = setup

    def boom(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    with patch.object(diary_writer, "_call_llm", return_value="x"):
        with patch.object(diary_writer, "_atomic_write", side_effect=boom):
            reply, n = diary_writer.write("u-abc", "x", is_voice=False)
    assert n == 0
    assert "磁盘" in reply or "DIARY_DIR" in reply, f"应给磁盘满特定提示, 实际: {reply!r}"


def test_other_oserror_returns_generic_message(setup):
    """非 ENOSPC 的 OSError → 通用提示, 不混淆为磁盘满。"""
    _, _, diary_writer, _ = setup

    def boom(*args, **kwargs):
        raise OSError("permission denied")  # errno=None / 其他错误

    with patch.object(diary_writer, "_call_llm", return_value="x"):
        with patch.object(diary_writer, "_atomic_write", side_effect=boom):
            reply, n = diary_writer.write("u-abc", "x", is_voice=False)
    assert n == 0
    assert "磁盘" not in reply, f"非磁盘满错误不该提磁盘, 实际: {reply!r}"
    assert "稍后再试" in reply or "出了点问题" in reply


def test_count_messages_independent_of_header_merge(setup, monkeypatch):
    """count_messages 数实际消息条数, 不受段头合并影响。"""
    config, _, diary_writer, vault = setup
    # 三条同分钟 + 一条不同分钟 = 4 条消息, 但只有 2 个段头
    times = iter(["14:30", "14:30", "14:30", "14:35"])
    monkeypatch.setattr(diary_writer.config, "hhmm_str", lambda: next(times))
    with patch.object(diary_writer, "_call_llm", side_effect=["m1", "m2", "m3", "m4"]):
        for i in range(4):
            diary_writer.write("u-abc", f"msg{i}", is_voice=False)
    path = _today_path(config, vault)
    content = path.read_text(encoding="utf-8")
    assert content.count("**14:30**") == 1
    assert content.count("**14:35**") == 1
    assert diary_writer.count_messages(path) == 4


# === Cluster B.1: 按年分目录测试 ===

def test_diary_path_uses_yearly_subdir(setup):
    """新写入文件应在 YYYY/ 子目录下。"""
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        diary_writer.write("u-abc", "x", is_voice=False)
    today = config.today_str()        # "2026-04-30"
    year = today[:4]                   # "2026"
    expected = vault / year / f"{today}.md"
    assert expected.exists(), f"应在年份子目录: 实际 vault 内容 {list(vault.rglob('*'))}"


def test_today_has_content_reads_yearly_subdir(setup):
    """today_has_content 也要走新路径。"""
    _, _, diary_writer, _ = setup
    assert not diary_writer.today_has_content("u-abc")
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        diary_writer.write("u-abc", "x", is_voice=False)
    assert diary_writer.today_has_content("u-abc")


def test_undo_works_with_yearly_subdir(setup, monkeypatch):
    """undo 在新路径下工作。"""
    config, _, diary_writer, vault = setup
    monkeypatch.setattr(diary_writer.config, "hhmm_str", lambda: "14:30")
    with patch.object(diary_writer, "_call_llm", return_value="只一段"):
        diary_writer.write("u-abc", "x", is_voice=False)
    ok = diary_writer.undo_last_block("u-abc")
    assert ok
    today = config.today_str()
    path = vault / today[:4] / f"{today}.md"
    assert "只一段" not in path.read_text(encoding="utf-8")


def test_finalize_works_with_yearly_subdir(setup):
    """finalize 在新路径下工作。"""
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="段落"):
        diary_writer.write("u-abc", "x", is_voice=False)
    ok = diary_writer.finalize_today("u-abc")
    assert ok
    today = config.today_str()
    path = vault / today[:4] / f"{today}.md"
    assert diary_writer.CLOSING_MARKER in path.read_text(encoding="utf-8")


# === v2 B.2: frontmatter 测试 ===

def test_new_file_has_frontmatter(setup):
    """新建文件头部是 YAML frontmatter (date/weekday/source), 之后才是 # 日期。"""
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        diary_writer.write("u-abc", "x", is_voice=False)
    content = _today_path(config, vault).read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert f"date: {config.today_str()}\n" in content
    assert "weekday: 周" in content
    assert "source: wechat-diary\n" in content
    assert f"# {config.today_str()}" in content


def test_frontmatter_not_counted_as_message(setup):
    """frontmatter 块不算消息, count_messages 仍只数正文。"""
    config, _, diary_writer, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        diary_writer.write("u-abc", "x", is_voice=False)
    assert diary_writer.count_messages(_today_path(config, vault)) == 1