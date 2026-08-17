"""main._handle / _dispatch / _on_message 路由测试 (v0.3 单模式: 发什么记什么)。

不启动 iLink/scheduler,只测消息路由到正确分支。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _reload_all(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    state_file = tmp_path / "session_state.json"
    profile_file = tmp_path / "user_profiles.json"
    monkeypatch.setenv("USER_ID", "u-abc")
    monkeypatch.setenv("DIARY_DIR", str(vault))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("AI_API_KEY", "fake-key")
    import config, users, diary_writer, user_profile, paths, session_state, chat_handler, welcome, main
    for m in (config, users, diary_writer, user_profile, paths, session_state, chat_handler, welcome, main):
        importlib.reload(m)
    monkeypatch.setattr(user_profile, "PROFILE_FILE", profile_file)
    monkeypatch.setattr(user_profile, "LEGACY_FILE", tmp_path / "welcomed_users.json")
    monkeypatch.setattr(session_state, "STATE_FILE", state_file)
    chat_handler.reset_history("u-abc")
    return main, diary_writer, user_profile, vault


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """active 用户 (跳过取名流程, 聚焦路由)。"""
    main, diary_writer, user_profile, vault = _reload_all(monkeypatch, tmp_path)
    user_profile.mark_welcomed("u-abc")
    user_profile.set_name("u-abc", "TestUser")
    return main, diary_writer, user_profile, vault


@pytest.fixture
def fresh_user_setup(monkeypatch, tmp_path):
    """全新用户 (state=unknown), 测试欢迎/取名流程。"""
    return _reload_all(monkeypatch, tmp_path)


def _md_text(vault) -> str:
    files = list(vault.rglob("*.md"))
    return files[0].read_text(encoding="utf-8") if files else ""


# ── 单模式核心: 发什么记什么 ──────────────────────────────────────────────

def test_plain_text_is_recorded_without_any_opener(setup):
    """不用「开始记日记」, 普通文本直接落库, 回执带段数。"""
    main, _, _, vault = setup
    reply = main._handle("u-abc", "今天吃了面", is_voice=False)
    assert "第 1 段" in reply
    assert "今天吃了面" in _md_text(vault)


def test_first_of_day_has_full_tips_then_clean(setup):
    main, *_ = setup
    r1 = main._handle("u-abc", "a", is_voice=False)
    r2 = main._handle("u-abc", "b", is_voice=False)
    r5 = main._handle("u-abc", "e", is_voice=False)
    assert "今天第一条" in r1 and "撤回" in r1 and "帮助" in r1
    assert "今天第一条" not in r2 and "撤回" not in r2
    assert "还有吗" not in r5 and "小册子" not in r5, "劝收尾提示已砍"


def test_no_llm_call_even_with_key(setup):
    """配了 AI_API_KEY 也不发任何 LLM 请求。"""
    import chat_handler
    main, diary_writer, _, _ = setup
    with patch.object(diary_writer, "_call_llm", return_value="不该调") as m1, \
         patch.object(chat_handler, "_call_chat_llm", return_value="不该调") as m2:
        main._handle("u-abc", "今天怎么这么累啊", is_voice=False)
        main._handle("u-abc", "你好", is_voice=False)
    m1.assert_not_called()
    m2.assert_not_called()


def test_help_intent_returns_help_text(setup):
    main, *_ = setup
    reply = main._handle("u-abc", "帮助", is_voice=False)
    assert "使用指南" in reply and "在吗" in reply and "撤回" in reply
    assert "两种模式" not in reply and "闲聊模式" not in reply


def test_unknown_user_rejected(setup):
    main, *_ = setup
    reply = main._handle("u-other", "你好", is_voice=False)
    assert "不是给你的" in reply


# ── 探活: 回状态, 不落库 ──────────────────────────────────────────────────

def test_ping_replies_status_and_does_not_record(setup):
    main, _, _, vault = setup
    r0 = main._handle("u-abc", "在吗", is_voice=False)
    assert "在的" in r0
    assert not list(vault.rglob("*.md")), "「在吗」不该落库"
    main._handle("u-abc", "第一条", is_voice=False)
    main._handle("u-abc", "第二条", is_voice=False)
    r2 = main._handle("u-abc", "在吗在吗", is_voice=False)
    assert "已记 2 段" in r2, f"探活应报今天段数: {r2!r}"
    assert "在吗" not in _md_text(vault)


def test_ping_variants_never_recorded(setup):
    main, _, _, vault = setup
    for g in ["嗨", "在吗", "在不在", "你在吗", "我来啦", "早上好", "测试", "hello", "哈喽"]:
        main._handle("u-abc", g, is_voice=False)
    assert not list(vault.rglob("*.md")), f"探活词落库了: {_md_text(vault)!r}"


# ── 命令 ──────────────────────────────────────────────────────────────────

def test_undo_removes_last_and_previews(setup):
    main, _, _, vault = setup
    main._handle("u-abc", "第一条内容", is_voice=False)
    main._handle("u-abc", "又想起一件事", is_voice=False)
    reply = main._handle("u-abc", "撤回", is_voice=False)
    assert "撤掉了「又想起一件事」" in reply, f"撤回应带预览: {reply!r}"
    txt = _md_text(vault)
    assert "第一条内容" in txt and "又想起一件事" not in txt


def test_undo_when_nothing_written(setup):
    main, *_ = setup
    reply = main._handle("u-abc", "撤回", is_voice=False)
    assert "没东西可撤" in reply


def test_finalize_is_optional_ritual_not_mode_switch(setup):
    """「结束」写封存标记; 之后继续发照样记。"""
    main, diary_writer, _, vault = setup
    main._handle("u-abc", "xx", is_voice=False)
    reply = main._handle("u-abc", "结束", is_voice=False)
    assert reply and "还没" not in reply
    assert diary_writer.CLOSING_MARKER in _md_text(vault)
    r = main._handle("u-abc", "结束之后又想到一句", is_voice=False)
    assert "第 2 段" in r, "「结束」后继续发必须照记(单模式没有模式可退)"
    assert "结束之后又想到一句" in _md_text(vault)


def test_finalize_when_nothing_written(setup):
    main, *_ = setup
    reply = main._handle("u-abc", "结束", is_voice=False)
    assert "还没" in reply


def test_start_diary_short_is_obsolete_reply_not_recorded(setup):
    """老习惯「开始记日记」: 告知不用了, 不落库。"""
    main, _, _, vault = setup
    for msg in ["开始记日记", "开始记日记吧", "记日记"]:
        reply = main._handle("u-abc", msg, is_voice=False)
        assert "不用" in reply and "直接发" in reply, f"{msg!r}: {reply!r}"
    assert not list(vault.rglob("*.md"))


def test_start_diary_long_sentence_recorded_whole(setup):
    """长句含开始短语是内容, 整句照记 + 顺带告知。"""
    main, _, _, vault = setup
    reply = main._handle("u-abc", "我今天过得还好我们开始记日记吧, 不说这些闲聊的话了", is_voice=False)
    assert "第 1 段" in reply and "不用发「开始记日记」" in reply
    assert "我今天过得还好" in _md_text(vault)


def test_rename_command(setup):
    main, _, user_profile, vault = setup
    reply = main._handle("u-abc", "叫我谷雨", is_voice=False)
    assert "谷雨" in reply
    assert user_profile.load("u-abc").name == "谷雨"
    assert not list(vault.rglob("*.md")), "改名命令不落库"


def test_casual_jiao_wo_sentence_is_content_not_rename(setup):
    """「同事叫我帮忙了」「你叫我干嘛」「叫我起床」是内容, 照记, 不改名。"""
    main, _, user_profile, vault = setup
    for msg in ("同事叫我帮忙了", "你叫我干嘛", "叫我起床"):
        main._handle("u-abc", msg, is_voice=False)
        assert user_profile.load("u-abc").name == "TestUser", f"{msg!r} 误改名"
    assert "同事叫我帮忙了" in _md_text(vault)


def test_inline_name_with_start_diary(setup):
    main, _, user_profile, _ = setup
    reply = main._handle("u-abc", "叫我小明, 开始记日记", is_voice=False)
    assert user_profile.load("u-abc").name == "小明"
    assert "小明" in reply


# ── 首次见面 / 取名 ────────────────────────────────────────────────────────

def test_first_message_content_recorded_then_welcome(fresh_user_setup):
    """首条就是内容: 先记下(内容优先), 再自我介绍问名字。"""
    main, _, user_profile, vault = fresh_user_setup
    reply = main._on_message("u-abc", "今天试了新的手冲豆子", is_voice=False)
    assert "记下来啦" in reply and "随手记 Agent" in reply and "叫你什么名字" in reply
    assert "今天试了新的手冲豆子" in _md_text(vault)
    assert user_profile.load("u-abc").state == "awaiting_name"


def test_first_message_ping_gets_welcome_only(fresh_user_setup):
    main, _, user_profile, vault = fresh_user_setup
    reply = main._on_message("u-abc", "你好", is_voice=False)
    assert "随手记 Agent" in reply and "跳过" in reply
    assert "比如「谷雨」" not in reply and "叫我XX」;" not in reply, "啰嗦示例已删"
    assert not list(vault.rglob("*.md"))
    assert user_profile.load("u-abc").state == "awaiting_name"


def test_welcome_mentions_diary_dir(fresh_user_setup, tmp_path):
    main, *_ = fresh_user_setup
    reply = main._on_message("u-abc", "你好", is_voice=False)
    assert str(tmp_path / "vault") in reply and "DIARY_DIR" in reply


def test_second_message_sets_name(fresh_user_setup):
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    reply = main._on_message("u-abc", "谷雨", is_voice=False)
    assert "谷雨" in reply and "直接发" in reply
    p = user_profile.load("u-abc")
    assert p.state == "active" and p.name == "谷雨"


def test_name_extracted_from_call_me_sentence(fresh_user_setup):
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    main._on_message("u-abc", "叫我谷雨就行", is_voice=False)
    assert user_profile.load("u-abc").name == "谷雨"


def test_long_unnamable_reply_recorded_and_naming_ends(fresh_user_setup):
    """取名只问一轮: 提不出名字的长句是内容, 记下并结束取名, 不追问。"""
    main, _, user_profile, vault = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    long_msg = "我希望你叫我谷雨谷雨谷雨可是这个名字有点长"
    reply = main._on_message("u-abc", long_msg, is_voice=False)
    assert "记下来啦" in reply and "叫我XX" in reply
    assert long_msg in _md_text(vault), "取名流程不得吞内容"
    p = user_profile.load("u-abc")
    assert p.state == "active" and p.name is None


def test_short_unclear_reply_asks_once_more(fresh_user_setup):
    main, _, user_profile, vault = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    reply = main._on_message("u-abc", "什么名字都行吧", is_voice=False)
    # 「什么都行」类是拒绝 → skip; 真正看不出的短句才再问。两种都不能落库
    assert user_profile.load("u-abc").state == "active" or "再发" in reply
    assert not list(vault.rglob("*.md"))


def test_help_during_awaiting_name_not_taken_as_name(fresh_user_setup):
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    reply = main._on_message("u-abc", "帮助", is_voice=False)
    assert "使用指南" in reply and "称呼" in reply
    p = user_profile.load("u-abc")
    assert p.state == "awaiting_name" and p.name is None


def test_greeting_during_awaiting_name_not_taken_as_name(fresh_user_setup):
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    reply = main._on_message("u-abc", "在吗", is_voice=False)
    assert "在的" in reply and "称呼" in reply
    p = user_profile.load("u-abc")
    assert p.state == "awaiting_name" and p.name is None


def test_command_during_awaiting_name_passes_through(fresh_user_setup):
    """取名流程中发命令(开始记日记/撤回): 放行, 结束取名, 附"以后可补名"。"""
    main, _, user_profile, vault = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    reply = main._on_message("u-abc", "开始记日记", is_voice=False)
    assert "叫我XX" in reply
    p = user_profile.load("u-abc")
    assert p.state == "active" and p.name is None
    main._on_message("u-abc", "今天很好", is_voice=False)
    assert "今天很好" in _md_text(vault)


def test_refuse_naming_skips(fresh_user_setup):
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    reply = main._on_message("u-abc", "跳过", is_voice=False)
    assert "直接发" in reply and "开始记日记" not in reply
    p = user_profile.load("u-abc")
    assert p.state == "active" and p.name is None


def test_refusal_with_politeness_skips_naming(fresh_user_setup):
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    main._on_message("u-abc", "不用了谢谢", is_voice=False)
    p = user_profile.load("u-abc")
    assert p.name is None and p.state == "active"


def test_inline_name_with_start_diary_awaiting(fresh_user_setup):
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    reply = main._on_message("u-abc", "叫我小明, 开始记日记", is_voice=False)
    assert user_profile.load("u-abc").name == "小明"
    assert "小明" in reply


# ── 跨天 (逻辑日) ─────────────────────────────────────────────────────────

def test_cross_day_auto_seals_yesterday_and_records_today(setup, monkeypatch):
    import config, session_state, diary_writer
    main, _, _, vault = setup
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-08-15")
    main._on_message("u-abc", "昨晚的内容", is_voice=False)
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-08-16")
    reply = main._on_message("u-abc", "新一天的内容", is_voice=False)
    assert "昨天的已自动收尾" in reply
    assert "今天第一条" not in reply, "跨天告知与首条前缀语义重复, 只留一句"
    y = (vault / "2026" / "2026-08-15.md").read_text(encoding="utf-8")
    t = (vault / "2026" / "2026-08-16.md").read_text(encoding="utf-8")
    assert diary_writer.CLOSING_MARKER in y and "昨晚的内容" in y
    assert "新一天的内容" in t and diary_writer.CLOSING_MARKER not in t


def test_cross_day_without_yesterday_content_no_notice(setup, monkeypatch):
    import config
    main, *_ = setup
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-08-15")
    main._on_message("u-abc", "在吗", is_voice=False)  # 昨天只探活, 没内容
    monkeypatch.setattr(config, "logical_today_str", lambda now=None: "2026-08-16")
    reply = main._on_message("u-abc", "今天的", is_voice=False)
    assert "自动收尾" not in reply, "昨天没内容就不该说封存了"


# ── 离线提示 ──────────────────────────────────────────────────────────────

def test_offline_notice_none_within_24h(setup):
    import time
    main, *_ = setup
    assert main._compute_offline_notice({}) is None
    assert main._compute_offline_notice({"last_alive_ts": int(time.time()) - 20 * 3600}) is None, \
        "24h 内实测可补收, 不该吓唬用户"


def test_offline_notice_present_after_24h(setup):
    import time
    main, *_ = setup
    notice = main._compute_offline_notice({"last_alive_ts": int(time.time()) - 30 * 3600})
    assert notice and "超过一天" in notice


def test_offline_notice_appended_once_to_first_reply(setup):
    main, *_ = setup
    main._offline_notice = "(小提示: 测试离线提示)"
    r1 = main._on_message("u-abc", "帮助", is_voice=False)
    assert "测试离线提示" in r1
    r2 = main._on_message("u-abc", "帮助", is_voice=False)
    assert "测试离线提示" not in r2
