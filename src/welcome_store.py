"""欢迎记录持久化:记住哪些 user_id 已收到过欢迎致辞,避免重复发。"""
from __future__ import annotations

import json
import os

import paths

STORE_FILE = paths.WELCOMED_USERS


def _load() -> set[str]:
    if not STORE_FILE.exists():
        return set()
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
        return set()
    except (json.JSONDecodeError, OSError):
        return set()


def _save(s: set[str]) -> None:
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STORE_FILE)


def is_welcomed(user_id: str) -> bool:
    return user_id in _load()


def mark_welcomed(user_id: str) -> None:
    s = _load()
    if user_id in s:
        return
    s.add(user_id)
    _save(s)
