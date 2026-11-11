# -*- coding: utf-8 -*-
"""GraphQL 请求监听器。

挂在 Playwright 的 Page 上，收集所有命中 GraphQL 端点的 POST 请求，
并按需检索目标 operationName。相比旧实现「命中即停」，
这里保留全部记录，从而支持同页多次请求（翻页、批量加载）不丢数据。
"""

from __future__ import annotations

from typing import Optional

from playwright.sync_api import Page, Request

from ..core.constants import IGNORED_OPERATIONS
from ..core.models import CapturedRequest
from ..logkit import get_logger
from .extractor import build_captured_request


class GraphQLListener:
    """页面级 GraphQL 请求收集器。"""

    def __init__(self, graphql_url: str) -> None:
        self._graphql_url = graphql_url
        self._logger = get_logger("capture.listener")
        self._records: list[CapturedRequest] = []
        self._seen_operations: list[str] = []

    # ── 挂载 / 卸载 ───────────────────────────────────────────
    def attach(self, page: Page) -> None:
        """开始监听指定页面的请求。"""
        self.reset()
        page.on("request", self._on_request)

    def detach(self, page: Page) -> None:
        """停止监听（容错，页面已关闭时忽略异常）。"""
        try:
            page.remove_listener("request", self._on_request)
        except Exception:  # noqa: BLE001 - 页面可能已关闭
            self._logger.debug("移除请求监听时页面已不可用，忽略")

    def reset(self) -> None:
        """清空已收集的记录。"""
        self._records.clear()
        self._seen_operations.clear()

    # ── 内部回调 ──────────────────────────────────────────────
    def _on_request(self, request: Request) -> None:
        if request.method != "POST":
            return
        if self._graphql_url not in request.url:
            return

        captured = build_captured_request(request)
        if captured is None:
            return

        self._records.append(captured)
        if captured.operation_name not in self._seen_operations:
            self._seen_operations.append(captured.operation_name)

        if captured.operation_name not in IGNORED_OPERATIONS:
            self._logger.debug(
                "捕获 GraphQL 请求：%s（累计 %d 条）",
                captured.operation_name,
                len(self._records),
            )

    # ── 查询接口 ──────────────────────────────────────────────
    @property
    def records(self) -> list[CapturedRequest]:
        return list(self._records)

    @property
    def seen_operations(self) -> list[str]:
        """本页出现过的全部 operationName（按首次出现顺序）。"""
        return list(self._seen_operations)

    @property
    def business_operations(self) -> list[str]:
        """过滤掉辅助 operation 后的列表，便于日志展示。"""
        return [op for op in self._seen_operations if op not in IGNORED_OPERATIONS]

    def find_all(self, operation_name: str) -> list[CapturedRequest]:
        """取出指定 operationName 的全部记录。"""
        return [r for r in self._records if r.operation_name == operation_name]

    def first(self, operation_name: str) -> Optional[CapturedRequest]:
        """取出指定 operationName 的第一条记录。"""
        for record in self._records:
            if record.operation_name == operation_name:
                return record
        return None
