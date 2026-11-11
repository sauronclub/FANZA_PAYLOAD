# -*- coding: utf-8 -*-
"""日志组件包。

提供 :func:`setup_logging` 统一初始化，配合 config/logging.py 使用。
"""

from __future__ import annotations

import logging

from .setup import LOGGING_FILENAME, setup_logging

__all__ = ["LOGGING_FILENAME", "setup_logging", "get_logger"]


def get_logger(name: str) -> logging.Logger:
    """获取带 `src.` 前缀的模块日志器。

    :param name: 模块短名，例如 ``"runner.orchestrator"``
    """
    return logging.getLogger(f"src.{name}")
