"""用户配置加载。

第一版单用户实现:从 env 读 USER_ID + VAULT_DIR,组装成 UserConfig。
未来多用户:改为读 users.json / SQLite,load(user_id) 接口不变。

**核心契约**:任何涉及"谁"的函数都必须接 user_id 参数,
禁止业务逻辑硬编码用户名/路径。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import config


@dataclass(frozen=True)
class UserConfig:
    user_id: str
    vault_dir: Path


class UserNotFoundError(KeyError):
    pass


def load(user_id: str) -> UserConfig:
    """根据 user_id 返回用户配置。未知 user_id 抛 UserNotFoundError。"""
    if not user_id:
        raise UserNotFoundError("user_id is empty")
    if user_id != config.USER_ID:
        raise UserNotFoundError(f"unknown user_id: {user_id}")
    if not config.VAULT_DIR:
        raise ValueError("VAULT_DIR not configured in .env")
    vault = Path(config.VAULT_DIR)
    vault.mkdir(parents=True, exist_ok=True)
    return UserConfig(user_id=user_id, vault_dir=vault)


def all_active() -> Iterable[str]:
    """返回所有活跃用户 ID(第一版:只有 config.USER_ID 一个)。"""
    if config.USER_ID:
        yield config.USER_ID
