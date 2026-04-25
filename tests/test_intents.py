"""intents.detect 规则识别测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from intents import Intent, detect


def test_finalize_variants():
    for t in ["结束", "结束。", "结束!", " 结束  ", "收尾", "归档", "打烊"]:
        assert detect(t) == Intent.FINALIZE, f"failed: {t!r}"


def test_undo_variants():
    for t in ["撤回", "删掉", "撤销", "删掉上一段", "撤回。", "删除"]:
        assert detect(t) == Intent.UNDO, f"failed: {t!r}"


def test_help_variants():
    for t in ["/help", "help", "帮助", "怎么用", "使用说明"]:
        assert detect(t) == Intent.HELP, f"failed: {t!r}"


def test_long_text_is_diary_even_if_contains_keyword():
    """借鉴 015fridge 经验:长消息不走规则,即使含关键词也当日记。"""
    text = "今天跟同事开了个会,最后我说结束,然后大家就散了"
    assert detect(text) == Intent.DIARY


def test_empty_is_diary():
    assert detect("") == Intent.DIARY
    assert detect("   ") == Intent.DIARY


def test_diary_simple():
    assert detect("今天天气不错") == Intent.DIARY
    assert detect("吃了面条") == Intent.DIARY


def test_borderline_length():
    # MAX_COMMAND_LEN=15,恰好 15 字符的命令应能识别
    assert detect("结束") == Intent.FINALIZE
    # 16 字符含 "结束" 不识别为命令
    long_text = "今天过得挺累想结束一切烦恼啊啊"
    assert detect(long_text) == Intent.DIARY


def test_case_insensitive_help():
    assert detect("HELP") == Intent.HELP
    assert detect("Help") == Intent.HELP


def test_chat_greetings():
    for t in [
        "你好", "您好", "嗨", "Hi", "HELLO", "在吗", "在么", "我来啦", "我来了",
        "早", "早上好", "晚上好", "下午好", "喂",
        "你好。", "嗨!", "  在吗 ",
    ]:
        assert detect(t) == Intent.CHAT, f"failed: {t!r}"


def test_long_greeting_is_diary():
    """招呼词混入长句要走 DIARY, 不能误判为闲聊。"""
    assert detect("你好啊我今天好累") == Intent.DIARY
    assert detect("早上好今天天气不错") == Intent.DIARY


def test_diary_words_not_chat():
    """常见的日记开头不应被识别为招呼。"""
    assert detect("今天") == Intent.DIARY
    assert detect("今晚") == Intent.DIARY
    assert detect("吃了") == Intent.DIARY


def test_start_diary_keywords():
    for t in [
        "开始记日记", "开始记录", "记日记", "开始", "我要记日记",
        "可以记日记吗", "记一下", "开始写", "开始记日记。", "  开始 ",
    ]:
        assert detect(t) == Intent.START_DIARY, f"failed: {t!r}"


def test_start_diary_not_misclassified():
    """长一点的句子含"开始"不应误判为 START_DIARY。"""
    assert detect("今天工作开始得很早") == Intent.DIARY
    # "我要记日记" 短而精确, 仍走 START_DIARY (这是对的)
    assert detect("我要记日记") == Intent.START_DIARY


# === Bug 复现 + 修复测试 (语气词去除 + 长句子串匹配) ===

def test_start_diary_with_tail_particles():
    """带尾部语气词的指令应被识别为 START_DIARY。

    复现 bug: 用户发"开始记日记吧。" 没切到 diary, 进了 LLM 闲聊。
    根因: _normalize 不去"吧/啦/呀/哦/嘛/呗/啊/哈"等语气词。
    """
    for t in [
        "开始记日记吧", "开始记日记吧。", "开始记日记啊", "开始记日记呀",
        "记日记吧", "记日记呗", "开始啦", "开始呗",
        "我要记日记吧", "记一下吧",
    ]:
        assert detect(t) == Intent.START_DIARY, f"failed: {t!r}"


def test_start_diary_in_long_sentence():
    """长句中含明确切换短语 → START_DIARY。

    复现 bug: 用户发"我今天过得还好我们开始记日记吧, 不说这些闲聊的话了"
    被当 DIARY 走 LLM, LLM 又假装切换。
    """
    long_msgs = [
        "我今天过得还好我们开始记日记吧, 不说这些闲聊的话了",
        "今天事情挺多的, 开始记日记吧",
        "好吧, 开始记录今天的事情",
        "聊够了, 开始写日记",
    ]
    for t in long_msgs:
        assert detect(t) == Intent.START_DIARY, f"failed: {t!r}"


def test_long_sentence_without_phrase_still_diary():
    """长句虽含'开始'/'记'等单字但无完整切换短语 → 仍走 DIARY, 不误触发。"""
    for t in [
        "今天工作开始得很早, 一直到晚上才结束",
        "我开始觉得这件事不太对劲, 但又说不出哪里不对",
        "我们开始忙了一天最后没成什么事",
        "我记得今天有个会议但忘了几点",
    ]:
        assert detect(t) == Intent.DIARY, f"误判 START_DIARY: {t!r}"
