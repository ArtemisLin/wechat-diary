"""v1 → v2 存量日记迁移: 平铺 YYYY-MM-DD.md → YYYY/ 子目录, 缺 frontmatter 的补上。

用法(在 wechat-diary/ 根目录):
    py scripts/migrate_v2.py           # 干跑: 只打印将要做什么, 不动文件
    py scripts/migrate_v2.py --apply   # 实际执行 (先自动备份到 DIARY_DIR/_backup_v1/)

回滚: 把 _backup_v1/ 里的文件复制回 DIARY_DIR 根目录, 删掉 YYYY/ 下对应文件。
"""
from __future__ import annotations

import io
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
_WEEKDAY_CN = "一二三四五六日"


def build_frontmatter(date_str: str) -> str:
    wd = _WEEKDAY_CN[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    return f"---\ndate: {date_str}\nweekday: 周{wd}\nsource: wechat-diary\n---\n\n"


def migrate(diary_dir: Path, apply: bool) -> list[str]:
    """迁移平铺日记文件。返回操作日志; apply=False 时只收集不执行。"""
    actions: list[str] = []
    files = sorted(p for p in diary_dir.iterdir() if p.is_file() and DATE_RE.match(p.name))
    if not files:
        actions.append("没有需要迁移的平铺日记文件")
        return actions
    backup = diary_dir / "_backup_v1"
    for f in files:
        year = DATE_RE.match(f.name).group(1)
        date_str = f.name[:-3]
        target = diary_dir / year / f.name
        if target.exists():
            actions.append(f"跳过 {f.name} (目标已存在: {year}/{f.name})")
            continue
        content = f.read_text(encoding="utf-8")
        needs_fm = not content.startswith("---\n")
        actions.append(f"{f.name} → {year}/{f.name}" + (" (+frontmatter)" if needs_fm else ""))
        if not apply:
            continue
        backup.mkdir(exist_ok=True)
        shutil.copy2(f, backup / f.name)
        if needs_fm:
            content = build_frontmatter(date_str) + content
        (diary_dir / year).mkdir(exist_ok=True)
        target.write_text(content, encoding="utf-8")
        f.unlink()
    return actions


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    import config  # noqa: E402  # 读 .env 里的 DIARY_DIR

    apply = "--apply" in sys.argv
    if not config.DIARY_DIR:
        print("DIARY_DIR 未配置 (.env)")
        return 1
    diary_dir = Path(config.DIARY_DIR)
    if not diary_dir.exists():
        print(f"DIARY_DIR 不存在: {diary_dir}")
        return 1
    print(f"{'【执行】' if apply else '【干跑】'} {diary_dir}")
    for line in migrate(diary_dir, apply):
        print("  " + line)
    if not apply:
        print("\n确认无误后运行: py scripts/migrate_v2.py --apply")
    else:
        print(f"\n完成。原文件备份在: {diary_dir / '_backup_v1'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
