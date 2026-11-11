# -*- coding: utf-8 -*-
"""日志过滤器。

目前提供上下文注入：把 run_id 等字段写入每条日志记录，
使日志文件与通知中的记录可以按「同一次运行」聚合。
"""

from __future__ import annotations

import logging
from typing import Any, Optional


class ContextFilter(logging.Filter):
    """向日志记录注入固定上下文字段。

    在 config/logging.py 的 dictConfig 字典里通过 ``()`` 工厂方式声明::

        "filters": {
            "context": {
                "()": "src.logkit.filters.ContextFilter",
                "fields": {"run_id": "xxx"},
            },
        }
    """

    def __init__(
        self,
        fields: Optional[dict[str, Any]] = None,
        name: str = "",
    ) -> None:
        super().__init__(name)
        self._fields: dict[str, Any] = dict(fields or {})

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self._fields.items():
            setattr(record, key, value)
        return True
