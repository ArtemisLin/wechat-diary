""".env 文件的原子更新工具 (webui 用)。

设计约束 (docs/webui-design.md):
- 逐行解析, 已有键原位替换, 新键追加到尾部
- 注释与空行原样保留 (用户手写的说明不能被冲掉)
- 先写 .tmp 再 os.replace, 保证原子性 (写一半断电不会留下残缺 .env)
- 值含空格 / # / 引号时加双引号 (与 config._load_env_file 的极简解析器互认)
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

# read-modify-write 不是原子操作: ThreadingHTTPServer 下多个 handler 线程
# 并发 update_env 会互相丢键, 进程内加锁串行化 (单进程场景足够)
_write_lock = threading.Lock()


def format_value(value: str) -> str:
    """把值格式化成 .env 行右侧的形态: 含空格/#/引号时包双引号。

    含换行/回车直接拒绝: 换行会把一行拆成多行 → .env 任意键注入。
    config 的极简解析器不解码转义, 所以只能拒绝, 不能转义。
    """
    v = str(value)
    if "\n" in v or "\r" in v:
        raise ValueError("配置值不能包含换行符")
    if v and any(c in v for c in (" ", "#", '"', "'")):
        # config._load_env_file 只 strip 首尾引号, 不解析转义 —— 这里同样
        # 不做转义, 仅把内部双引号替换成单引号避免歧义 (env 值极少含引号)
        return '"' + v.replace('"', "'") + '"'
    return v


def update_env(path, mapping: dict) -> None:
    """更新 path 指向的 .env: mapping 中已有键原位替换, 新键追加到尾部。

    - 注释行 / 空行 / 未知键原样保留, 行序不变
    - 同一键出现多次时只替换第一次出现的那行 (config 解析器也是首行生效)
    - 文件不存在时直接创建
    - 原子写: 先写同目录 .tmp, 再 os.replace
    """
    path = Path(path)
    with _write_lock:
        lines: list = []
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()

        pending = dict(mapping)  # 尚未落位的键
        out = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in pending:
                    out.append(f"{key}={format_value(pending.pop(key))}")
                    continue
            out.append(line)

        for key, value in pending.items():
            out.append(f"{key}={format_value(value)}")

        content = "\n".join(out)
        if content and not content.endswith("\n"):
            content += "\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
