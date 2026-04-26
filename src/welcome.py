"""文案常量:欢迎致辞、帮助、仪式感结束语、模式切换文案。"""
from __future__ import annotations

import random

WELCOME_TEXT = """嗨~ 我是你的日记 Agent 📖

我有两种模式:
• 平时陪你随便聊聊 (闲聊模式)
• 你说「开始记日记」就进入记录模式, 之后说什么我都帮你记到今天的笔记里
• 完了发「结束」收尾归档

随时发「帮助」看完整命令。

第一次见面, 你希望我叫你什么名字呢? (一句话告诉我就行, 比如「谷雨」)"""


# 取名后的确认 (用 {name} 占位)
NAME_CONFIRM_TEMPLATE = "好的{name}~ 以后我们一起记日记吧 😊\n想说什么直接发, 或发「开始记日记」开始今天的记录"


# 名字太长时的回退提示
NAME_TOO_LONG_HINT = "名字短一点哦~ 比如「谷雨」、「小明」这样, 再发一次?"


# 名字最大长度
NAME_MAX_LEN = 10


HELP_TEXT = """📖 日记 Agent 使用指南

【两种模式】
• 闲聊模式 (默认): 随便聊, 不写日记
• 记录模式: 你说的话都会写进今天的笔记

【模式切换】
• 进入记录: 发「开始记日记」/「记日记」/「开始」
• 退出记录: 发「结束」(同时归档今天)

【命令 (两种模式都能用)】
• 帮助 → 看到这条
• 撤回 → 删掉刚才记的最后一段 (仅记录模式)

每晚 22:00 / 23:00 我会提醒你写。
跨天会自动回到闲聊模式 (避免新一天的话被记到昨天)。"""


# 仪式感: 进入记录模式
ENTER_DIARY_REPLIES: list[str] = [
    "好的~ 开始记今天的日记 📖 想说什么直接说就行, 完了发「结束」收尾",
    "记录模式开启 ✍️ 接下来你说的都会写进今天的笔记",
    "好嘞, 我洗耳恭听 📖 完了记得说「结束」让我归档",
]


# chat 模式下追加的"成本+引导"提示 (从第 2 条 chat 起追加)
CHAT_COST_REMINDER = "\n\n💡 闲聊会消耗一点 token~ 我主要是帮你记日记的, 想记今天的话发「开始记日记」就开始 📖"


# chat 模式下用户错发命令的提示 (撤回/结束时未在 diary 模式)
NOT_IN_DIARY_HINTS = {
    "undo": "现在是闲聊模式哦, 还没开始记呢, 没东西可撤~ 想记的话发「开始记日记」",
    "finalize": "现在是闲聊模式, 还没开始记呢~ 想记的话发「开始记日记」",
}


# 每次"结束"随机抽一句, 保持仪式感不腻
CLOSING_LINES: list[str] = [
    "今天的故事我收好啦, 晚安 ✨",
    "已经装订成册 📖",
    "归档完毕, 这一页属于今天了。",
    "小册子合上了, 安心睡吧。",
    "好了, 今天的心事都在本子里了。",
    "日记本盖章 📮 愿今晚好梦。",
    "收进时光胶囊, 明年今日再开。",
    "今天的字, 都存好了, 晚安。",
    "咔哒, 打卡完成 ✓ 今天辛苦了。",
    "一天的褶皱, 已经熨平收好。",
]


# 告别句池: random_closing 在仪式感结束语后追加一句, 强化"明天再见"的陪伴感。
CLOSING_FAREWELL_LINES: list[str] = [
    "明天见 👋",
    "明天再聊~",
    "好梦, 明天见 🌙",
    "明天我等你 📖",
    "明天再见呀 ✨",
]


NUDGE_TEXT = "差不多了? 还有吗? 没有就发「结束」, 我帮你收进今天的小册子。"


# Phase 0.B 最小版招呼回复池 (chat 模式下 Intent.CHAT 命中时使用)
# 注: 完整 LLM 闲聊由 chat_handler 处理; 招呼词命中走这个池避免每次招呼都调 LLM
CHAT_GREETING_REPLIES: list[str] = [
    "嗨~ 我在呢 😊 想说点什么?",
    "在的在的, 今天过得怎么样?",
    "嗨~ 来啦? 想到什么直接说就好",
    "我在呢, 慢慢说我都听着",
    "嗨~ 准备好开聊了吗?",
]


# 带名字的仪式感结束语 (供 random_closing 30% 概率随机抽)
CLOSING_LINES_WITH_NAME: list[str] = [
    "辛苦啦{name}~ 今天又记下了一些珍贵的东西 🌙",
    "{name}, 今天的故事我收好啦, 晚安 ✨",
    "{name}, 这一页属于今天, 收好了 📖",
]


def random_closing(name: str | None = None) -> str:
    """随机拼接一句仪式感结束语 + 一句"明天见"告别。

    name 非空时, 30% 概率从 CLOSING_LINES_WITH_NAME 抽 (保留多样性, 避免太腻)。
    """
    if name and random.random() < 0.3:
        head = random.choice(CLOSING_LINES_WITH_NAME).format(name=name)
    else:
        head = random.choice(CLOSING_LINES)
    return head + "\n\n" + random.choice(CLOSING_FAREWELL_LINES)


def random_greeting() -> str:
    """从 CHAT_GREETING_REPLIES 随机抽一句。"""
    return random.choice(CHAT_GREETING_REPLIES)


def random_enter_diary() -> str:
    """从 ENTER_DIARY_REPLIES 随机抽一句。"""
    return random.choice(ENTER_DIARY_REPLIES)
