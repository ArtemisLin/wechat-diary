"""main._handle / _on_message 路由测试 (双模式 chat / diary)。

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
    state_file = tmp_path / "session_state.json"
    profile_file = tmp_path / "user_profiles.json"
    monkeypatch.setenv("USER_ID", "u-abc")
    monkeypatch.setenv("DIARY_DIR", str(vault))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("AI_API_KEY", "fake-key")
    import config, users, diary_writer, user_profile, paths, session_state, chat_handler, main
    importlib.reload(config)
    importlib.reload(users)
    importlib.reload(diary_writer)
    importlib.reload(user_profile)
    importlib.reload(paths)
    importlib.reload(session_state)
    importlib.reload(chat_handler)
    importlib.reload(main)
    monkeypatch.setattr(user_profile, "PROFILE_FILE", profile_file)
    monkeypatch.setattr(user_profile, "LEGACY_FILE", tmp_path / "welcomed_users.json")
    monkeypatch.setattr(session_state, "STATE_FILE", state_file)
    chat_handler.reset_history("u-abc")
    # 默认置 active (跳过取名流程, 让旧测试聚焦于路由逻辑)
    user_profile.mark_welcomed("u-abc")
    user_profile.set_name("u-abc", "TestUser")
    return main, diary_writer, user_profile, vault


@pytest.fixture
def diary_setup(setup):
    """复用 setup, 提前进入 diary 模式 (供旧 diary 类测试使用)。"""
    main, *rest = setup
    main._handle("u-abc", "开始记日记", is_voice=False)
    return (main, *rest)


def test_help_intent_returns_help_text(setup):
    main, *_ = setup
    reply = main._handle("u-abc", "帮助", is_voice=False)
    assert "日记 Agent" in reply or "使用指南" in reply


def test_undo_removes_last_block(diary_setup):
    main, diary_writer, _, _ = diary_setup
    with patch.object(diary_writer, "_call_llm", return_value="第一段"):
        main._handle("u-abc", "a", is_voice=False)
    reply = main._handle("u-abc", "撤回", is_voice=False)
    assert "撤" in reply or "好的" in reply


def test_undo_when_nothing_written(diary_setup):
    main, *_ = diary_setup
    reply = main._handle("u-abc", "撤回", is_voice=False)
    assert "撤" in reply or "还" in reply


def test_finalize_returns_closing_line(diary_setup):
    main, diary_writer, _, _ = diary_setup
    with patch.object(diary_writer, "_call_llm", return_value="内容"):
        main._handle("u-abc", "xx", is_voice=False)
    reply = main._handle("u-abc", "结束", is_voice=False)
    # 结束语 10 选 1, 都应该比"今天还没写"长
    assert reply and "还没" not in reply


def test_finalize_when_nothing_written(diary_setup):
    main, *_ = diary_setup
    reply = main._handle("u-abc", "结束", is_voice=False)
    assert "还没" in reply


def test_diary_write_returns_confirm(diary_setup):
    main, diary_writer, _, _ = diary_setup
    with patch.object(diary_writer, "_call_llm", return_value="今天"):
        reply = main._handle("u-abc", "今天吃了面", is_voice=False)
    assert "第 1 段" in reply


def test_nudge_every_4_blocks(diary_setup):
    main, diary_writer, _, _ = diary_setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        r1 = main._handle("u-abc", "a", is_voice=False)
        r2 = main._handle("u-abc", "b", is_voice=False)
        r3 = main._handle("u-abc", "c", is_voice=False)
        r4 = main._handle("u-abc", "d", is_voice=False)
        r5 = main._handle("u-abc", "e", is_voice=False)
    assert "还有吗" not in r1 and "还有吗" not in r2 and "还有吗" not in r3
    assert "还有吗" in r4 or "小册子" in r4, "第 4 段应追加劝收尾"
    assert "还有吗" not in r5, "第 5 段不再追加"


def test_active_user_routes_normally(setup):
    """active 用户消息走主路由 (chat/diary), 不再前置欢迎致辞。"""
    import chat_handler
    main, *_ = setup
    with patch.object(chat_handler, "_call_chat_llm", return_value="reply"):
        reply = main._on_message("u-abc", "今天怎样", is_voice=False)
    assert "日记 Agent" not in reply and "日记小伙计" not in reply


def test_unknown_user_rejected(setup):
    main, *_ = setup
    reply = main._handle("u-other", "你好", is_voice=False)
    assert "不是给你的" in reply or "别人的" in reply


def test_chat_greeting_does_not_write_diary(setup):
    """chat 模式: 招呼词走静态池, 不调 LLM, 不写日记。"""
    main, diary_writer, _, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="不该被调用") as mock_llm:
        reply = main._handle("u-abc", "你好", is_voice=False)
    assert reply, "招呼必须有回复"
    assert "嗨" in reply or "在呢" in reply or "在的" in reply, f"未命中招呼回复池: {reply!r}"
    mock_llm.assert_not_called()
    md_files = list(vault.glob("*.md"))
    assert md_files == [], f"招呼不应写日记文件, 但发现: {md_files}"


def test_chat_greeting_variants_route_to_chat(setup):
    """常见招呼词都走 CHAT 路径(不写日记)。"""
    main, diary_writer, _, vault = setup
    with patch.object(diary_writer, "_call_llm", return_value="x") as mock_llm:
        for greeting in ["嗨", "在吗", "我来啦", "早上好"]:
            main._handle("u-abc", greeting, is_voice=False)
    mock_llm.assert_not_called()
    assert list(vault.glob("*.md")) == []


# === Phase Agent Mode 新增测试 ===

def test_chat_mode_default_after_setup(setup):
    """fixture 默认是 chat 模式。"""
    import session_state
    main, *_ = setup
    s = session_state.load_or_reset("u-abc")
    assert s.mode == "chat"


def test_start_diary_switches_mode(setup):
    """发"开始记日记"后切到 diary, 回复仪式感文案。"""
    import session_state
    main, *_ = setup
    reply = main._handle("u-abc", "开始记日记", is_voice=False)
    assert "记录" in reply or "记今天" in reply or "📖" in reply
    s = session_state.load_or_reset("u-abc")
    assert s.mode == "diary"


def test_start_diary_does_not_write_diary(setup):
    """切换指令本身不写进日记文件。"""
    main, _, _, vault = setup
    main._handle("u-abc", "开始记日记", is_voice=False)
    assert list(vault.glob("*.md")) == []


def test_diary_mode_writes_diary_for_normal_text(diary_setup):
    """diary 模式下普通文本走 DIARY 走 LLM 写笔记。"""
    main, diary_writer, _, _ = diary_setup
    with patch.object(diary_writer, "_call_llm", return_value="今天") as mock_llm:
        reply = main._handle("u-abc", "今天吃了面", is_voice=False)
    assert "第 1 段" in reply
    mock_llm.assert_called_once()


def test_diary_mode_chat_words_still_write(diary_setup):
    """diary 模式下"你好"也当日记内容写, 不切回 chat。"""
    main, diary_writer, _, _ = diary_setup
    with patch.object(diary_writer, "_call_llm", return_value="你好"):
        reply = main._handle("u-abc", "你好", is_voice=False)
    assert "第 1 段" in reply


def test_finalize_in_diary_exits_to_chat(diary_setup):
    """diary 模式说"结束"成功封存后回到 chat 模式。"""
    import session_state
    main, diary_writer, _, _ = diary_setup
    with patch.object(diary_writer, "_call_llm", return_value="x"):
        main._handle("u-abc", "今天", is_voice=False)
    main._handle("u-abc", "结束", is_voice=False)
    s = session_state.load_or_reset("u-abc")
    assert s.mode == "chat"


def test_finalize_in_chat_returns_hint(setup):
    """chat 模式下"结束"返回引导提示, 不写也不切。"""
    main, *_ = setup
    reply = main._handle("u-abc", "结束", is_voice=False)
    assert "闲聊模式" in reply or "还没开始记" in reply


def test_undo_in_chat_returns_hint(setup):
    """chat 模式下"撤回"返回引导提示。"""
    main, *_ = setup
    reply = main._handle("u-abc", "撤回", is_voice=False)
    assert "闲聊模式" in reply or "还没开始记" in reply


def test_chat_mode_routes_normal_text_to_llm(setup):
    """chat 模式下普通文本走 chat_handler, 不写日记。"""
    import chat_handler
    main, diary_writer, _, vault = setup
    with patch.object(chat_handler, "_call_chat_llm", return_value="嗯, 在听") as mock_chat:
        with patch.object(diary_writer, "_call_llm", return_value="x") as mock_polish:
            reply = main._handle("u-abc", "今天怎么这么累啊", is_voice=False)
    assert "嗯" in reply or "在听" in reply
    mock_chat.assert_called_once()
    mock_polish.assert_not_called()
    assert list(vault.glob("*.md")) == []


def test_chat_second_message_appends_cost_reminder(setup):
    """从第 2 条 chat 起回复尾部追加成本提示。"""
    import chat_handler
    main, *_ = setup
    with patch.object(chat_handler, "_call_chat_llm", return_value="嗯"):
        r1 = main._handle("u-abc", "今天累", is_voice=False)
        r2 = main._handle("u-abc", "怎么办", is_voice=False)
    assert "token" not in r1, "第 1 条不应附加成本提示"
    assert "token" in r2 or "开始记日记" in r2, "第 2 条起应附加引导"


def test_help_works_in_both_modes(setup):
    main, *_ = setup
    r1 = main._handle("u-abc", "帮助", is_voice=False)
    main._handle("u-abc", "开始记日记", is_voice=False)
    r2 = main._handle("u-abc", "帮助", is_voice=False)
    assert "使用指南" in r1 and "使用指南" in r2


# === Bug 复现 (root cause: 漏洞 1 + 2) ===

def test_particle_start_diary_actually_switches_mode(setup):
    """带语气词的'开始记日记吧'必须真切到 diary 模式 (非 LLM 假装切换)。"""
    import session_state
    main, *_ = setup
    main._handle("u-abc", "开始记日记吧", is_voice=False)
    s = session_state.load_or_reset("u-abc")
    assert s.mode == "diary", f"应真切到 diary, 实际: {s.mode}"


def test_long_sentence_start_diary_actually_switches_mode(setup):
    """长句含切换短语必须真切到 diary 模式 (避免 LLM 在 chat 模式下假装切换)。"""
    import session_state
    main, *_ = setup
    main._handle("u-abc", "我今天过得还好我们开始记日记吧, 不说这些闲聊的话了", is_voice=False)
    s = session_state.load_or_reset("u-abc")
    assert s.mode == "diary", f"应真切到 diary, 实际: {s.mode}"


def test_particle_start_diary_returns_enter_diary_text(setup):
    """带语气词的切换指令应返回 ENTER_DIARY 文案 (而非 LLM 闲聊回复)。"""
    main, *_ = setup
    reply = main._handle("u-abc", "开始记日记吧", is_voice=False)
    # ENTER_DIARY_REPLIES 都含"📖"或"记今天"或"记录模式"
    assert "📖" in reply or "记录模式" in reply or "记今天" in reply, f"未命中 ENTER_DIARY: {reply!r}"
    # 不应含 chat 模式的 token 提示
    assert "token" not in reply


# === Cluster A.3 取名流程测试 ===

@pytest.fixture
def fresh_user_setup(monkeypatch, tmp_path):
    """全新用户 fixture (state=unknown), 测试取名流程。

    与 setup 不同: setup 直接置 active 跳过取名; 这里保留 unknown 状态。
    """
    vault = tmp_path / "vault"
    state_file = tmp_path / "session_state.json"
    profile_file = tmp_path / "user_profiles.json"
    monkeypatch.setenv("USER_ID", "u-abc")
    monkeypatch.setenv("DIARY_DIR", str(vault))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("AI_API_KEY", "fake-key")
    import config, users, diary_writer, user_profile, paths, session_state, chat_handler, main
    importlib.reload(config)
    importlib.reload(users)
    importlib.reload(diary_writer)
    importlib.reload(user_profile)
    importlib.reload(paths)
    importlib.reload(session_state)
    importlib.reload(chat_handler)
    importlib.reload(main)
    monkeypatch.setattr(user_profile, "PROFILE_FILE", profile_file)
    monkeypatch.setattr(user_profile, "LEGACY_FILE", tmp_path / "welcomed_users.json")
    monkeypatch.setattr(session_state, "STATE_FILE", state_file)
    chat_handler.reset_history("u-abc")
    return main, diary_writer, user_profile, vault


def test_first_message_asks_name(fresh_user_setup):
    """首次消息 (state=unknown): bot 问名字, 标记 awaiting_name, 不写日记。"""
    import chat_handler
    main, diary_writer, user_profile, vault = fresh_user_setup
    with patch.object(chat_handler, "_call_chat_llm", return_value="x"):
        with patch.object(diary_writer, "_call_llm", return_value="x") as mock_llm:
            reply = main._on_message("u-abc", "你好", is_voice=False)
    assert "名字" in reply or "叫你什么" in reply, f"应问名字: {reply!r}"
    p = user_profile.load("u-abc")
    assert p.state == "awaiting_name"
    mock_llm.assert_not_called()
    assert list(vault.glob("*.md")) == []


def test_second_message_sets_name(fresh_user_setup):
    """awaiting_name 状态下用户回复 → 存为名字, 切到 active。"""
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)  # 触发问名字
    reply = main._on_message("u-abc", "谷雨", is_voice=False)
    assert "谷雨" in reply, f"应含名字: {reply!r}"
    p = user_profile.load("u-abc")
    assert p.state == "active"
    assert p.name == "谷雨"


def test_name_too_long_rejected(fresh_user_setup):
    """名字 >10 字 → 回提示重发, 状态保留 awaiting_name。"""
    main, _, user_profile, _ = fresh_user_setup
    main._on_message("u-abc", "你好", is_voice=False)
    long_name = "我希望你叫我谷雨可是这个名字有点长"
    reply = main._on_message("u-abc", long_name, is_voice=False)
    assert "短一点" in reply or "再发" in reply
    p = user_profile.load("u-abc")
    assert p.state == "awaiting_name", "名字太长仍待取名"
    assert p.name is None
