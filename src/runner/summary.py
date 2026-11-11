# -*- coding: utf-8 -*-
"""运行摘要与退出码。

退出码约定（便于 systemd / 监控系统判断）：
  0  全部页面成功
  1  部分或全部页面失败
  2  运行前的致命错误（配置、浏览器无法启动等）
"""

from __future__ import annotations

import json
import logging

from ..core.models import RunResult

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_FATAL = 2


def compute_exit_code(result: RunResult) -> int:
    """根据运行结果给出进程退出码。"""
    return EXIT_OK if result.ok else EXIT_PARTIAL


def log_summary(logger: logging.Logger, result: RunResult) -> None:
    """把运行摘要写入日志。

    同时输出人类可读文本与一行结构化 JSON，
    便于人工查看和后续日志系统检索。
    """
    logger.info("─" * 60)
    logger.info("运行摘要")
    for line in result.summary_text().splitlines():
        logger.info("  %s", line)
    logger.info(
        "运行摘要（JSON）：%s",
        json.dumps(result.schema(), ensure_ascii=False),
    )
    logger.info("─" * 60)
