"""wechat-diary 启动入口。

职责:
- 加载 iLink state(未登录则提示先跑 `python ilink.py login`)
- 启动 APScheduler 后台线程(22:00/23:00 提醒)
- 主线程跑 iLink 长轮询,消息路由到:
    - 首次用户先发欢迎致辞
    - 意图识别: 结束/撤回/帮助/在吗 → 对应处理
    - 其余一律写入 (v0.3 单模式: 发什么记什么, 无 chat/diary 双态)
"""
from __future__ import annotations

import atexit
import sys
import time

import config  # noqa: 入口脚本初始化编码/env
import diary_writer
import ilink
import names
import paths
import session_state
import user_profile
import welcome
from intents import Intent, detect, detect_ex


OFFLINE_NOTICE_GAP_H = 24  # 缓冲窗口 24h 内实测可补收(2026-08-16), 之内不吓唬用户
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
        f"(小提示: 我离线超过一天了(约 {int(gap_h)} 小时), 太早的消息可能没补到, "
        "翻一下聊天记录, 漏了的可以再发我一次)"
    )


def _rollover(user_id: str) -> str | None:
    """逻辑日翻页处理: 翻页则自动封存旧的一天, 真封了才返回告知文案。"""
    old_date = session_state.rollover(user_id)
    if not old_date:
        return None
    sealed = diary_writer.finalize_today(user_id, old_date)
    return welcome.GRACE_EXPIRED_NOTICE if sealed else None


def _write_entry(user_id: str, text: str, is_voice: bool) -> str:
    reply, _n = diary_writer.write(user_id, text, is_voice)
    return reply


def _handle(user_id: str, text: str, is_voice: bool) -> str | None:
    """主业务路由 (v0.3 单模式: 命令之外一切皆记)。"""
    if user_id != config.USER_ID:
        return "嗯? 这个日记本不是给你的呢"

    intent, suspect = detect_ex(text)

    if intent is Intent.HELP:
        return welcome.HELP_TEXT

    # 探活(在吗/hello/测试…): 回状态, 不落库。用户在 ping"它还在吗"——尊重这个机制,
    # 别把它记进笔记。bot 不在线时本来就没人回, 有回复即是答案。
    if intent is Intent.CHAT:
        return welcome.ping_reply(diary_writer.count_day(user_id))

    if intent is Intent.UNDO:
        ok, removed = diary_writer.undo_last_block(user_id)
        return welcome.undo_ok_reply(removed) if ok else welcome.UNDO_EMPTY_REPLY

    if intent is Intent.FINALIZE:
        # 封存降级为可选仪式: 写收尾标记, 不再切换任何模式; 之后继续发照样记
        ok = diary_writer.finalize_today(user_id)
        if not ok:
            return welcome.FINALIZE_EMPTY_REPLY
        name = user_profile.get_name(user_id, fallback="")
        return welcome.random_closing(name=name or None)

    if intent is Intent.START_DIARY:
        # 老习惯兼容: 短句只告知"不用了"; 长句(suspect)里是内容, 整句照记不能丢
        if suspect:
            return f"{_write_entry(user_id, text, is_voice)}\n\n{welcome.START_DIARY_SUSPECT_NOTE}"
        reply = welcome.START_DIARY_OBSOLETE_REPLY
        inline_name = names.extract_explicit(text)  # 「叫我小明, 开始记日记」: 称呼别丢
        if inline_name:
            user_profile.set_name(user_id, inline_name)
            reply = f"{reply}\n\n{welcome.NAME_INLINE_CONFIRM_TEMPLATE.format(name=inline_name)}"
        return reply

    # 显式「叫我XX」→ 设置/修改称呼(短句命令, 不落库)
    new_name = names.extract_explicit(text)
    if new_name:
        user_profile.set_name(user_id, new_name)
        return welcome.RENAME_CONFIRM_TEMPLATE.format(name=new_name)

    return _write_entry(user_id, text, is_voice)


def _dispatch(user_id: str, text: str, is_voice: bool) -> str | None:
    """处理跨天 + 首次见面欢迎 + 取名流程, 之后才走主路由。"""
    if user_id != config.USER_ID:
        return _handle(user_id, text, is_voice)

    expired_notice = _rollover(user_id)
    profile = user_profile.load(user_id)

    # 首次见面 (unknown): 内容优先——第一句就是内容的先记下, 再自我介绍
    if profile.state == "unknown":
        user_profile.mark_welcomed(user_id)
        if detect(text) is Intent.DIARY:
            write_reply = _handle(user_id, text, is_voice)
            reply = f"{write_reply}\n\n{welcome.welcome_text(config.DIARY_DIR)}" if write_reply else welcome.welcome_text(config.DIARY_DIR)
        else:
            reply = welcome.welcome_text(config.DIARY_DIR)  # 第一句是探活/命令: 欢迎语本身就是回答
    elif profile.state == "awaiting_name":
        reply = _dispatch_awaiting_name(user_id, text, is_voice)
    else:
        reply = _handle(user_id, text, is_voice)

    if reply and expired_notice:
        # 跨天告知与「今天第一条」语义重复, 只留前者(告知在前)
        reply = f"{expired_notice}\n\n{reply.replace(welcome.FIRST_OF_DAY_PREFIX, '')}"
    return reply


def _dispatch_awaiting_name(user_id: str, text: str, is_voice: bool) -> str | None:
    """等待取名 (awaiting_name): 命令优先, 之后才尝试从回答里提取名字。
    取名只问一轮: 提不出名字的长句当内容记下, 不再追问(取名流程不得吞日记)。"""
    intent, _suspect = detect_ex(text)
    if intent is Intent.HELP:
        return f"{welcome.HELP_TEXT}\n\n{welcome.STILL_AWAITING_NAME_HINT}"
    if intent is Intent.CHAT:
        return f"{welcome.ping_reply(diary_writer.count_day(user_id))}\n\n{welcome.STILL_AWAITING_NAME_HINT}"
    if intent in (Intent.FINALIZE, Intent.UNDO, Intent.START_DIARY):
        # 命令不拦路: 放行; 同句里带了名字先收下
        name, _ = names.extract(text)
        if name:
            user_profile.set_name(user_id, name)
        else:
            user_profile.skip_naming(user_id)
        reply = _handle(user_id, text, is_voice)
        if reply:
            tail = welcome.NAME_INLINE_CONFIRM_TEMPLATE.format(name=name) if name else welcome.NAME_LATER_HINT
            reply = f"{reply}\n\n{tail}"
        return reply

    name, refused = names.extract(text)
    if refused:
        user_profile.skip_naming(user_id)
        return welcome.NAME_SKIPPED_REPLY
    if name is not None:
        user_profile.set_name(user_id, name)
        return welcome.NAME_CONFIRM_TEMPLATE.format(name=name)
    # 看不出名字: 短句再问一次; 长句是内容, 记下并结束取名(不再追问)
    if len(text) <= 15:
        return welcome.NAME_UNCLEAR_HINT
    user_profile.skip_naming(user_id)
    reply = _handle(user_id, text, is_voice)
    return f"{reply}\n\n{welcome.NAME_LATER_HINT}" if reply else reply


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
    if config.AI_API_KEY:
        print("  ℹ️  AI_API_KEY 已配置, 但 v0.3 起 AI 润色/闲聊暂停用: 原文直存, 不发任何 LLM 请求")

    try:
        import scheduler as diary_scheduler
    except ModuleNotFoundError as e:
        if e.name and e.name.startswith("apscheduler"):
            print("  缺少依赖 apscheduler。先运行: python -m pip install -r requirements.txt")
            return 1
        raise

    sched = diary_scheduler.create_scheduler(_make_send_fn(state))
    sched.start()
    atexit.register(lambda: sched.shutdown(wait=False))
    if diary_scheduler.run_catchup(_make_send_fn(state)):
        print("  已补发今日提醒 (启动补偿)")

    print("\n=== wechat-diary 已启动 ===")
    print(f"  时区: {config.TIMEZONE}")
    print(f"  提醒: {config.REMIND_HOUR_1}:00 / {config.REMIND_HOUR_2}:00")
    print(f"  diary: {config.DIARY_DIR}")
    print(f"  一天边界: 凌晨 {config.DAY_START_HOUR} 点 (之前算前一天)")
    print("  AI: 停用 (v0.3 纯机械记录, 原文直存)")
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
