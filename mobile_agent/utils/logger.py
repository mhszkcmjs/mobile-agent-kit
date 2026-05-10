"""统一日志:控制台 + 任务级文件日志。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mobile_agent.config import cfg


_FMT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATEFMT = "%H:%M:%S"


def get_logger(name: str = "mobile_agent", task_dir: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:  # 已配置过,直接返回
        return logger

    logger.setLevel(getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO))

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    logger.addHandler(sh)

    if task_dir is not None:
        task_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            task_dir / "run.log", maxBytes=5_000_000, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
        logger.addHandler(fh)

    logger.propagate = False
    return logger
