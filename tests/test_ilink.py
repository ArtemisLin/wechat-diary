"""ilink 模块的轻量单元测试 (不涉及网络/iLink 实际通信)。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_status_exit_code_ok():
    """status 探活 ok → exit 0 (start.bat 直接通过)。"""
    from ilink import _status_to_exit_code
    assert _status_to_exit_code("ok") == 0


def test_status_exit_code_network():
    """status 探活 network → exit 2 (start.bat 给网络容错提示, 仍启动)。"""
    from ilink import _status_to_exit_code
    assert _status_to_exit_code("network") == 2


def test_status_exit_code_other():
    """status 探活其他 → exit 1 (start.bat 触发重新登录)。"""
    from ilink import _status_to_exit_code
    assert _status_to_exit_code("error") == 1
    assert _status_to_exit_code("expired") == 1
    assert _status_to_exit_code("") == 1
