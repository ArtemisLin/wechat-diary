"""文案常量: 欢迎致辞、帮助、收尾语、回执。

v0.3 单模式全面改写(与 020 插件版 0.3.0 同步, 2026-08-16 谷雨逐条审定):
发什么记什么, 不再有 chat/diary 双模式; 「在吗」探活不落库; 「结束」是可选仪式。
"""
from __future__ import annotations

import random

import config

WELCOME_SNIPPET = "随手记 Agent"


def welcome_text(diary_dir: str) -> str:
    """欢迎语按用户的日记目录动态生成: 入门用户得知道东西记去哪了、在哪改。"""
    return f"""嗨~ 我是你的随手记 Agent ✍️

想记什么直接发给我, 文字、语音都行, 我会记到你今天的笔记里。
记的东西在这台电脑的「{diary_dir}」目录; 想换地方: 改 .env 里的 DIARY_DIR (或在网页面板里选)。
说错了发「撤回」, 随时发「帮助」看全部用法。

第一次见面, 你希望我叫你什么名字呢? (不想要称呼就发「跳过」)"""


# 取名后的确认 (用 {name} 占位)
NAME_CONFIRM_TEMPLATE = "好的{name}~ 想记什么直接发我就行 ✍️"

# 没从回答里看出名字时的回退提示
NAME_UNCLEAR_HINT = "没太看出来名字呢~ 名字短一点直接发就行, 再发一次? 不想要称呼就发「跳过」"

# 取名流程中用户发了帮助/招呼等命令时, 追加的"还欠一个名字"提醒
STILL_AWAITING_NAME_HINT = "(对了, 还没告诉我怎么称呼你呢~ 直接发名字就行; 不想要就发「跳过」)"

# 用户明确不想要称呼
NAME_SKIPPED_REPLY = "好的~ 那就不特别称呼啦 😊 想记什么直接发就行; 以后想让我称呼你, 随时发「叫我XX」"

# 取名流程中用户直接发内容/命令: 放行, 追加这句
NAME_LATER_HINT = "(称呼不急~ 想要的话随时发「叫我XX」)"

# 「叫我小明, ...」同句取名成功时, 追加在回复后
NAME_INLINE_CONFIRM_TEMPLATE = "(称呼记下啦, {name}~)"

# 「叫我XX」改名/补名成功的确认
RENAME_CONFIRM_TEMPLATE = "好嘞{name}~ 以后就这么叫你啦 😊"

# 名字最大长度
NAME_MAX_LEN = 10


HELP_TEXT = f"""✍️ 微信随手记 使用指南

想记什么直接发, 文字、语音都行, 自动记到今天的笔记里。
不用任何开场白, 发出去就记下了。

【命令】
• 撤回 → 删掉刚记的最后一条
• 结束 → 给今天写个收尾标记 (不发也没关系, 跨天会自动收尾)
• 在吗 → 看我在不在、今天记了几段
• 叫我XX → 设置/修改你的称呼
• 帮助 → 看到这条

熬夜不怕跨天: 凌晨 {config.DAY_START_HOUR} 点前记的都算前一天。
每晚 {config.REMIND_HOUR_1}:00 / {config.REMIND_HOUR_2}:00 我会提醒你写。"""


# 老用户习惯发「开始记日记」: 友好告知不用了, 不落库
START_DIARY_OBSOLETE_REPLY = "现在不用特意开始啦~ 想记什么直接发就行 ✍️"
START_DIARY_SUSPECT_NOTE = "(顺便说, 现在不用发「开始记日记」了, 直接说就记)"


def ping_reply(n: int) -> str:
    """探活回执(在吗/hello/测试…): 回状态, 不落库。
    「在吗」是用户自己发明的 ping——有回复=在线; 尊重它, 别把它记进笔记。"""
    if n > 0:
        return f"在的~ 今天已记 {n} 段 ✍️ 想记什么直接发"
    return "在的~ 想记什么直接发, 我都记着 ✍️"


# 每天第一条的回执前缀: 零动作给足"它在且在记"的信任信号; 完整命令提示每天只在这出现一次
FIRST_OF_DAY_PREFIX = "今天第一条, 已开新的一页 📖\n"
FIRST_OF_DAY_TIPS = "\n(说错了发「撤回」, 随时发「帮助」看全部用法)"

UNDO_EMPTY_REPLY = "今天还什么都没说呢, 没东西可撤哦"
FINALIZE_EMPTY_REPLY = "今天还没记东西呢~ 想记什么直接发"
# 跨天后的第一条: 昨天已自动封存的告知(会替掉 FIRST_OF_DAY_PREFIX, 两句语义重复)
GRACE_EXPIRED_NOTICE = "(昨天的已自动收尾, 翻开新的一页 📖)"

# 图片: 019 暂不支持(020 插件版支持), 但绝不能静默——用户得知道这条没记上
IMAGE_UNSUPPORTED_REPLY = "⚠️ 图片这条没记上——电脑版暂时只收文字和语音, 图片请用 Obsidian 插件版 📷"


def undo_ok_reply(removed: str | None) -> str:
    """撤回回执带被撤内容预览: 用户要能确认撤对了。纯字符串, 不需要 AI。"""
    if not removed:
        return "好的, 帮你撤回啦"
    if removed.startswith("![["):
        return "好的, 撤掉了刚才那张图片"
    t = removed.removeprefix("🎤 ").replace("\n", " ").strip()
    preview = t[:12] + ("…" if len(t) > 12 else "")
    return f"好的, 撤掉了「{preview}」"


# 收尾语分时段(2026-08-16 谷雨审定): 备忘录用户中午也会「结束」, 白天说"晚安"违和。
# 20 点后到逻辑日边界前用晚安池, 其余用中性池。
CLOSING_LINES_DAY: list[str] = [
    "已经装订成册 📖",
    "归档完毕, 这一页属于今天了。",
    "收进时光胶囊, 下次见。",
    "咔哒, 打卡完成 ✓ 今天辛苦了。",
]
CLOSING_LINES_NIGHT: list[str] = [
    "今天的故事我收好啦, 晚安 ✨",
    "小册子合上了, 安心睡吧。",
    "好了, 今天的心事都在本子里了。",
    "笔记本盖章 📮 愿今晚好梦。",
    "今天的字, 都存好了, 晚安。",
]
CLOSING_FAREWELL_DAY: list[str] = ["下次见 👋", "明天见 👋", "明天再见呀 ✨"]
CLOSING_FAREWELL_NIGHT: list[str] = ["好梦, 明天见 🌙", "明天我等你 📖", "明天见 👋"]
CLOSING_WITH_NAME_DAY: list[str] = ["{name}, 这一页属于今天, 收好了 📖"]
CLOSING_WITH_NAME_NIGHT: list[str] = [
    "辛苦啦{name}~ 今天又记下了一些珍贵的东西 🌙",
    "{name}, 今天的故事我收好啦, 晚安 ✨",
]

# 兼容旧引用(测试/外部): 全池
CLOSING_LINES: list[str] = CLOSING_LINES_DAY + CLOSING_LINES_NIGHT
CLOSING_FAREWELL_LINES: list[str] = list(dict.fromkeys(CLOSING_FAREWELL_DAY + CLOSING_FAREWELL_NIGHT))
CLOSING_LINES_WITH_NAME: list[str] = CLOSING_WITH_NAME_DAY + CLOSING_WITH_NAME_NIGHT


def random_closing(name: str | None = None) -> str:
    """按时段抽一句收尾语 + 一句道别。name 非空时 30% 概率用带名字版。"""
    night = config.is_night_now()
    name_pool = CLOSING_WITH_NAME_NIGHT if night else CLOSING_WITH_NAME_DAY
    line_pool = CLOSING_LINES_NIGHT if night else CLOSING_LINES_DAY
    bye_pool = CLOSING_FAREWELL_NIGHT if night else CLOSING_FAREWELL_DAY
    if name and random.random() < 0.3:
        head = random.choice(name_pool).format(name=name)
    else:
        head = random.choice(line_pool)
    return head + "\n\n" + random.choice(bye_pool)
