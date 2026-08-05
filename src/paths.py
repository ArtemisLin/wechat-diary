"""统一管理 data/ 目录下的运行时文件路径, 以及一次性迁移旧版文件的逻辑。

Phase 0.5: ilink_state.json / welcomed_users.json / ilink_debug.log
从项目根目录集中到 data/ (日志进一步放到 data/logs/)。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"

ILINK_STATE = DATA_DIR / "ilink_state.json"
WELCOMED_USERS = DATA_DIR / "welcomed_users.json"
ILINK_LOG = LOGS_DIR / "ilink.log"
AI_LOG = LOGS_DIR / "ai.log"
# 主动推送探针日志: 每次 send_to_user 记一行 (token 年龄 / 返回码 / 成败),
# 用来攒数据回答"context_token 到底多久失效"。人可读, 直接 cat 就行。
REMIND_PROBE_LOG = LOGS_DIR / "remind-probe.log"
SESSION_STATE = DATA_DIR / "session_state.json"
USER_PROFILES = DATA_DIR / "user_profiles.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy() -> None:
    """把根目录旧版运行时文件挪到 data/, 只在新位置不存在时迁。幂等, 可重复调。"""
    ensure_dirs()
    legacy_map = (
        (ROOT / "ilink_state.json", ILINK_STATE),
        (ROOT / "welcomed_users.json", WELCOMED_USERS),
        (ROOT / "ilink_debug.log", ILINK_LOG),
    )
    for old, new in legacy_map:
        if old.exists() and not new.exists():
            try:
                old.replace(new)
            except OSError:
                pass
