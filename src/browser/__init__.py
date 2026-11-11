# -*- coding: utf-8 -*-
"""浏览器层：负责 Playwright 浏览器/上下文的创建、复用与释放。"""

from __future__ import annotations

from .age_gate import AgeGateHandler  # noqa: F401
from .manager import BrowserManager  # noqa: F401

__all__ = ["AgeGateHandler", "BrowserManager"]
