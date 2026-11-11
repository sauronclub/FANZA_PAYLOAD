# -*- coding: utf-8 -*-
"""浏览器生命周期管理。

设计要点：
* 整个进程只启动一次浏览器，所有页面复用同一个上下文（共享 cookies，
  更贴近真实用户行为，也避免重复过年龄验证）；
* 每个页面单独开一个 Page，用完即关；
* 浏览器启动参数针对无显示的 Linux VPS 做了适配；
* 关闭过程容错，任一步失败都不阻断其余清理动作。
"""

from __future__ import annotations

from typing import Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from ..core.constants import (
    DEFAULT_LOCALE,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    DEFAULT_TIMEZONE,
    DEFAULT_USER_AGENT,
    DEFAULT_VIEWPORT,
)
from ..core.exceptions import BrowserError
from ..core.settings import Settings
from ..logkit import get_logger

# 无显示环境下常用的启动参数
_LAUNCH_ARGS: tuple[str, ...] = (
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
)


class BrowserManager:
    """浏览器资源管理器（支持 with 语句）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = get_logger("browser.manager")
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    # ── 生命周期 ──────────────────────────────────────────────
    def start(self) -> None:
        """启动浏览器并创建共享上下文。"""
        if self._context is not None:
            return
        try:
            self._playwright = sync_playwright().start()

            launch_kwargs: dict[str, object] = {
                "headless": self._settings.headless,
                "args": list(_LAUNCH_ARGS),
            }
            if self._settings.proxy:
                launch_kwargs["proxy"] = {"server": self._settings.proxy}
                self._logger.info("已启用代理：%s", self._settings.proxy)

            self._browser = self._playwright.chromium.launch(**launch_kwargs)  # type: ignore[arg-type]
            self._context = self._browser.new_context(
                viewport=DEFAULT_VIEWPORT,  # type: ignore[arg-type]
                user_agent=DEFAULT_USER_AGENT,
                locale=DEFAULT_LOCALE,
                timezone_id=DEFAULT_TIMEZONE,
            )
            self._context.set_default_timeout(DEFAULT_PAGE_LOAD_TIMEOUT_MS)
            self._logger.info(
                "浏览器已启动（无头模式=%s）", "是" if self._settings.headless else "否"
            )
        except Exception as exc:  # noqa: BLE001 - 统一包装为项目异常
            raise BrowserError(f"浏览器启动失败：{exc}") from exc

    def new_page(self) -> Page:
        """创建一个新的页面。"""
        if self._context is None:
            raise BrowserError("浏览器尚未启动，请先调用 start()")
        try:
            return self._context.new_page()
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(f"创建页面失败：{exc}") from exc

    def close(self) -> None:
        """释放全部浏览器资源（容错关闭）。"""
        for name, closer in (
            ("上下文", lambda: self._context and self._context.close()),
            ("浏览器", lambda: self._browser and self._browser.close()),
            ("Playwright", lambda: self._playwright and self._playwright.stop()),
        ):
            try:
                closer()
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("关闭%s时出现异常：%s", name, exc)
        self._context = None
        self._browser = None
        self._playwright = None
        self._logger.info("浏览器已关闭")

    # ── with 语句支持 ─────────────────────────────────────────
    def __enter__(self) -> "BrowserManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False
