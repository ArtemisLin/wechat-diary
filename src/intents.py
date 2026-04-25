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
    CHAT = "chat"             # 闲聊招呼(短消息且命中招呼词, 不写日记只回应)
    START_DIARY = "start_diary"  # chat 模式下显式进入记录模式


# 规则关键词(精确匹配完整消息去除标点后)
_FINALIZE_KEYWORDS = {"结束", "收尾", "收工", "打烊", "归档", "完了"}
_UNDO_KEYWORDS = {"撤回", "删掉", "删除", "撤销", "删掉上一段", "删掉上条", "撤回上一段"}
_HELP_KEYWORDS = {"/help", "help", "帮助", "怎么用", "使用说明", "菜单"}

# Phase 0.B 最小版闲聊识别: 仅"招呼"一类, 完整 6 类 CHAT 留 Phase 1.3。
# 词集保守, 不包含"今天/今晚"等可能开启日记的词, 避免误判。
_CHAT_GREETING_KEYWORDS = {
    "你好", "您好", "嗨", "hi", "hello", "hihi", "halo",
    "在吗", "在么", "在不在", "在嘛", "喂",
    "我来啦", "我来了", "来啦", "我来",
    "早", "早安", "早上好", "中午好", "下午好", "晚上好",
}

# Phase Agent Mode: 显式进入 diary 模式 (在 chat 模式下生效)
_START_DIARY_KEYWORDS = {
    "开始记日记", "开始记录", "记日记", "开始", "开始写",
    "我要记日记", "我要写日记", "我要记录",
    "可以记日记吗", "可以开始吗", "记一下",
}


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
    if norm in _START_DIARY_KEYWORDS:
        return Intent.START_DIARY
    if norm in _CHAT_GREETING_KEYWORDS:
        return Intent.CHAT
    return Intent.DIARY
