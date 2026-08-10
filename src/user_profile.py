"""用户 Profile 持久化: 名字 + 欢迎/取名状态。

替代 welcome_store.py。新增字段 name 用于个性化称呼 (提醒/收尾/招呼场景)。

状态机:
  unknown        — 从未见过 (默认)
  awaiting_name  — 已发欢迎致辞, 等用户告知名字
  active         — 已取名, 正常使用

存储: data/user_profiles.json
{
  "u-abc": {
    "name": "谷雨",
    "welcomed_at": "2026-04-25 10:00",
    "named_at": "2026-04-25 10:01",
    "state": "active"
  }
}
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass

import config
import paths

PROFILE_FILE = paths.USER_PROFILES
LEGACY_FILE = paths.DATA_DIR / "welcomed_users.json"
_lock = threading.Lock()


@dataclass
class UserProfile:
    user_id: str
    name: str | None = None
    welcomed_at: str | None = None
    named_at: str | None = None
    state: str = "unknown"  # unknown | awaiting_name | active


def _read_all() -> dict:
    if not PROFILE_FILE.exists():
        return {}
    try:
        return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data: dict) -> None:
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROFILE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PROFILE_FILE)


def load(user_id: str) -> UserProfile:
    """读取 profile; 不存在返回 unknown 默认。"""
    with _lock:
        data = _read_all()
        raw = data.get(user_id)
        if raw is None:
            return UserProfile(user_id=user_id)
        return UserProfile(
            user_id=user_id,
            name=raw.get("name"),
            welcomed_at=raw.get("welcomed_at"),
            named_at=raw.get("named_at"),
            state=raw.get("state", "unknown"),
        )


def save(p: UserProfile) -> None:
    with _lock:
        data = _read_all()
        d = asdict(p)
        d.pop("user_id", None)
        data[p.user_id] = d
        _write_all(data)


def mark_welcomed(user_id: str) -> None:
    """首次欢迎致辞已发, 进入 awaiting_name 状态。"""
    p = load(user_id)
    p.welcomed_at = config.now_bj().strftime("%Y-%m-%d %H:%M")
    p.state = "awaiting_name"
    save(p)


def set_name(user_id: str, name: str) -> None:
    """记录用户名字, 状态切到 active。"""
    p = load(user_id)
    p.name = name
    p.named_at = config.now_bj().strftime("%Y-%m-%d %H:%M")
    p.state = "active"
    save(p)


def skip_naming(user_id: str) -> None:
    """跳过取名 (用户拒绝 / 直接发命令): 不设名字, 状态切到 active。

    之后仍可在 chat 模式发「叫我XX」补上名字。
    """
    p = load(user_id)
    p.state = "active"
    save(p)


def get_name(user_id: str, fallback: str = "你") -> str:
    """取名字 (供模板用); 未取名返回默认 '你'。"""
    p = load(user_id)
    return p.name or fallback


def is_welcomed(user_id: str) -> bool:
    """向后兼容 welcome_store.is_welcomed: 非 unknown 即视为已欢迎。"""
    return load(user_id).state != "unknown"


def migrate_legacy() -> None:
    """旧 welcomed_users.json (list[str]) 迁移到新格式 (dict)。

    旧用户置 state=unknown (而非 awaiting_name): 因为 bot 不能主动推欢迎致辞,
    若直接置 awaiting_name, 老用户下一条消息会被当名字存掉, 用户感受不到流程。
    置 unknown 后, 下次 _on_message 会走完整流程: 第一条触发 WELCOME (问名字),
    第二条作为名字。幂等。
    """
    if not LEGACY_FILE.exists():
        return
    try:
        legacy = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(legacy, list):
        return

    with _lock:
        data = _read_all()
        for uid in legacy:
            if uid not in data:
                data[uid] = {
                    "name": None,
                    "welcomed_at": None,
                    "named_at": None,
                    "state": "unknown",
                }
        _write_all(data)
        try:
            LEGACY_FILE.unlink()
        except OSError:
            pass
