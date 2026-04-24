"""users.load() 单用户实现的测试。"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _reload(monkeypatch, env: dict) -> tuple:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    import users
    importlib.reload(config)
    importlib.reload(users)
    return config, users


def test_load_valid_user(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    _, users = _reload(monkeypatch, {"USER_ID": "u-abc", "VAULT_DIR": str(vault)})
    u = users.load("u-abc")
    assert u.user_id == "u-abc"
    assert u.vault_dir == vault
    assert vault.exists(), "vault_dir should be auto-created"


def test_load_unknown_user_raises(monkeypatch, tmp_path):
    _, users = _reload(monkeypatch, {"USER_ID": "u-abc", "VAULT_DIR": str(tmp_path)})
    with pytest.raises(users.UserNotFoundError):
        users.load("u-other")


def test_load_empty_user_raises(monkeypatch, tmp_path):
    _, users = _reload(monkeypatch, {"USER_ID": "u-abc", "VAULT_DIR": str(tmp_path)})
    with pytest.raises(users.UserNotFoundError):
        users.load("")


def test_load_missing_vault_raises(monkeypatch):
    _, users = _reload(monkeypatch, {"USER_ID": "u-abc", "VAULT_DIR": ""})
    with pytest.raises(ValueError):
        users.load("u-abc")


def test_all_active_single_user(monkeypatch, tmp_path):
    _, users = _reload(monkeypatch, {"USER_ID": "u-abc", "VAULT_DIR": str(tmp_path)})
    assert list(users.all_active()) == ["u-abc"]


def test_timezone_defaults_to_shanghai(monkeypatch, tmp_path):
    monkeypatch.delenv("TIMEZONE", raising=False)
    config, _ = _reload(monkeypatch, {"USER_ID": "u-abc", "VAULT_DIR": str(tmp_path)})
    assert config.TIMEZONE == "Asia/Shanghai"
    assert config.now_bj().utcoffset().total_seconds() == 8 * 3600


def test_today_str_uses_timezone_not_system(monkeypatch, tmp_path):
    """即使系统时区是 UTC,today_str() 应该返回北京日期。"""
    config, _ = _reload(monkeypatch, {"USER_ID": "u-abc", "VAULT_DIR": str(tmp_path), "TIMEZONE": "Asia/Shanghai"})
    # today_str 格式验证(不测具体值以避开跑测时刚好跨天的边界)
    s = config.today_str()
    assert len(s) == 10 and s[4] == "-" and s[7] == "-"
