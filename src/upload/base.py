# -*- coding: utf-8 -*-
"""上传接口定义。

所有对象存储实现 :class:`Uploader`；未配置存储时使用
:class:`NullUploader`，调用方无需做空判断。

设计原则：**上传失败绝不影响本地结果**。本地文件已经原子落盘，
上传只是「再送一份到云端」，任何异常都被收敛成 :class:`UploadOutcome`
中的失败记录，交由编排层汇总后写入日志与通知。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class UploadItem:
    """一个待上传的文件。

    :param local_path: 本地文件路径
    :param remote_key: 对象存储中的键名（不含桶名）
    """

    local_path: Path
    remote_key: str


@dataclass
class UploadOutcome:
    """单个文件的上传结果。"""

    remote_key: str
    success: bool
    size_bytes: int = 0
    error: Optional[str] = None
    skipped: bool = False


@dataclass
class UploadBatch:
    """一批上传的汇总结果。"""

    outcomes: list[UploadOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def succeeded(self) -> int:
        return sum(1 for o in self.outcomes if o.success and not o.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if not o.success and not o.skipped)

    @property
    def uploaded_bytes(self) -> int:
        return sum(o.size_bytes for o in self.outcomes if o.success and not o.skipped)

    @property
    def failed_keys(self) -> list[str]:
        return [o.remote_key for o in self.outcomes if not o.success and not o.skipped]


class Uploader(ABC):
    """对象存储上传器抽象基类。"""

    @property
    def enabled(self) -> bool:
        """是否真正启用（未启用时调用方可直接跳过）。"""
        return True

    @abstractmethod
    def upload_many(self, items: Iterable[UploadItem]) -> UploadBatch:
        """批量上传，逐个返回结果，不抛异常。"""


class NullUploader(Uploader):
    """空实现：未配置对象存储时使用。"""

    @property
    def enabled(self) -> bool:  # noqa: D102
        return False

    def upload_many(self, items: Iterable[UploadItem]) -> UploadBatch:  # noqa: D102
        return UploadBatch(
            outcomes=[
                UploadOutcome(remote_key=item.remote_key, success=False, skipped=True)
                for item in items
            ]
        )
