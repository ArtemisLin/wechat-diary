"""envfile.update_env 的测试: 注释保留 / 原子性 / 引号 / 新增键。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import envfile  # noqa: E402


def test_replace_existing_key_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nUSER_ID=old\nB=2\n", encoding="utf-8")
    envfile.update_env(env, {"USER_ID": "new-id"})
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["A=1", "USER_ID=new-id", "B=2"], "已有键应原位替换, 行序不变"


def test_comments_and_blank_lines_preserved(tmp_path):
    env = tmp_path / ".env"
    original = "# 顶部注释\n\n# USER_ID 的说明\nUSER_ID=old\n\n# 尾部注释\n"
    env.write_text(original, encoding="utf-8")
    envfile.update_env(env, {"USER_ID": "new"})
    text = env.read_text(encoding="utf-8")
    assert "# 顶部注释" in text
    assert "# USER_ID 的说明" in text
    assert "# 尾部注释" in text
    assert text.count("\n\n") == original.count("\n\n"), "空行应原样保留"
    assert "USER_ID=new" in text
    assert "USER_ID=old" not in text


def test_commented_out_key_not_touched(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# AI_API_KEY=example\nAI_API_KEY=old\n", encoding="utf-8")
    envfile.update_env(env, {"AI_API_KEY": "new"})
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["# AI_API_KEY=example", "AI_API_KEY=new"]


def test_new_keys_appended_to_tail(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    envfile.update_env(env, {"DIARY_DIR": "/tmp/diary", "USER_ID": "u1"})
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "A=1"
    assert "DIARY_DIR=/tmp/diary" in lines[1:]
    assert "USER_ID=u1" in lines[1:]


def test_creates_file_when_missing(tmp_path):
    env = tmp_path / "sub" / ".env"
    envfile.update_env(env, {"USER_ID": "u1"})
    assert env.read_text(encoding="utf-8") == "USER_ID=u1\n"


def test_value_with_space_or_hash_gets_quoted(tmp_path):
    env = tmp_path / ".env"
    envfile.update_env(env, {"DIARY_DIR": "/Users/某人/My Diary", "NOTE": "a#b"})
    text = env.read_text(encoding="utf-8")
    assert 'DIARY_DIR="/Users/某人/My Diary"' in text
    assert 'NOTE="a#b"' in text


def test_quoted_value_roundtrips_through_config_parser(tmp_path, monkeypatch):
    """加引号后的值必须能被 config._load_env_file 原样读回。"""
    import config

    env = tmp_path / ".env"
    envfile.update_env(env, {"DIARY_DIR": "/tmp/My Diary"})
    monkeypatch.delenv("DIARY_DIR", raising=False)
    config._load_env_file(env)
    import os
    assert os.environ.get("DIARY_DIR") == "/tmp/My Diary"


def test_atomic_write_no_tmp_leftover(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    envfile.update_env(env, {"A": "2"})
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != ".env"]
    assert leftovers == [], "不应留下 .tmp 中间文件"


def test_file_without_trailing_newline(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1", encoding="utf-8")  # 无末尾换行
    envfile.update_env(env, {"B": "2"})
    assert env.read_text(encoding="utf-8") == "A=1\nB=2\n"
