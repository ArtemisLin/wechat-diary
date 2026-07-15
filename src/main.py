"""wechat-diary 启动入口。

职责:
- 加载 iLink state(未登录则提示先跑 `python ilink.py login`)
- 启动 APScheduler 后台线程(22:00/23:00 提醒)
- 主线程跑 iLink 长轮询,消息路由到:
    - 首次用户先发欢迎致辞
    - 意图识别:结束/撤回/帮助 → 对应处理
    - 日记:写入 + 每 4 段追加劝收尾
"""
from __future__ import annotations

import atexit
import sys
import time

import chat_handler
import config  # noqa: 入口脚本初始化编码/env
import diary_writer
import ilink
import paths
import session_state
import user_profile
import welcome
from intents import Intent, detect


NUDGE_EVERY = 4  # 每 4 段追加一次劝收尾

OFFLINE_NOTICE_GAP_H = 12  # 离线超过该小时数, 首条回复附一次性提示
_offline_notice: str | None = None


def _compute_offline_notice(state: dict) -> str | None:
    """离线间隔提示。上次存活时间缺失或间隔小于阈值时返回 None。"""
    ts = state.get("last_alive_ts")
    if not ts:
        return None
    gap_h = (time.time() - ts) / 3600
    if gap_h < OFFLINE_NOTICE_GAP_H:
        return None
    return (
        f"(小提示: 我离线了大约 {int(gap_h)} 小时, 期间你发的消息我可能没收到, "
        "翻一下聊天记录, 漏了的可以再发我一次)"
    )


def _handle(user_id: str, text: str, is_voice: bool) -> str | None:
    """主业务路由, 双模式 (chat / diary) 感知。"""
    if user_id != config.USER_ID:
        return "嗯? 这个日记本不是给你的呢"

    # 跨天自动 reset; 拿到当前模式
    session = session_state.load_or_reset(user_id)
    intent = detect(text)

    # 全模式都生效的命令
    if intent is Intent.HELP:
        return welcome.HELP_TEXT

    # === DIARY 模式 ===
    if session.mode == "diary":
        if intent is Intent.UNDO:
            ok = diary_writer.undo_last_block(user_id)
            return "好的, 帮你撤回啦" if ok else "今天还什么都没说呢, 没东西可撤哦"
        if intent is Intent.FINALIZE:
            ok = diary_writer.finalize_today(user_id)
            if not ok:
                return "今天还没说话呢, 要不先说两句吧?"
            session_state.exit_diary(user_id)
            chat_handler.reset_history(user_id)
            name = user_profile.get_name(user_id, fallback="")
            return welcome.random_closing(name=name or None)
        # diary 模式下其他所有意图都当日记记 (包括 CHAT/START_DIARY/默认 DIARY)
        # 注: 用户在 diary 中再说"开始记日记", 就当成日记内容写进去, 不重复进入
        reply, n = diary_writer.write(user_id, text, is_voice)
        if n > 0 and n % NUDGE_EVERY == 0:
            reply = f"{reply}\n\n{welcome.NUDGE_TEXT}"
        return reply

    # === CHAT 模式 ===
    if intent is Intent.START_DIARY:
        session_state.enter_diary(user_id)
        chat_handler.reset_history(user_id)
        return welcome.random_enter_diary()

    if intent is Intent.UNDO:
        return welcome.NOT_IN_DIARY_HINTS["undo"]
    if intent is Intent.FINALIZE:
        return welcome.NOT_IN_DIARY_HINTS["finalize"]

    if intent is Intent.CHAT:
        # 招呼词走静态回复池 (省 LLM 开销)
        reply = welcome.random_greeting()
    else:
        # 其他普通消息 (Intent.DIARY in chat mode = 不在记录中的普通对话) 走 LLM 闲聊
        reply = chat_handler.chat(user_id, text)

    new_count = session_state.increment_chat_count(user_id)
    if new_count >= 2 and config.AI_API_KEY:
        reply = reply + welcome.CHAT_COST_REMINDER
    return reply


def _dispatch(user_id: str, text: str, is_voice: bool) -> str | None:
    """处理首次见面欢迎 + 取名流程, 之后才走主路由。"""
    if user_id != config.USER_ID:
        return _handle(user_id, text, is_voice)

    profile = user_profile.load(user_id)

    # 首次见面 (unknown): 发欢迎致辞 + 问名字, 不处理本次消息
    if profile.state == "unknown":
        user_profile.mark_welcomed(user_id)
        return welcome.WELCOME_TEXT

    # 等待取名 (awaiting_name): 把本次消息当名字处理
    if profile.state == "awaiting_name":
        candidate = text.strip()
        if not candidate or len(candidate) > welcome.NAME_MAX_LEN:
            return welcome.NAME_TOO_LONG_HINT
        user_profile.set_name(user_id, candidate)
        return welcome.NAME_CONFIRM_TEMPLATE.format(name=candidate)

    # 正常状态 (active): 走主路由
    return _handle(user_id, text, is_voice)


def _on_message(user_id: str, text: str, is_voice: bool) -> str | None:
    """iLink 回调入口: 主路由 + 离线提示一次性附注。"""
    global _offline_notice
    reply = _dispatch(user_id, text, is_voice)
    if reply and _offline_notice and user_id == config.USER_ID:
        reply = f"{reply}\n\n{_offline_notice}"
        _offline_notice = None
    return reply


def _make_send_fn(state: dict):
    def send(user_id: str, text: str) -> bool:
        return ilink.send_to_user(state, user_id, text)
    return send


def main() -> int:
    global _offline_notice
    paths.migrate_legacy()
    user_profile.migrate_legacy()
    state = ilink.load_state()
    _offline_notice = _compute_offline_notice(state)
    if _offline_notice:
        print(f"  ⚠️  {_offline_notice}")
    if not state.get("bot_token"):
        print("  未登录。先运行: python ilink.py login")
        return 1

    if not config.USER_ID:
        print("  .env 未配置 USER_ID,请填 ilink 登录时返回的 ilink_user_id")
        return 1
    if not config.DIARY_DIR:
        print("  .env 未配置 DIARY_DIR")
        return 1
    if not config.AI_API_KEY:
        print("  ℹ️  零 key 模式: 未配 AI_API_KEY, 原文直存 (润色/闲聊为可选增强)")

    try:
        from scheduler import create_scheduler
    except ModuleNotFoundError as e:
        if e.name and e.name.startswith("apscheduler"):
            print("  缺少依赖 apscheduler。先运行: python -m pip install apscheduler tzdata")
            return 1
        raise

    sched = create_scheduler(_make_send_fn(state))
    sched.start()
    atexit.register(lambda: sched.shutdown(wait=False))

    print("\n=== wechat-diary 已启动 ===")
    print(f"  时区: {config.TIMEZONE}")
    print(f"  提醒: {config.REMIND_HOUR_1}:00 / {config.REMIND_HOUR_2}:00")
    print(f"  diary: {config.DIARY_DIR}")
    print(f"  AI 润色: {'开启' if config.AI_API_KEY else '关闭 (零 key 模式)'}")
    print(f"  user: {config.USER_ID[:20]}...")
    _profile = user_profile.load(config.USER_ID)
    _state_label = {
        "unknown": "首次见面 (会发欢迎致辞 + 问名字)",
        "awaiting_name": "已欢迎, 等待用户告知名字",
        "active": f"已激活 (name={_profile.name})",
    }.get(_profile.state, _profile.state)
    print(f"  状态: {_state_label}")
    print()

    loop_result = ilink.run_loop(state, on_message=_on_message)
    if loop_result == "session_expired":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
