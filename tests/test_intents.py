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
