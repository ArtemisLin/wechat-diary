"""配置加载 + 时区工具。

所有业务代码禁止直接 datetime.now() / date.today(),必须走 now_bj() / today_str()。
理由:部署机器可能是美西时区,系统时间 ≠ 北京时间,日期文件名会错。
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# 入口脚本处理 Windows 终端中文乱码(CLAUDE.md 规则)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def _load_env_file(path: Path) -> None:
    """极简 .env 解析器,不依赖 python-dotenv。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
_load_env_file(PROJECT_ROOT / ".env")

# === 时区 ===
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Shanghai")
TZ = ZoneInfo(TIMEZONE)


def now_bj() -> datetime:
    """当前时间(北京时区,或 TIMEZONE 指定时区)。"""
    return datetime.now(TZ)


def today_str() -> str:
    """今天的日期字符串 YYYY-MM-DD(北京时区)。"""
    return now_bj().strftime("%Y-%m-%d")


def hhmm_str() -> str:
    """当前时分 HH:MM(北京时区)。"""
    return now_bj().strftime("%H:%M")


# === AI ===
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com/chat/completions")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")

# === 用户 / 日记目录 ===
USER_ID = os.environ.get("USER_ID", "")
DIARY_DIR = os.environ.get("DIARY_DIR", "")

# === 提醒时间 ===
REMIND_HOUR_1 = int(os.environ.get("REMIND_HOUR_1", "22"))
REMIND_HOUR_2 = int(os.environ.get("REMIND_HOUR_2", "23"))
