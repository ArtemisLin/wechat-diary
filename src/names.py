"""名字提取规则引擎: 从"你希望我叫你什么"的回答里提取称呼。

设计与 intents.py 同一哲学: 规则优先、零延迟、可解释。
- extract(text): 取名流程用, 覆盖「叫我X就行」「我叫X」「X」等常见句式,
  并识别"不想要称呼"类回答 (前缀/关键词匹配, 覆盖「不用了谢谢」等变体)。
- extract_explicit(text): chat 模式改名用, 只认「叫我X」类显式句式 +
  白名单前缀 + 更严的候选过滤, 避免「叫我起床」「你叫我干嘛」误触发改名。
- llm_extract(text): 配了 AI key 时的兜底 (规则失手的长句), 失败返回 None。
  (这是第三个 LLM 调用点, 复用 diary_writer 基础设施; 后续应抽 src/llm.py)
"""
from __future__ import annotations

import re

import intents
import welcome

# 「叫我X」类标记; 取最后一次出现, 支持"别叫我小谷, 叫我谷雨"
_CALL_ME_MARKERS = ("叫我", "喊我", "称呼我", "称我")

# 标记前紧邻窗口出现这些字样 → 否定/疑问语境 ("别叫我X"/"怎么称呼我"), 该处不取
_MARKER_GUARDS = ("别", "不", "没", "勿", "怎么", "咋", "如何", "怎样")

# 「我叫X」类自我介绍
_SELF_INTRO_RE = re.compile(r"^我(?:的名字|的名)?(?:是|叫做|叫)\s*(?P<name>.+)$")

# 候选名截断: 取到第一个分句标点为止 ("叫我谷雨, 谢谢" → "谷雨")
_CLAUSE_SPLIT_RE = re.compile(r"[。．.！!？?,，;；、\n]")

# 尾部客套短语 (反复剥离, 长的在前)
_TAIL_PHRASES = (
    "就可以了", "就行了", "就好了", "就可以", "就行", "就好", "就成", "好了",
    "怎么样", "可以吗", "行不行", "好不好", "都可以", "行吗", "好吗", "都行", "如何",
)
# 尾部语气词 (反复剥离; 剥后必须还有内容, 保护"小哈"这类以语气字结尾的名字)
_TAIL_PARTICLES = ("吧", "呗", "啦", "哟", "哦", "呀", "嘛", "呢", "咯", "喽", "吗", "么", "嗯")
# 头部引导短语 (反复剥离, 长的在前; 处理"嗯就叫谷雨吧"这类裸回答)
_LEAD_PHRASES = ("那就叫", "就叫我", "就叫", "那就", "就", "那", "嗯", "呃", "唔")
_STRIP_PUNCT = " \t\n　。．.！!？?~～,，、;；:：'\"“”‘’「」『』《》〈〉()（）[]【】<>"

# 明确表示不要称呼: 整句精确匹配 (normalize 后)
_REFUSALS = {
    "不用", "不用了", "不需要", "不必", "随便", "随意", "都行", "都可以",
    "无所谓", "算了", "跳过", "不想说", "保密", "没有", "不告诉你",
    "你随便", "随便你", "你定", "你看着办", "不取了", "不用取",
}
# 拒绝前缀: 首个分句以此开头即视为拒绝 (覆盖「不用了谢谢」「算了算了」等变体)
_REFUSAL_PREFIXES = (
    "不用", "不要", "不需要", "不必", "不想", "不取", "不了", "免了", "算了",
    "随便", "随意", "无所谓", "都行", "都可以", "跳过", "保密", "没有名字",
    "不告诉", "你随便", "你定", "你看着办",
)
# 拒绝关键词: 「叫我X」路径没提出有效名字时, 句中含这些词也视为拒绝
# (「叫我什么都行」「随便叫我什么都可以」)
_REFUSAL_HINTS = ("什么都行", "什么都可以", "无所谓", "随便")

# 疑问词: 名字里不可能出现, 含之即拒收候选 (「什么都行」「你是谁」「你叫什么名字」)
_INTERROGATIVES = ("什么", "啥", "谁", "怎么", "为什么", "哪", "如何", "几点")
# 「叫我X干嘛」类反问后缀: 候选以此结尾说明是在质问, 不是取名
_QUESTION_SUFFIXES = ("干嘛", "干什么", "干啥", "做什么", "做甚")

# 应答词/常见"叫我+动作"类请求, 不是名字
_NON_NAMES = {
    "好", "好的", "好呀", "好啊", "行", "可以", "嗯", "嗯嗯", "哦", "噢", "喔",
    "是", "对", "什么", "啥", "为什么", "怎么", "怎么办", "谢谢", "多谢",
    "干", "干嘛", "干什么", "干啥", "名字", "什么名字", "比较好",
    "起床", "吃饭", "睡觉", "上班", "下班", "开会", "加班", "帮忙",
    "说两句", "说话", "想想", "看看", "加油",
}

# chat 模式改名: 标记前只允许这些前缀, 其他一律不触发 (防误改)
_RENAME_PREFIXES = {
    "", "请", "就", "你", "您", "你就", "您就", "那就", "以后", "以后就",
    "以后请", "以后你就", "改成", "改口", "还是", "重新",
}
# chat 模式改名: 候选含这些功能字 → 是句子不是名字 (「吃饭的时候我在睡觉」)
_RENAME_REJECT_CHARS = "的了是在去到给帮"
# chat 模式改名的消息长度上限 (与 intents.MAX_COMMAND_LEN 同哲学)
RENAME_MAX_LEN = 15


def _clean(s: str) -> str:
    """剥掉首尾标点/引号 + 头部引导短语 + 尾部客套短语/语气词。"""
    prev = None
    while s and s != prev:
        prev = s
        s = s.strip(_STRIP_PUNCT)
        for ph in _TAIL_PHRASES:
            if s.endswith(ph) and len(s) > len(ph):
                s = s[: -len(ph)]
                break
        for ph in _LEAD_PHRASES:
            if s.startswith(ph) and len(s) > len(ph):
                s = s[len(ph):]
                break
        for p in _TAIL_PARTICLES:
            if s.endswith(p) and len(s) > len(p):
                s = s[: -len(p)]
                break
    return s.strip(_STRIP_PUNCT)


def _dedup_repetition(s: str) -> str:
    """语音转写整句复读折叠: "就叫谷雨吧就叫谷雨吧" → "就叫谷雨吧"。

    只折叠重复单元 ≥2 字的情形 — "婷婷/多多"这类叠字昵称是真名字, 不动。
    """
    n = len(s)
    for size in range(2, n // 2 + 1):
        if n % size == 0 and s == s[:size] * (n // size):
            return s[:size]
    return s


def _validate(candidate: str) -> str | None:
    """清洗候选名并校验: 长度 1..NAME_MAX_LEN, 不含疑问词, 不是命令/应答词。"""
    raw = candidate.strip()
    first_clause = _CLAUSE_SPLIT_RE.split(raw, 1)[0].strip(_STRIP_PUNCT)
    if not first_clause:
        return None
    # 反问/疑问语义在剥语气词之前判 (「什么都行」剥掉「么」会变「什」逃过检查)
    if first_clause.endswith(_QUESTION_SUFFIXES):
        return None
    if any(q in first_clause for q in _INTERROGATIVES):
        return None
    s = _clean(first_clause)
    if not s or len(s) > welcome.NAME_MAX_LEN:
        return None
    if s in _NON_NAMES or s in _REFUSALS:
        return None
    # 命令词/招呼词 (帮助/结束/开始/你好...) 不能当名字
    if intents.detect(s) is not intents.Intent.DIARY:
        return None
    return s


def _marker_hits(text: str) -> list:
    """所有「叫我」类标记出现的位置, 按位置倒序 (后说的优先)。"""
    hits = []
    for marker in _CALL_ME_MARKERS:
        start = 0
        while True:
            i = text.find(marker, start)
            if i < 0:
                break
            hits.append((i, marker))
            start = i + 1
    hits.sort(reverse=True)
    return hits


def _is_guarded(text: str, idx: int) -> bool:
    """标记前紧邻窗口是否为否定/疑问语境。"""
    window = text[max(0, idx - 2): idx]
    return any(g in window for g in _MARKER_GUARDS)


def _is_refusal(text: str) -> bool:
    """整句/首分句级拒绝识别 (含「不用了谢谢」「算了算了」等变体)。"""
    cleaned = _clean(text)
    if not cleaned:
        return False
    if cleaned in _REFUSALS or intents._normalize(cleaned) in _REFUSALS:
        return True
    first_clause = _clean(_CLAUSE_SPLIT_RE.split(text.strip(), 1)[0])
    for prefix in _REFUSAL_PREFIXES:
        if cleaned.startswith(prefix) or first_clause.startswith(prefix):
            return True
    return False


def extract(text: str) -> tuple:
    """从取名回答中提取名字。返回 (name, refused)。

    refused=True 表示用户明确不想要称呼; 两者都空表示没看出名字。
    优先级: 「叫我X」显式句式 > 拒绝识别 > 「我叫X」自我介绍 > 裸名字兜底
    (显式取名在前, 保证「随便叫我小谷吧」是取名而不是拒绝)。
    """
    s = (text or "").strip()
    if not s:
        return None, False

    hits = _marker_hits(s)
    for idx, marker in hits:
        if _is_guarded(s, idx):
            continue
        name = _validate(s[idx + len(marker):])
        if name:
            return name, False

    if _is_refusal(s):
        return None, True
    if hits and any(h in s for h in _REFUSAL_HINTS):
        # 「叫我什么都行」: 有标记但没名字, 且句中是"随便"语义 → 拒绝
        return None, True
    if hits:
        # 有「叫我」标记但没提出有效名字: 不做裸兜底, 避免整句当名字
        return None, False

    m = _SELF_INTRO_RE.match(s)
    if m:
        return _validate(m.group("name")), False

    # 裸名字兜底: 短回答直接当名字 ("谷雨" / "谷雨吧" / 「谷雨」);
    # 复读折叠必须在剥引导词之前 ("就叫谷雨吧就叫谷雨吧" 剥完就不对称了)
    return _validate(_dedup_repetition(s.strip(_STRIP_PUNCT))), False


def extract_explicit(text: str) -> str | None:
    """chat 模式改名: 只认显式「叫我X」+ 白名单前缀 + 严过滤的短句。

    比取名流程的 extract 严得多: 闲聊里误改名的代价 (用户名字被莫名覆盖)
    远大于漏识别 (用户换个说法再发一次就行)。
    """
    s = (text or "").strip().strip(_STRIP_PUNCT)
    if not s or len(s) > RENAME_MAX_LEN:
        return None
    for idx, marker in _marker_hits(s):
        if _is_guarded(s, idx):
            continue
        if s[:idx] not in _RENAME_PREFIXES:
            continue
        name = _validate(s[idx + len(marker):])
        if not name:
            continue
        if any(c in name for c in _RENAME_REJECT_CHARS):
            continue  # 含功能字 → 是句子不是名字
        return name
    return None


NAME_EXTRACT_PROMPT = """用户被问「你希望我叫你什么名字」, 用户回答:
{reply}

从回答中提取用户希望被称呼的名字, 只输出名字本身 (不超过 10 个字), 不要任何解释。
如果回答里没有名字、或用户表示不想要称呼, 只输出一个字: 无"""


def llm_extract(text: str) -> str | None:
    """LLM 兜底提取 (仅在配了 AI key 且规则失手时调用)。失败返回 None。"""
    import diary_writer  # 延迟导入, 避免模块加载期做代理探测

    try:
        out = diary_writer._call_llm(
            NAME_EXTRACT_PROMPT.format(reply=text.strip()), timeout=10
        )
    except diary_writer.LLMError:
        return None
    out = (out or "").strip()
    if not out or out in ("无", "None"):
        return None
    return _validate(out)
