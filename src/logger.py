"""统一日志封装: RotatingFileHandler, 1MB / 5 份。

Phase 0.2:
- ilink 收发/登录/网络事件 → data/logs/ilink.log
- LLM 调用失败原因         → data/logs/ai.log

设计:
- get_logger 幂等 (依 logger.handlers 判重), 重复调用不会产生重复日志
- propagate=False, 不向根 logger 冒泡, 避免 pytest 等环境重复输出
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMATTER = logging.Formatter(
    fmt="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_MAX_BYTES = 1024 * 1024  # 1 MB
_BACKUP_COUNT = 5


def get_logger(name: str, log_file: Path) -> logging.Logger:
    """按名字拿到一个绑定到指定文件的 logger, 幂等。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(_FORMATTER)
    logger.addHandler(handler)
    return logger
