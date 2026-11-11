# -*- coding: utf-8 -*-
"""单页捕获编排。

流程：附加监听 → 导航 → 越过年龄验证 → 轮询等待目标 operationName
→ 额外等待（收集同页后续请求）→ 卸载监听 → 返回结果。

关键实现细节：
Playwright 同步 API 的事件回调只在「执行 Playwright 调用」时被派发，
因此轮询必须使用 ``page.wait_for_timeout()`` 而不能用 ``time.sleep()``，
否则网络事件不会被处理、监听器永远收不到请求。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ..browser.age_gate import AgeGateHandler
from ..core.constants import DEFAULT_PAGE_LOAD_TIMEOUT_MS
from ..core.exceptions import CaptureError, CaptureTimeoutError
from ..core.models import CapturedRequest, PageSpec
from ..logkit import get_logger
from .listener import GraphQLListener

_POLL_INTERVAL_MS = 250


@dataclass
class CaptureOutcome:
    """单页捕获结果。"""

    captured: CapturedRequest
    extras: list[CapturedRequest] = field(default_factory=list)
    seen_operations: list[str] = field(default_factory=list)
    age_gate_passed: bool = True

    @property
    def total(self) -> int:
        return 1 + len(self.extras)


class PageCapturer:
    """负责单个页面的捕获流程。"""

    def __init__(
        self,
        graphql_url: str,
        age_gate: AgeGateHandler,
        load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    ) -> None:
        self._graphql_url = graphql_url
        self._age_gate = age_gate
        self._load_timeout_ms = load_timeout_ms
        self._logger = get_logger("capture.page_capturer")

    def capture(
        self,
        page: Page,
        spec: PageSpec,
        *,
        wait_ms: int,
        settle_ms: int,
    ) -> CaptureOutcome:
        """捕获指定页面的目标 GraphQL 请求。

        :raises CaptureError: 导航失败
        :raises CaptureTimeoutError: 超时未捕获到目标 operationName
        """
        listener = GraphQLListener(self._graphql_url)
        listener.attach(page)
        records: list[CapturedRequest] = []
        age_gate_passed = True

        try:
            self._logger.debug("导航至页面：%s", spec.url)
            try:
                page.goto(
                    spec.url,
                    wait_until="domcontentloaded",
                    timeout=self._load_timeout_ms,
                )
            except PlaywrightError as exc:
                raise CaptureError(f"页面导航失败：{exc}") from exc

            age_gate_passed = self._age_gate.ensure_passed(page)
            if not age_gate_passed:
                self._logger.warning("页面 %s 未能越过年龄验证，继续尝试捕获", spec.name)

            self._wait_for_operation(page, listener, spec.operation_name, wait_ms)

            records = listener.find_all(spec.operation_name)
            if records and settle_ms > 0:
                # 额外等待，尽量把同页触发的后续同类请求也收进来
                try:
                    page.wait_for_timeout(settle_ms)
                except PlaywrightError:
                    pass
                records = listener.find_all(spec.operation_name)

            seen_operations = listener.seen_operations
        finally:
            listener.detach(page)

        if not records:
            raise CaptureTimeoutError(
                f"等待 {wait_ms / 1000:.0f} 秒仍未捕获到 {spec.operation_name}"
                f"（本页出现的 operation：{'、'.join(listener.business_operations) or '无'}）"
            )

        if len(records) > 1:
            self._logger.info(
                "本页 %s 共触发 %d 次（已全部保留）", spec.operation_name, len(records)
            )

        return CaptureOutcome(
            captured=records[0],
            extras=records[1:],
            seen_operations=seen_operations,
            age_gate_passed=age_gate_passed,
        )

    # ── 内部方法 ──────────────────────────────────────────────
    def _wait_for_operation(
        self,
        page: Page,
        listener: GraphQLListener,
        operation_name: str,
        wait_ms: int,
    ) -> None:
        """轮询等待目标 operationName 出现。"""
        deadline = time.monotonic() + wait_ms / 1000.0
        waited = 0.0
        while time.monotonic() < deadline:
            if listener.find_all(operation_name):
                self._logger.debug(
                    "已捕获目标请求 %s（等待 %.1f 秒）", operation_name, waited
                )
                return
            try:
                page.wait_for_timeout(_POLL_INTERVAL_MS)
            except PlaywrightError as exc:
                self._logger.debug("轮询期间页面不可用：%s", exc)
                return
            waited += _POLL_INTERVAL_MS / 1000.0

        # 超时由调用方根据 records 判定，这里只记录现场信息
        self._logger.warning(
            "等待 %s 超时；本页已出现的业务 operation：%s",
            operation_name,
            "、".join(listener.business_operations) or "无",
        )
