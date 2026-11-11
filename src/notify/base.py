# -*- coding: utf-8 -*-
"""通知接口定义。

所有通知渠道实现 :class:`Notifier`；未配置渠道时使用
:class:`NullNotifier`，调用方无需做空判断。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.models import RunResult


class Notifier(ABC):
    """通知渠道抽象基类。"""

    @abstractmethod
    def send_run_summary(self, result: RunResult) -> None:
        """推送一次运行摘要。

        :raises NotifyError: 发送失败（调用方应捕获且不影响主流程）
        """


class NullNotifier(Notifier):
    """空实现：未配置任何通知渠道时使用。"""

    def send_run_summary(self, result: RunResult) -> None:  # noqa: D102
        return None
