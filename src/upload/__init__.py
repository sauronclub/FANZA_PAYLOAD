# -*- coding: utf-8 -*-
"""上传层：把本地捕获结果送到对象存储（Cloudflare R2）。

对外提供三层能力：

* :class:`R2Client`   —— 底层 S3 兼容客户端（运维脚本 / 自检也用它）；
* :class:`R2Uploader` —— 面向主流程的批量上传器；
* :mod:`src.upload.sigv4` —— 纯标准库的 AWS SigV4 签名（无第三方依赖）。
"""

from __future__ import annotations

from .base import (  # noqa: F401
    NullUploader,
    UploadBatch,
    UploadItem,
    UploadOutcome,
    Uploader,
)
from .r2 import R2Client, R2Uploader, build_uploader  # noqa: F401

__all__ = [
    "NullUploader",
    "R2Client",
    "R2Uploader",
    "UploadBatch",
    "UploadItem",
    "UploadOutcome",
    "Uploader",
    "build_uploader",
]
