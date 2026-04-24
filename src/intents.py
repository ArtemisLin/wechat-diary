"""指令识别:从用户消息文本判断是日记、还是命令(结束/撤回/帮助等)。

设计原则:
- 规则优先、零延迟(<1ms),只在消息**很短**时走规则
- >15 字符的消息直接判为日记,不做规则匹配(借鉴 015fridge 经验:长复合句交给 AI/日记逻辑)
- 尾部空白、全角/半角、常见标点都要容忍
"""
from __future__ import annotations

from enum import Enum

MAX_COMMAND_LEN = 15


class Intent(Enum):
    DIARY = "diary"           # 默认:写日记
    FINALIZE = "finalize"     # 结束今日
    UNDO = "undo"             # 撤回上一段
    HELP = "help"             # 看帮助


# 规则关键词(精确匹配完整消息去除标点后)
_FINALIZE_KEYWORDS = {"结束", "收尾", "收工", "打烊", "归档", "完了"}
_UNDO_KEYWORDS = {"撤回", "删掉", "删除", "撤销", "删掉上一段", "删掉上条", "撤回上一段"}
_HELP_KEYWORDS = {"/help", "help", "帮助", "怎么用", "使用说明", "菜单"}


_STRIP_CHARS = "。!?!?,,、~ \t\n\u3000"


def _normalize(text: str) -> str:
    """去掉首尾空白 + 末尾标点,小写化,全角空格归一。"""
    s = text.strip().replace("\u3000", " ")
    s = s.rstrip(_STRIP_CHARS).lstrip()
    return s.lower()


def detect(text: str) -> Intent:
    """识别文本意图。消息过长直接判 DIARY(符合"零门槛写日记"诉求)。"""
    if not text:
        return Intent.DIARY
    if len(text) > MAX_COMMAND_LEN:
        return Intent.DIARY
    norm = _normalize(text)
    if norm in _FINALIZE_KEYWORDS:
        return Intent.FINALIZE
    if norm in _UNDO_KEYWORDS:
        return Intent.UNDO
    if norm in _HELP_KEYWORDS:
        return Intent.HELP
    return Intent.DIARY
