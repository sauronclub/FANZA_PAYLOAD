# -*- coding: utf-8 -*-
"""FANZA GraphQL Payload 捕获器。

生产级重构版本：模块化分层，各层职责单一、可独立测试。

分层结构::

    src.core      基础设施（配置、模型、异常、常量）
    src.logkit    日志（分级、滚动、上下文注入）
    src.browser   浏览器生命周期与年龄验证
    src.capture   GraphQL 请求监听与提取
    src.storage   落盘（原子写、路径规划）
    src.notify    外部通知（飞书）
    src.runner    批量编排、重试与运行摘要
"""

from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["__version__"]
