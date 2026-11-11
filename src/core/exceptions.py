# -*- coding: utf-8 -*-
"""自定义异常体系。

所有异常都继承自 :class:`FanzaPayloadError`，便于调用方
按「是否本项目可控」统一处理；更细的子类用于精确分级捕获。
"""

from __future__ import annotations


class FanzaPayloadError(Exception):
    """本项目所有异常的基类。"""


class ConfigError(FanzaPayloadError):
    """配置缺失、格式错误或校验不通过。"""


class BrowserError(FanzaPayloadError):
    """浏览器启动、上下文创建或页面导航失败。"""


class CaptureError(FanzaPayloadError):
    """捕获流程出错。"""


class CaptureTimeoutError(CaptureError):
    """在超时时间内未捕获到目标 GraphQL 请求。"""


class StorageError(FanzaPayloadError):
    """文件落盘失败。"""


class NotifyError(FanzaPayloadError):
    """外部通知发送失败。"""


class UploadError(FanzaPayloadError):
    """对象存储上传失败。"""


class R2RequestError(UploadError):
    """调用 R2（S3 兼容接口）本身失败，如 403 签名错误、404 桶不存在。"""
