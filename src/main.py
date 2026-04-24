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

import config  # noqa: 入口脚本初始化编码/env
import diary_writer
import ilink
import welcome
import welcome_store
from intents import Intent, detect


NUDGE_EVERY = 4  # 每 4 段追加一次劝收尾


def _handle(user_id: str, text: str, is_voice: bool) -> str | None:
    """主业务路由。返回给用户的回复(多段用 \\n\\n 间隔)或 None。"""
    if user_id != config.USER_ID:
        return "这个日记本是别人的,抱歉~"

    intent = detect(text)

    if intent is Intent.HELP:
        return welcome.HELP_TEXT

    if intent is Intent.UNDO:
        ok = diary_writer.undo_last_block(user_id)
        return "已删掉最后一段 🗑️" if ok else "今天还没记东西,没啥可撤的 🤔"

    if intent is Intent.FINALIZE:
        ok = diary_writer.finalize_today(user_id)
        if not ok:
            return "今天还没写东西呢,说一句吧?"
        return welcome.random_closing()

    # Intent.DIARY
    reply, n = diary_writer.write(user_id, text, is_voice)
    if n > 0 and n % NUDGE_EVERY == 0:
        reply = f"{reply}\n\n{welcome.NUDGE_TEXT}"
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
    state = ilink.load_state()
    if not state.get("bot_token"):
        print("  未登录。先运行: python ilink.py login")
        return 1

    if not config.USER_ID:
        print("  .env 未配置 USER_ID,请填 ilink 登录时返回的 ilink_user_id")
        return 1
    if not config.VAULT_DIR:
        print("  .env 未配置 VAULT_DIR")
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
    print(f"  vault: {config.VAULT_DIR}")
    print(f"  user: {config.USER_ID[:20]}...")
    print(f"  已欢迎: {'是' if welcome_store.is_welcomed(config.USER_ID) else '否(首次消息时前置欢迎)'}")
    print()

    loop_result = ilink.run_loop(state, on_message=_on_message)
    if loop_result == "session_expired":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
