"""配置加载 + 时区工具。

所有业务代码禁止直接 datetime.now() / date.today(),必须走 now_bj() / today_str()。
理由:部署机器可能是美西时区,系统时间 ≠ 北京时间,日期文件名会错。
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta
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


if getattr(sys, "frozen", False):
    # PyInstaller 打包态: .env 在 exe 旁边 (与 paths.ROOT 同一逻辑)
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    # 冻结态 CA 证书: 构建机 Python 的证书路径在用户机器上不存在, 不带上
    # certifi 的证书文件, macOS 上所有 HTTPS 都会 CERTIFICATE_VERIFY_FAILED
    # (登录二维码/AI 润色全挂; Windows 因走系统证书库幸免)。
    # OpenSSL 尊重 SSL_CERT_FILE 环境变量; 用户已设置的话不覆盖。
    _bundled_ca = Path(getattr(sys, "_MEIPASS", "")) / "certifi" / "cacert.pem"
    if _bundled_ca.exists():
        os.environ.setdefault("SSL_CERT_FILE", str(_bundled_ca))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
_load_env_file(PROJECT_ROOT / ".env")

# === 时区 ===
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Shanghai")
TZ = ZoneInfo(TIMEZONE)


def now_bj() -> datetime:
    """当前时间(北京时区,或 TIMEZONE 指定时区)。"""
    return datetime.now(TZ)


def today_str() -> str:
    """今天的【日历】日期字符串 YYYY-MM-DD(北京时区)。

    ⚠️ 日记文件名/封存/计数一律用 logical_today_str(), 不要用这个——
    契约 v1.2 起"今天"指逻辑日(凌晨 DAY_START_HOUR 点前算前一天)。
    """
    return now_bj().strftime("%Y-%m-%d")


def hhmm_str() -> str:
    """当前时分 HH:MM(北京时区)。"""
    return now_bj().strftime("%H:%M")


# === 逻辑日 (契约 v1.2, 2026-08-16) ===
# 一天的边界不是零点, 而是凌晨 DAY_START_HOUR 点(默认 4): 夜猫子睡前记的属于"今晚"。
# 段头时间戳仍写真实时间(00:30 出现在昨天的文件里, 日记本来如此)。
def _parse_day_start_hour(raw: str) -> int:
    try:
        h = int(raw)
    except (TypeError, ValueError):
        return 4
    return h if 0 <= h <= 12 else 4


DAY_START_HOUR = _parse_day_start_hour(os.environ.get("DAY_START_HOUR", "4"))


def logical_today_str(now: datetime | None = None) -> str:
    """逻辑日 YYYY-MM-DD: 凌晨 DAY_START_HOUR 点前算前一天。"""
    t = now if now is not None else now_bj()
    return (t - timedelta(hours=DAY_START_HOUR)).strftime("%Y-%m-%d")


def is_night_now(now: datetime | None = None) -> bool:
    """现在是不是"深夜段"(20 点后到逻辑日边界前): 收尾语选晚安池用。"""
    t = now if now is not None else now_bj()
    return t.hour >= 20 or t.hour < DAY_START_HOUR


_WEEKDAY_CN = "一二三四五六日"


def weekday_str() -> str:
    """今天(日历日)是周几(中文), 北京时区。日记 frontmatter 请用 weekday_for()。"""
    return f"周{_WEEKDAY_CN[now_bj().weekday()]}"


def weekday_for(date_str: str) -> str:
    """指定 YYYY-MM-DD 是周几(中文), 与时区无关。"""
    return f"周{_WEEKDAY_CN[datetime.strptime(date_str, '%Y-%m-%d').weekday()]}"


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
