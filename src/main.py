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

import chat_handler
import config  # noqa: 入口脚本初始化编码/env
import diary_writer
import ilink
import paths
import session_state
import welcome
import welcome_store
from intents import Intent, detect


NUDGE_EVERY = 4  # 每 4 段追加一次劝收尾


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
            return welcome.random_closing()
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
    if new_count >= 2:
        reply = reply + welcome.CHAT_COST_REMINDER
    return reply


def _on_message(user_id: str, text: str, is_voice: bool) -> str | None:
    """iLink 回调。首次用户前置欢迎。"""
    if user_id == config.USER_ID and not welcome_store.is_welcomed(user_id):
        welcome_store.mark_welcomed(user_id)
        main_reply = _handle(user_id, text, is_voice)
        # 欢迎 + 主业务回复拼一起,用户一次收到
        if main_reply:
            return f"{welcome.WELCOME_TEXT}\n\n———\n\n{main_reply}"
        return welcome.WELCOME_TEXT
    return _handle(user_id, text, is_voice)


def _make_send_fn(state: dict):
    def send(user_id: str, text: str) -> bool:
        return ilink.send_to_user(state, user_id, text)
    return send


def main() -> int:
    paths.migrate_legacy()
    state = ilink.load_state()
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
        print("  ⚠️  AI_API_KEY 未配置,LLM 润色失效,会回落到原文写入")

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
    print(f"  user: {config.USER_ID[:20]}...")
    print(f"  已欢迎: {'是' if welcome_store.is_welcomed(config.USER_ID) else '否(首次消息时前置欢迎)'}")
    print()

    loop_result = ilink.run_loop(state, on_message=_on_message)
    if loop_result == "session_expired":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
