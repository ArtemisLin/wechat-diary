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


# === 大修 2026-08-10: 同一条 msg 的多 item 合并 (长内容被平台拆分) ===

def _text_item(t):
    return {"type": 1, "text_item": {"text": t}}


def _voice_item(t):
    return {"type": 3, "voice_item": {"text": t}}


def test_coalesce_single_text():
    from ilink import _coalesce_items
    assert _coalesce_items([_text_item("你好")]) == ("你好", False, False)


def test_coalesce_chunked_text_joined_without_separator():
    """长文本被拆成多个 item → 原样拼回 (拆分点在句子中间)。"""
    from ilink import _coalesce_items
    text, is_voice, _ = _coalesce_items([_text_item("今天去了公"), _text_item("园散步")])
    assert text == "今天去了公园散步"
    assert is_voice is False


def test_coalesce_chunked_voice():
    from ilink import _coalesce_items
    text, is_voice, empty = _coalesce_items([_voice_item("上半句"), _voice_item("下半句")])
    assert text == "上半句下半句"
    assert is_voice is True
    assert empty is False


def test_coalesce_empty_voice_flagged():
    """转写为空的语音 → 文本空 + has_empty_voice, 上层回复"没听清"。"""
    from ilink import _coalesce_items
    assert _coalesce_items([_voice_item("")]) == ("", True, True)


def test_coalesce_partial_empty_voice_keeps_text():
    """部分 item 转写为空: 有内容的照收, 不因空 item 丢整条。"""
    from ilink import _coalesce_items
    text, is_voice, empty = _coalesce_items([_voice_item("有内容"), _voice_item("")])
    assert text == "有内容"
    assert empty is True


def test_coalesce_ignores_unknown_types():
    from ilink import _coalesce_items
    items = [{"type": 99, "foo": {}}, _text_item("正文")]
    assert _coalesce_items(items)[0] == "正文"


def test_coalesce_empty_list():
    from ilink import _coalesce_items
    assert _coalesce_items([]) == ("", False, False)
