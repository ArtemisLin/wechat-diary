"""指令识别:从用户消息文本判断是日记、还是命令(结束/撤回/帮助等)。

设计原则:
- 规则优先、零延迟(<1ms),只在消息**很短**时走规则
- >15 字符的消息默认判为日记,但例外: 长句若含明确切换短语 → START_DIARY
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


_STRIP_CHARS = "。!?!?,,、~ \t\n　"

# Phase Debug: 中文尾部语气词集合
# 用户口语指令常带"开始记日记吧/记日记呗/开始啦"等语气词, normalize 时全部去掉
# 还原为核心命令 → 让 _START_DIARY_KEYWORDS 等词集能命中。
_TAIL_PARTICLES = ("吧", "啊", "啦", "呀", "哦", "嘛", "呗", "哈")

# Phase Debug: 切换短语子串匹配 (任意长度都生效, 优先级最高)
# 用于:
# (1) 长句中含切换意图 ("我今天还行我们开始记日记吧, 不说闲聊了")
# (2) 短句带语气词 ("开始记日记呀!") - 此时 _normalize 已剥语气词,
#     走 _START_DIARY_KEYWORDS; 但短句长度刚好命中边界 (=15) 时也走这里兜底
# 边界保守: 不写"开始"单字, 避免"今天工作开始得很早"等长句误触发。
_START_DIARY_PHRASES = (
    "开始记日记",
    "开始记录",
    "开始写日记",
    "我们记日记",
)


def _normalize(text: str) -> str:
    """去掉首尾空白 + 末尾标点 + 尾部语气词, 小写化, 全角空格归一。"""
    s = text.strip().replace("　", " ")
    s = s.rstrip(_STRIP_CHARS).lstrip().lower()
    # 反复去尾部语气词 + 标点 (语气词后可能再有标点, 如"开始记日记吧。")
    while True:
        prev = s
        for p in _TAIL_PARTICLES:
            if s.endswith(p):
                s = s[: -len(p)]
                break
        s = s.rstrip(_STRIP_CHARS)
        if s == prev:
            break
    return s


def detect(text: str) -> Intent:
    """识别文本意图。

    优先级 (高 → 低):
    1. 切换短语子串匹配 (任意长度): "开始记日记"/"开始记录"等 → START_DIARY
    2. 长消息 (> MAX_COMMAND_LEN) 默认 DIARY
    3. 短消息走完整词集匹配 (FINALIZE/UNDO/HELP/START_DIARY/CHAT)
    """
    if not text:
        return Intent.DIARY

    # 优先级 1: 任意长度的切换意图子串匹配
    for phrase in _START_DIARY_PHRASES:
        if phrase in text:
            return Intent.START_DIARY

    # 优先级 2: 长消息默认 DIARY
    if len(text) > MAX_COMMAND_LEN:
        return Intent.DIARY

    # 优先级 3: 短消息词集精确匹配
    norm = _normalize(text)
    if norm in _FINALIZE_KEYWORDS:
        return Intent.FINALIZE
    if norm in _UNDO_KEYWORDS:
        return Intent.UNDO
    # 语音转写的撤回指令常带重复/宾语 ("撤回撤回撤回这一段"), 短消息按前缀兜底。
    # 只放行"撤回/撤销"打头: undo 有破坏性, "删掉/删除"打头的短句可能是日记
    # ("删掉了一些旧照片"), 仍只走上面的精确匹配。
    if norm.startswith(("撤回", "撤销")):
        return Intent.UNDO
    if norm in _HELP_KEYWORDS:
        return Intent.HELP
    if norm in _START_DIARY_KEYWORDS:
        return Intent.START_DIARY
    if norm in _CHAT_GREETING_KEYWORDS:
        return Intent.CHAT
    return Intent.DIARY
