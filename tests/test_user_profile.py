"""user_profile 持久化 + 旧 welcomed_users.json 迁移测试。"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    profile_file = tmp_path / "user_profiles.json"
    legacy_file = tmp_path / "welcomed_users.json"
    monkeypatch.setenv("USER_ID", "u-abc")
    monkeypatch.setenv("DIARY_DIR", str(tmp_path / "diary"))
    monkeypatch.setenv("TIMEZONE", "Asia/Shanghai")
    import config, paths, user_profile
    importlib.reload(config)
    importlib.reload(paths)
    importlib.reload(user_profile)
    monkeypatch.setattr(user_profile, "PROFILE_FILE", profile_file)
    monkeypatch.setattr(user_profile, "LEGACY_FILE", legacy_file)
    return user_profile, profile_file, legacy_file


def test_unknown_user_returns_default_unwelcomed(setup):
    """未见过的 user_id → 默认未欢迎, 状态 unknown。"""
    up, _, _ = setup
    p = up.load("u-abc")
    assert p.state == "unknown"
    assert p.name is None


def test_mark_welcomed_starts_awaiting_name(setup):
    """mark_welcomed 把状态切到 awaiting_name (等用户告知名字)。"""
    up, _, _ = setup
    up.mark_welcomed("u-abc")
    p = up.load("u-abc")
    assert p.state == "awaiting_name"
    assert p.welcomed_at is not None


def test_set_name_advances_to_active(setup):
    """set_name 后状态切到 active, name 持久化。"""
    up, _, _ = setup
    up.mark_welcomed("u-abc")
    up.set_name("u-abc", "谷雨")
    p = up.load("u-abc")
    assert p.state == "active"
    assert p.name == "谷雨"


def test_get_name_returns_default_for_unnamed(setup):
    """未取名时 get_name 返回 '你'。"""
    up, _, _ = setup
    assert up.get_name("u-abc") == "你"
    up.mark_welcomed("u-abc")
    assert up.get_name("u-abc") == "你"  # awaiting_name 时仍是默认
    up.set_name("u-abc", "谷雨")
    assert up.get_name("u-abc") == "谷雨"


def test_legacy_migration_from_welcomed_users_json(setup):
    """旧 welcomed_users.json (list) 迁移到 user_profiles.json (dict),
    name=None, state=awaiting_name (强制重新问一次名字)。"""
    up, profile_file, legacy_file = setup
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text(json.dumps(["u-abc", "u-other"]), encoding="utf-8")

    up.migrate_legacy()

    assert profile_file.exists()
    assert not legacy_file.exists(), "迁移后旧文件应删除"
    data = json.loads(profile_file.read_text(encoding="utf-8"))
    assert "u-abc" in data
    assert data["u-abc"]["name"] is None
    assert data["u-abc"]["state"] == "awaiting_name"


def test_migration_idempotent(setup):
    """迁移幂等: 调两次不重复处理 (legacy 不存在时跳过)。"""
    up, profile_file, legacy_file = setup
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text(json.dumps(["u-abc"]), encoding="utf-8")
    up.migrate_legacy()  # 第一次
    up.migrate_legacy()  # 第二次, 不报错


def test_atomic_write_no_residual_tmp(setup):
    """原子写入, 不留 .tmp 残留。"""
    up, profile_file, _ = setup
    up.mark_welcomed("u-abc")
    assert profile_file.exists()
    assert not profile_file.with_suffix(".json.tmp").exists()


def test_is_welcomed_compatibility(setup):
    """is_welcomed (向后兼容 main.py 调用): 任何非 unknown 状态都视为已欢迎。"""
    up, _, _ = setup
    assert not up.is_welcomed("u-abc")
    up.mark_welcomed("u-abc")
    assert up.is_welcomed("u-abc")
    up.set_name("u-abc", "谷雨")
    assert up.is_welcomed("u-abc")
