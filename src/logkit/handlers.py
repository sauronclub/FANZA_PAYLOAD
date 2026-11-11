# -*- coding: utf-8 -*-
"""自定义日志处理器。

标准库自带的 `TimedRotatingFileHandler` 只按时间滚动、
`RotatingFileHandler` 只按大小滚动，都无法满足
「按天滚动 + 单文件大小上限 + 超期自动清理」的组合需求，
因此这里实现一个组合策略的处理器。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Optional

# when 取值 -> 归档文件的时间戳格式
_ROLLOVER_PATTERNS: dict[str, str] = {
    "midnight": "%Y-%m-%d",
    "daily": "%Y-%m-%d",
    "hourly": "%Y-%m-%d_%H",
}

_SECONDS_PER_DAY = 86_400


class DailySizeRotatingFileHandler(logging.FileHandler):
    """按天 + 按大小滚动的文件日志处理器。

    滚动规则：
      * 日期发生变化（跨天/跨小时，取决于 ``when``）时滚动；
      * 当前文件超过 ``max_bytes`` 时立即滚动；
      * 归档命名 ``<basename>.<时间戳>``，同一时间戳重复滚动时追加 ``.1``、``.2``；
      * 每次滚动后按 ``retention_days`` 清理过期归档（依据文件修改时间）。
    """

    def __init__(
        self,
        filename: str,
        when: str = "midnight",
        max_bytes: int = 10 * 1024 * 1024,
        retention_days: int = 30,
        encoding: str = "utf-8",
        delay: bool = False,
    ) -> None:
        if when not in _ROLLOVER_PATTERNS:
            raise ValueError(
                f"不支持的 when 取值：{when!r}（可选：{', '.join(_ROLLOVER_PATTERNS)}）"
            )
        # 这些属性需在 super().__init__ 之前就绪，因为 _open() 可能被提前调用
        self.when = when
        self.max_bytes = max(0, int(max_bytes))
        self.retention_days = max(0, int(retention_days))
        self._current_stamp: Optional[str] = None

        super().__init__(filename, mode="a", encoding=encoding, delay=delay)

        self._current_stamp = self._stamp()
        self._purge_expired()

    # ── 内部工具 ──────────────────────────────────────────────
    def _stamp(self) -> str:
        """当前时间对应的归档时间戳。"""
        return datetime.now().strftime(_ROLLOVER_PATTERNS[self.when])

    def _should_rollover(self, msg_len: int) -> bool:
        """判断是否需要滚动。"""
        # 1) 跨天/跨小时
        if self._stamp() != self._current_stamp:
            return True
        # 2) 超过单文件上限
        if self.max_bytes > 0:
            try:
                if self.stream is None:
                    self.stream = self._open()
                self.stream.seek(0, os.SEEK_END)
                if self.stream.tell() + msg_len > self.max_bytes:
                    return True
            except (OSError, ValueError):
                # 取大小失败时不阻塞写日志
                return False
        return False

    def _next_archive_path(self) -> str:
        """计算本次滚动应写入的归档路径（避免覆盖同名归档）。"""
        base = self.baseFilename
        stamp = self._stamp()
        candidate = f"{base}.{stamp}"
        if not os.path.exists(candidate):
            return candidate
        index = 1
        while True:
            candidate = f"{base}.{stamp}.{index}"
            if not os.path.exists(candidate):
                return candidate
            index += 1

    def _perform_rollover(self) -> None:
        """执行一次滚动：关闭当前流 → 归档 → 重开 → 清理过期归档。"""
        # 注意：这里只关闭底层文件流，绝不能调用 self.close()，
        # 否则处理器会被标准库从内部注册表中移除而失效。
        if self.stream is not None:
            try:
                self.flush()
                self.stream.close()
            finally:
                self.stream = None

        if os.path.exists(self.baseFilename):
            try:
                os.replace(self.baseFilename, self._next_archive_path())
            except OSError:
                # 归档失败也不能影响正常写入
                pass

        self.stream = self._open()
        self._current_stamp = self._stamp()
        self._purge_expired()

    def _purge_expired(self) -> None:
        """删除超过保留期的归档文件。"""
        if self.retention_days <= 0:
            return
        cutoff = time.time() - self.retention_days * _SECONDS_PER_DAY
        directory = os.path.dirname(self.baseFilename) or "."
        prefix = os.path.basename(self.baseFilename) + "."
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if not entry.is_file() or not entry.name.startswith(prefix):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    os.remove(entry.path)
            except OSError:
                continue

    # ── 标准接口 ──────────────────────────────────────────────
    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            msg_len = len(self.format(record)) + len(getattr(self, "terminator", "\n"))
            if self._should_rollover(msg_len):
                with self.lock:
                    # 二次确认，避免多线程下重复滚动
                    if self._should_rollover(msg_len):
                        self._perform_rollover()
            super().emit(record)
        except Exception:  # noqa: BLE001 - 日志处理器不得向上抛异常
            self.handleError(record)
