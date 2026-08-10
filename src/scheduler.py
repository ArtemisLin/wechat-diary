"""日记提醒调度器。

每晚 REMIND_HOUR_1 和 REMIND_HOUR_2(北京时间)检查,当天未写则推送微信提醒。
无 context_token 或已过期时记日志跳过(015fridge 经验:等用户下次发消息自然刷新)。
"""
from __future__ import annotations

import json
import os
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import diary_writer
import paths
import users

REMIND_TEXT_1_TEMPLATE = "{name}, 今天还没记呢~ 想记的话发「开始记日记」就开始 📖"
REMIND_TEXT_2_TEMPLATE = "{name}, 快睡了, 还要不要留几句给今天? 发「开始记日记」开始记录"

CATCHUP_FILE = paths.DATA_DIR / "remind_state.json"


def _load_catchup_date() -> str:
    try:
        return json.loads(CATCHUP_FILE.read_text(encoding="utf-8")).get("last_catchup_date", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _save_catchup_date(date_str: str) -> None:
    CATCHUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CATCHUP_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"last_catchup_date": date_str}), encoding="utf-8")
    os.replace(tmp, CATCHUP_FILE)


def run_catchup(send_fn: Callable[[str, str], bool]) -> bool:
    """启动补偿 (v2 C.2): 已过 REMIND_HOUR_1 且当天未写且今天没补偿过, 补发一次提醒。
    无论是否发送成功, 当天只尝试一次(记录日期), 避免反复重启刷屏。"""
    if config.now_bj().hour < config.REMIND_HOUR_1:
        return False
    today = config.today_str()
    if _load_catchup_date() == today:
        return False
    import user_profile
    sent_any = False
    for uid in users.all_active():
        name = user_profile.get_name(uid)
        text = REMIND_TEXT_1_TEMPLATE.format(name=name)
        if check_and_remind(uid, text, send_fn):
            sent_any = True
    _save_catchup_date(today)
    return sent_any


def check_and_remind(user_id: str, text: str, send_fn: Callable[[str, str], bool]) -> bool:
    """单用户:当天无内容则发提醒。返回"是否发送了"。
    send_fn(user_id, text) → bool"""
    try:
        users.load(user_id)
        if diary_writer.today_has_content(user_id):
            # 正当跳过(今天已经写过了)。打出来, 免得和"发失败"混淆 ——
            # 排查提醒问题时要能一眼分清"没发"和"发了但没到"。
            print(f"  提醒跳过({config.hhmm_str()}): 今天已经写过了")
            return False
        print(f"  提醒触发({config.hhmm_str()}): 今天还没写, 尝试发送...")
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
    # 显式 CronTrigger 而非 trigger="cron" 字符串: 字符串形式经 setuptools
    # entry points 动态解析, PyInstaller 打包态下会找不到; 显式导入两态都稳。
    # timezone 必须显式传给 Trigger —— 手工构造的 Trigger 不继承 scheduler 的时区
    sched = BackgroundScheduler(timezone=config.TIMEZONE)
    sched.add_job(
        make_reminder_job(REMIND_TEXT_1_TEMPLATE, send_fn),
        trigger=CronTrigger(hour=config.REMIND_HOUR_1, minute=0, timezone=config.TZ),
        id="remind_1", replace_existing=True,
    )
    sched.add_job(
        make_reminder_job(REMIND_TEXT_2_TEMPLATE, send_fn),
        trigger=CronTrigger(hour=config.REMIND_HOUR_2, minute=0, timezone=config.TZ),
        id="remind_2", replace_existing=True,
    )
    return sched
