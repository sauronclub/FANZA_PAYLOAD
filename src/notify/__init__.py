# -*- coding: utf-8 -*-
"""通知层：运行结果对外推送。"""

from __future__ import annotations

from .base import Notifier, NullNotifier  # noqa: F401
from .feishu import FeishuNotifier, build_notifier  # noqa: F401

__all__ = ["FeishuNotifier", "Notifier", "NullNotifier", "build_notifier"]
