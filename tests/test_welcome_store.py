"""welcome_store 持久化测试。"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _reload(monkeypatch, tmp_path):
    # 把 STORE_FILE 路径重定向到 tmp_path,避免污染真实文件
    import welcome_store
    importlib.reload(welcome_store)
    monkeypatch.setattr(welcome_store, "STORE_FILE", tmp_path / "welcomed_users.json")
    return welcome_store


def test_not_welcomed_initially(monkeypatch, tmp_path):
    ws = _reload(monkeypatch, tmp_path)
    assert not ws.is_welcomed("u-abc")


def test_mark_then_check(monkeypatch, tmp_path):
    ws = _reload(monkeypatch, tmp_path)
    ws.mark_welcomed("u-abc")
    assert ws.is_welcomed("u-abc")
    assert not ws.is_welcomed("u-other")


def test_mark_idempotent(monkeypatch, tmp_path):
    ws = _reload(monkeypatch, tmp_path)
    ws.mark_welcomed("u-abc")
    ws.mark_welcomed("u-abc")
    # 文件内容应只有一个 u-abc
    import json
    data = json.loads((tmp_path / "welcomed_users.json").read_text(encoding="utf-8"))
    assert data == ["u-abc"]


def test_persists_across_reload(monkeypatch, tmp_path):
    ws = _reload(monkeypatch, tmp_path)
    ws.mark_welcomed("u-abc")

    # 模拟进程重启:重新 reload 模块但文件保留
    import welcome_store
    importlib.reload(welcome_store)
    monkeypatch.setattr(welcome_store, "STORE_FILE", tmp_path / "welcomed_users.json")
    assert welcome_store.is_welcomed("u-abc")
