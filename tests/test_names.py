"""names 模块测试: 取名回答的名字提取规则引擎 (纯规则, 不涉及 LLM)。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import names  # noqa: E402


# === extract: 裸名字 ===

@pytest.mark.parametrize("text,expected", [
    ("谷雨", "谷雨"),
    ("谷雨吧", "谷雨"),
    ("「谷雨」", "谷雨"),
    ("谷雨。", "谷雨"),
    ("Tom", "Tom"),
    ("小哈", "小哈"),  # 语气字结尾的名字不被剥穿
    ("就叫谷雨吧", "谷雨"),
])
def test_bare_name(text, expected):
    assert names.extract(text) == (expected, False)


# === extract: 「叫我X」句式 ===

@pytest.mark.parametrize("text,expected", [
    ("叫我谷雨", "谷雨"),
    ("叫我谷雨就行", "谷雨"),
    ("叫我谷雨就行了。", "谷雨"),
    ("你可以叫我谷雨", "谷雨"),
    ("以后就叫我谷雨吧", "谷雨"),
    ("请叫我谷雨", "谷雨"),
    ("喊我小明", "小明"),
    ("称呼我老谷就好", "老谷"),
    ("叫我小哈", "小哈"),
    ("叫我谷雨, 谢谢", "谷雨"),
    ("别叫我小谷, 叫我谷雨", "谷雨"),  # 否定的不取, 取后面肯定的
])
def test_call_me_patterns(text, expected):
    assert names.extract(text) == (expected, False)


# === extract: 「我叫X」自我介绍 ===

@pytest.mark.parametrize("text,expected", [
    ("我叫谷雨", "谷雨"),
    ("我是谷雨", "谷雨"),
    ("我的名字是谷雨", "谷雨"),
])
def test_self_intro_patterns(text, expected):
    assert names.extract(text) == (expected, False)


# === extract: 拒绝取名 ===

@pytest.mark.parametrize("text", ["跳过", "不用了", "不需要", "随便", "算了吧", "保密"])
def test_refusals(text):
    assert names.extract(text) == (None, True)


# === extract: 提取不出名字 (但不是拒绝) ===

@pytest.mark.parametrize("text", [
    "",
    "帮助",       # 命令词不是名字 (主路由会先拦, 这里是纵深防御)
    "你好",       # 招呼词不是名字
    "好的",       # 应答词不是名字
    "叫我就行",   # 「叫我」后面没有名字
    "我希望你叫我谷雨可是这个名字有点长",  # 候选超长
    "这是一个特别长的完全不像名字的回答哈哈哈哈",
])
def test_no_name_found(text):
    assert names.extract(text) == (None, False)


# === extract_explicit: chat 模式改名, 只认显式句式 ===

@pytest.mark.parametrize("text,expected", [
    ("叫我谷雨", "谷雨"),
    ("以后就叫我谷雨吧", "谷雨"),
    ("你就叫我老谷吧", "老谷"),
    ("改成叫我小明", "小明"),
])
def test_explicit_rename_hits(text, expected):
    assert names.extract_explicit(text) == expected


@pytest.mark.parametrize("text", [
    "同事叫我帮忙了",                    # 前缀不在白名单 → 不触发
    "今天老板叫我加班到很晚真的好累啊",  # 超长 → 不触发
    "别叫我谷雨",                        # 否定 → 不触发
    "你好",
    "谷雨",                              # 裸名字在 chat 模式不算改名指令
    "",
])
def test_explicit_rename_misses(text):
    assert names.extract_explicit(text) is None


# === 对抗审查回归 (2026-08-10): 误改名 / 拒绝变体 / 疑问句 / 复读 ===

@pytest.mark.parametrize("text", [
    "你叫我干嘛", "叫我干嘛", "你喊我干什么", "你叫我什么名字",
    "叫我起床", "请叫我起床", "你叫我谷雨干嘛", "就叫我说两句",
    "喊我吃饭的时候我在睡觉", "叫我起床的是闹钟",
])
def test_explicit_rename_rejects_casual_sentences(text):
    """闲聊自然句不得触发改名 (审查 critical: 用户名字被莫名覆盖)。"""
    assert names.extract_explicit(text) is None, f"{text!r} 不应触发改名"


@pytest.mark.parametrize("text", [
    "不用了谢谢", "算了算了", "不用不用", "随便随便", "不要了",
    "不用取名了", "不想取名", "免了", "不了", "不用了,谢谢", "不用了，谢谢",
    "叫我什么都行", "随便叫我什么都可以",
])
def test_refusal_variants_recognized(text):
    """拒绝取名的各种变体必须识别为拒绝, 不能变成名字 (审查 critical)。"""
    assert names.extract(text) == (None, True), f"{text!r} 应识别为拒绝"


@pytest.mark.parametrize("text", [
    "你叫什么名字", "你是谁", "叫我干嘛",
    "这个嘛让我想想我也不知道该让你怎么称呼我比较好",
])
def test_questions_not_taken_as_name(text):
    """反问/疑问句不能变成名字。"""
    name, refused = names.extract(text)
    assert name is None, f"{text!r} 提取出了 {name!r}"


@pytest.mark.parametrize("text,expected", [
    ("能叫我小雨吗", "小雨"),      # 疑问助词「吗」剥掉
    ("你可以叫我小雨吗", "小雨"),
    ("叫我小雨么", "小雨"),
    ("就叫谷雨吧就叫谷雨吧", "谷雨"),  # 语音转写复读折叠
    ("嗯就叫谷雨吧嗯", "谷雨"),        # 头尾语气词
    ("谷雨谷雨", "谷雨"),
])
def test_voice_transcription_noise(text, expected):
    assert names.extract(text) == (expected, False)


def test_reduplicated_nickname_preserved():
    """叠字昵称 (婷婷/多多) 是真名字, 复读折叠不能碰。"""
    assert names.extract("婷婷") == ("婷婷", False)
    assert names.extract("叫我多多") == ("多多", False)


def test_inline_name_with_command():
    """「叫我小明, 开始记日记」→ extract 拿到小明 (路由层负责命令)。"""
    assert names.extract("叫我小明, 开始记日记") == ("小明", False)
    assert names.extract_explicit("叫我小明, 开始记日记") == "小明"
