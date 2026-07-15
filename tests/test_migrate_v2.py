"""migrate_v2 迁移逻辑测试(纯函数, 不碰真实 vault)。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from migrate_v2 import build_frontmatter, migrate  # noqa: E402


def _mk(dir_: Path, name: str, content: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_text(content, encoding="utf-8")
    return p


def test_dry_run_changes_nothing(tmp_path):
    _mk(tmp_path, "2026-01-05.md", "# 2026-01-05\n\n**10:00**\n\n内容\n")
    actions = migrate(tmp_path, apply=False)
    assert any("2026-01-05.md" in a for a in actions)
    assert (tmp_path / "2026-01-05.md").exists(), "干跑不应移动文件"
    assert not (tmp_path / "2026").exists()


def test_apply_moves_backs_up_and_adds_frontmatter(tmp_path):
    _mk(tmp_path, "2026-01-05.md", "# 2026-01-05\n\n**10:00**\n\n内容\n")
    migrate(tmp_path, apply=True)
    moved = tmp_path / "2026" / "2026-01-05.md"
    assert moved.exists()
    assert not (tmp_path / "2026-01-05.md").exists()
    assert (tmp_path / "_backup_v1" / "2026-01-05.md").exists(), "必须先备份"
    content = moved.read_text(encoding="utf-8")
    assert content.startswith("---\ndate: 2026-01-05\n")
    assert "内容" in content, "原文必须保留"


def test_apply_idempotent_and_skips_existing_frontmatter(tmp_path):
    _mk(tmp_path, "2026-01-05.md", "---\ndate: 2026-01-05\n---\n\n# 2026-01-05\n\n正文\n")
    migrate(tmp_path, apply=True)
    first = (tmp_path / "2026" / "2026-01-05.md").read_text(encoding="utf-8")
    assert first.count("---\ndate") == 1, "已有 frontmatter 不重复加"
    migrate(tmp_path, apply=True)  # 第二次: 无平铺文件, 应无操作
    assert (tmp_path / "2026" / "2026-01-05.md").read_text(encoding="utf-8") == first


def test_non_diary_files_untouched(tmp_path):
    other = _mk(tmp_path, "notes.md", "别动我")
    _mk(tmp_path, "2026-02-01.md", "# x\n")
    migrate(tmp_path, apply=True)
    assert other.exists() and other.read_text(encoding="utf-8") == "别动我"


def test_build_frontmatter_weekday():
    fm = build_frontmatter("2026-07-15")  # 2026-07-15 是周三
    assert "date: 2026-07-15" in fm
    assert "weekday: 周三" in fm
    assert "source: wechat-diary" in fm
