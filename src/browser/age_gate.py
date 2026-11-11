# -*- coding: utf-8 -*-
"""FANZA 年龄验证（年齢認証）页面处理。

首次访问会跳到 `age_check` 页面，需要点击「はい（已满 18 岁）」链接
才能进入目标页。该状态以 cookie 形式保存在浏览器上下文中，
因此后续页面通常无需重复验证。
"""

from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from ..core.constants import (
    AGE_CHECK_BUTTON_SELECTOR,
    AGE_CHECK_TEXT_MARKER,
    AGE_CHECK_URL_MARKER,
)
from ..logkit import get_logger

_NAV_TIMEOUT_MS = 30_000


class AgeGateHandler:
    """年龄验证处理器。"""

    def __init__(self) -> None:
        self._logger = get_logger("browser.age_gate")

    @staticmethod
    def is_age_gate(page: Page) -> bool:
        """判断当前是否停留在年龄验证页。"""
        try:
            if AGE_CHECK_URL_MARKER in page.url.lower():
                return True
            return AGE_CHECK_TEXT_MARKER in page.title()
        except PlaywrightError:
            # 页面可能正在导航，取不到标题时按「非验证页」处理
            return False

    def ensure_passed(self, page: Page, retries: int = 2) -> bool:
        """确保已越过年龄验证。

        :return: True 表示当前已不在验证页
        """
        if not self.is_age_gate(page):
            return True

        self._logger.info("检测到年龄验证页面，尝试自动通过")
        for attempt in range(1, retries + 1):
            try:
                button = page.locator(AGE_CHECK_BUTTON_SELECTOR)
                if button.count() == 0:
                    self._logger.warning("第 %d 次尝试：未找到年龄验证按钮", attempt)
                    continue

                button.first.click()
                page.wait_for_load_state("domcontentloaded", timeout=_NAV_TIMEOUT_MS)
                if not self.is_age_gate(page):
                    self._logger.info("年龄验证已通过")
                    return True
                self._logger.warning("第 %d 次尝试后仍停留在验证页", attempt)
            except (PlaywrightTimeoutError, PlaywrightError) as exc:
                self._logger.warning("第 %d 次尝试处理验证页失败：%s", attempt, exc)

        still_blocked = self.is_age_gate(page)
        if still_blocked:
            self._logger.error("年龄验证未能通过，页面可能无法正常加载")
        return not still_blocked
