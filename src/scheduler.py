"""日记提醒调度器。

每晚 REMIND_HOUR_1 和 REMIND_HOUR_2(北京时间)检查,当天未写则推送微信提醒。
无 context_token 或已过期时记日志跳过(015fridge 经验:等用户下次发消息自然刷新)。
"""
from __future__ import annotations

from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler

import config
import diary_writer
import users

REMIND_TEXT_1_TEMPLATE = "{name}, 今天还没记呢~ 想记的话发「开始记日记」就开始 📖"
REMIND_TEXT_2_TEMPLATE = "{name}, 快睡了, 还要不要留几句给今天? 发「开始记日记」开始记录"


def check_and_remind(user_id: str, text: str, send_fn: Callable[[str, str], bool]) -> bool:
    """单用户:当天无内容则发提醒。返回"是否发送了"。
    send_fn(user_id, text) → bool"""
    try:
        users.load(user_id)
        if diary_writer.today_has_content(user_id):
            return False
        return bool(send_fn(user_id, text))
    except users.UserNotFoundError:
        print(f"  提醒跳过:未知用户 {user_id}")
        return False
    except Exception as e:  # 降级到日志,绝不让 scheduler 挂
        print(f"  提醒失败({user_id}): {e}")
        return False


def make_reminder_job(text_template: str, send_fn: Callable[[str, str], bool]) -> Callable[[], None]:
    """生成一个 cron 回调, 遍历所有活跃用户触发 check_and_remind。

    text_template 含 {name} 占位, 触发时按用户名字渲染 (未取名回落'你')。
    """
    def job() -> None:
        import user_profile
        for uid in users.all_active():
            name = user_profile.get_name(uid)
            text = text_template.format(name=name)
            check_and_remind(uid, text, send_fn)
    return job


def create_scheduler(send_fn: Callable[[str, str], bool]) -> BackgroundScheduler:
    """创建 APScheduler, 注册 REMIND_HOUR_1 / REMIND_HOUR_2 两个北京时间 cron。
    send_fn(user_id, text) 注入以便测试。"""
    sched = BackgroundScheduler(timezone=config.TIMEZONE)
    sched.add_job(
        make_reminder_job(REMIND_TEXT_1_TEMPLATE, send_fn),
        trigger="cron", hour=config.REMIND_HOUR_1, minute=0,
        id="remind_1", replace_existing=True,
    )
    sched.add_job(
        make_reminder_job(REMIND_TEXT_2_TEMPLATE, send_fn),
        trigger="cron", hour=config.REMIND_HOUR_2, minute=0,
        id="remind_2", replace_existing=True,
    )
    return sched
