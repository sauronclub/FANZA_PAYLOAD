# -*- coding: utf-8 -*-
"""数据模型。

用不可变数据类描述「页面定义」「捕获到的请求」「单页结果」「整轮结果」，
让各层之间只通过明确的数据结构传递信息，避免裸露 dict。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .constants import PAYLOAD_SCHEMA_VERSION


def now_iso() -> str:
    """返回带时区的当前时间（ISO 8601，秒级）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def one_line(text: Optional[str], limit: int = 200) -> str:
    """把可能多行的异常信息压成单行，并限制长度。

    第三方库（如 Playwright）的异常常带多行提示框，
    直接写进日志与通知会严重干扰阅读，这里统一收敛。
    """
    if not text:
        return ""
    collapsed = " ".join(str(text).split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return collapsed


@dataclass(frozen=True)
class PageSpec:
    """一个待捕获页面的定义（来自 config/pages.py）。"""

    name: str
    url: str
    operation_name: str
    output: str
    enabled: bool = True
    tags: tuple[str, ...] = ()
    description: str = ""
    settle_ms: Optional[int] = None
    timeout_ms: Optional[int] = None
    url_env: Optional[str] = None
    # 请求头输出文件名；为空时由 output 自动推导（PAYLOAD_X.json -> HEADERS_X.json）
    headers_output: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - 仅用于日志
        return f"{self.name}({self.operation_name})"


@dataclass
class CapturedRequest:
    """一次被捕获的 GraphQL 请求。"""

    url: str
    operation_name: str
    query: str
    variables: dict[str, Any]
    headers: dict[str, str]
    # 与服务端实际收到的请求体完全一致（原样保存，不做任何裁剪或重排）。
    # 这是「不漏参数」的结构性保证：服务端将来新增任何顶层字段都会被自动保留。
    body: dict[str, Any]
    method: str = "POST"
    received_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """返回原始请求体 —— 即 PAYLOAD 文件要写入的内容。"""
        return self.body


@dataclass
class PageResult:
    """单个页面的捕获结果。"""

    page_name: str
    source_url: str
    success: bool
    attempts: int = 0
    duration_s: float = 0.0
    captured: Optional[CapturedRequest] = None
    extra_requests: list[CapturedRequest] = field(default_factory=list)
    output_path: Optional[str] = None
    headers_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def request_count(self) -> int:
        """该页捕获到的目标请求总数（主请求 + 额外请求）。"""
        return (1 if self.captured else 0) + len(self.extra_requests)


@dataclass
class RunResult:
    """整轮运行的结果汇总。"""

    run_id: str
    started_at: datetime
    pages: list[PageResult] = field(default_factory=list)
    finished_at: Optional[datetime] = None

    # ── 上传统计（未启用对象存储时保持默认值）──────────────────
    uploaded_files: int = 0
    uploaded_bytes: int = 0
    skipped_uploads: int = 0
    failed_uploads: list[str] = field(default_factory=list)

    # ── 统计属性 ──────────────────────────────────────────────
    @property
    def total(self) -> int:
        return len(self.pages)

    @property
    def succeeded(self) -> int:
        return sum(1 for p in self.pages if p.success)

    @property
    def failed(self) -> int:
        return sum(1 for p in self.pages if not p.success)

    @property
    def duration_s(self) -> float:
        if self.finished_at is None:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def failed_pages(self) -> list[PageResult]:
        return [p for p in self.pages if not p.success]

    @property
    def ok(self) -> bool:
        """是否全部成功。"""
        return self.failed == 0

    def summary_text(self) -> str:
        """生成用于日志/通知的多行中文摘要。"""
        lines = [
            f"运行 ID：{self.run_id}",
            f"结果：成功 {self.succeeded} / 共 {self.total}，失败 {self.failed}",
            f"耗时：{self.duration_s:.1f} 秒",
        ]
        if self.uploaded_files or self.skipped_uploads or self.failed_uploads:
            lines.append(
                f"云端上传：成功 {self.uploaded_files} 个"
                f"（{self.uploaded_bytes / 1024:.1f} KB），失败 {len(self.failed_uploads)} 个"
            )
            if self.skipped_uploads:
                lines.append(f"  · 未启用上传，跳过 {self.skipped_uploads} 个文件")
            for key in self.failed_uploads:
                lines.append(f"  · 上传失败：{key}")
        if self.failed_pages:
            lines.append("失败页面：")
            for p in self.failed_pages:
                lines.append(f"  · {p.page_name}：{one_line(p.error) or '未知原因'}")
        return "\n".join(lines)

    def schema(self) -> dict[str, Any]:
        """运行摘要的结构化形式。"""
        return {
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": (
                self.finished_at.isoformat(timespec="seconds")
                if self.finished_at
                else None
            ),
            "duration_s": round(self.duration_s, 2),
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "upload": {
                "uploaded": self.uploaded_files,
                "uploaded_bytes": self.uploaded_bytes,
                "skipped": self.skipped_uploads,
                "failed": len(self.failed_uploads),
                "failed_keys": self.failed_uploads,
            },
            "pages": [
                {
                    "page": p.page_name,
                    "url": p.source_url,
                    "success": p.success,
                    "attempts": p.attempts,
                    "duration_s": round(p.duration_s, 2),
                    "request_count": p.request_count,
                    "output": p.output_path,
                    "headers": p.headers_path,
                    "error": one_line(p.error, limit=500) or None,
                }
                for p in self.pages
            ],
        }
