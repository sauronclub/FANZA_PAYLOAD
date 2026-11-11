# -*- coding: utf-8 -*-
"""批量捕获编排器。

职责：
* 按页面清单顺序逐个捕获，单页失败按次数重试；
* 任一页面最终失败都不中断整体流程（保证其余页面照常产出）；
* 把结果分别写入 PAYLOAD/（纯净负载）与 HEADERS/（请求头）；
* 把本轮写出的文件推送到对象存储（Cloudflare R2）；
* 汇总运行结果并交给通知层。

上传策略：只上传**本轮实际写出**的文件，远端同名对象被覆盖，
因此云端始终保有每个页面的最新一版；上传失败只记录、不影响本地结果。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ..browser.age_gate import AgeGateHandler
from ..browser.manager import BrowserManager
from ..capture.page_capturer import CaptureOutcome, PageCapturer
from ..core.constants import (
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    DEFAULT_RETRY_INTERVAL_S,
    DEFAULT_SETTLE_MS,
)
from ..core.exceptions import BrowserError, CaptureError, FanzaPayloadError, StorageError
from ..core.models import PageResult, PageSpec, RunResult
from ..core.settings import Settings
from ..logkit import get_logger
from ..notify.base import Notifier
from ..storage.layout import numbered_name, resolve_headers_path, resolve_payload_path
from ..storage.writer import write_json_atomic
from ..upload.base import UploadItem, Uploader


class Orchestrator:
    """串行执行所有页面的捕获任务。"""

    def __init__(
        self,
        settings: Settings,
        pages: Iterable[PageSpec],
        notifier: Notifier,
        run_id: str,
        uploader: Uploader,
    ) -> None:
        self._settings = settings
        self._pages = list(pages)
        self._notifier = notifier
        self._run_id = run_id
        self._uploader = uploader
        self._logger = get_logger("runner.orchestrator")
        # 本轮实际写出的文件，运行结束后统一上传
        self._written_files: list[Path] = []

        self._age_gate = AgeGateHandler()
        self._capturer = PageCapturer(
            graphql_url=settings.graphql_api_url,
            age_gate=self._age_gate,
            load_timeout_ms=DEFAULT_PAGE_LOAD_TIMEOUT_MS,
        )

    # ── 对外入口 ──────────────────────────────────────────────
    def run(self) -> RunResult:
        """执行全部页面并返回运行结果。"""
        result = RunResult(
            run_id=self._run_id,
            started_at=datetime.now(timezone.utc).astimezone(),
        )
        enabled = [p for p in self._pages if p.enabled]
        skipped = [p for p in self._pages if not p.enabled]

        self._logger.info(
            "本次共 %d 个页面待捕获（另有 %d 个已停用）", len(enabled), len(skipped)
        )
        for page in skipped:
            self._logger.info("跳过已停用页面：%s", page.name)

        if not enabled:
            self._logger.warning("没有启用任何页面，本次不做任何捕获")
            result.finished_at = datetime.now(timezone.utc).astimezone()
            return result

        try:
            with BrowserManager(self._settings) as browser:
                for index, spec in enumerate(enabled, start=1):
                    self._logger.info(
                        "[%d/%d] 开始处理页面：%s", index, len(enabled), spec.name
                    )
                    page_result = self._capture_with_retry(browser, spec)
                    result.pages.append(page_result)
                    if page_result.success:
                        op_name = page_result.captured.operation_name if page_result.captured else "?"
                        if page_result.attempts > 1:
                            self._logger.info(
                                "[%d/%d] %s 第 %d 次尝试成功，已捕获目标请求（%s，共 %d 条），用时 %.1f 秒",
                                index,
                                len(enabled),
                                spec.name,
                                page_result.attempts,
                                op_name,
                                page_result.request_count,
                                page_result.duration_s,
                            )
                        else:
                            self._logger.info(
                                "[%d/%d] %s 完成，已捕获目标请求（%s），用时 %.1f 秒",
                                index,
                                len(enabled),
                                spec.name,
                                op_name,
                                page_result.duration_s,
                            )
                    else:
                        self._logger.error(
                            "[%d/%d] %s 失败：%s",
                            index,
                            len(enabled),
                            spec.name,
                            page_result.error,
                        )
        except BrowserError as exc:
            # 浏览器都起不来，属于致命错误，直接把所有页面标记为失败
            self._logger.critical("浏览器不可用，本次运行终止：%s", exc)
            for spec in enabled:
                if not any(p.page_name == spec.name for p in result.pages):
                    result.pages.append(
                        PageResult(
                            page_name=spec.name,
                            source_url=spec.url,
                            success=False,
                            error=f"浏览器不可用：{exc}",
                        )
                    )
        finally:
            result.finished_at = datetime.now(timezone.utc).astimezone()

        # 浏览器已关闭，此时再做网络上传，避免与抓取争抢资源
        self._upload_outputs(result)
        return result

    # ── 云端上传 ──────────────────────────────────────────────
    def _upload_outputs(self, result: RunResult) -> None:
        """把本轮写出的文件推送到对象存储，并回填统计到 ``result``。"""
        if not self._written_files:
            self._logger.info("本轮没有写出任何文件，跳过上传")
            return

        items = [
            UploadItem(local_path=path, remote_key=self._remote_key(path))
            for path in self._written_files
        ]

        if not self._uploader.enabled:
            # 区分两种「不上传」：本次被 --no-upload 关掉，还是压根没配置。
            # 文案准确与否直接影响运维排查（曾出现「以为没配，其实是本次跳过」）。
            reason = (
                "命令行指定 --no-upload"
                if self._settings.upload_enabled
                else "未配置对象存储"
            )
            self._logger.info(
                "%s，跳过上传（本地已保存 %d 个文件）", reason, len(items)
            )
            result.skipped_uploads = len(items)
            return

        self._logger.info("开始上传 %d 个文件到对象存储", len(items))
        batch = self._uploader.upload_many(items)
        result.uploaded_files = batch.succeeded
        result.uploaded_bytes = batch.uploaded_bytes
        result.skipped_uploads = batch.skipped
        result.failed_uploads = batch.failed_keys

        if batch.failed:
            self._logger.error(
                "上传完成：成功 %d 个，失败 %d 个（本地文件不受影响）",
                batch.succeeded,
                batch.failed,
            )
            for outcome in batch.outcomes:
                if not outcome.success and not outcome.skipped:
                    self._logger.error("  · %s：%s", outcome.remote_key, outcome.error)
        else:
            self._logger.info(
                "上传完成：%d 个文件全部成功（共 %.1f KB）",
                batch.succeeded,
                batch.uploaded_bytes / 1024,
            )

    def _remote_key(self, path: Path) -> str:
        """由本地路径推导对象键，保持 ``PAYLOAD/``、``HEADERS/`` 目录结构。"""
        try:
            relative = path.resolve().relative_to(self._settings.project_root)
        except ValueError:
            # 输出目录被配置到项目之外时，退化为只用文件名
            self._logger.debug("文件不在项目目录内，对象键仅取文件名：%s", path)
            return path.name
        return relative.as_posix()

    # ── 输出落盘 ──────────────────────────────────────────────
    def _write_outputs(self, spec: PageSpec, outcome: CaptureOutcome) -> tuple[Path, Path]:
        """写入负载文件与请求头文件，返回两者的路径。

        * ``PAYLOAD/<output>``     —— 服务端原始 GraphQL 请求体（纯净内容，无任何包装）
        * ``HEADERS/<headers 名>`` —— 该请求的请求头字典

        若同一页面内目标 operation 触发多次，第 2 条及之后另存为 ``__2``、``__3``
        文件：主文件名恒定不变（下游按固定名字读取不受影响），同时不丢数据。
        """
        payload_path = resolve_payload_path(self._settings.payload_dir, spec)
        headers_path = resolve_headers_path(self._settings.headers_dir, spec)
        write_json_atomic(payload_path, outcome.captured.body)
        write_json_atomic(headers_path, outcome.captured.headers)
        self._written_files.extend((payload_path, headers_path))

        for index, extra in enumerate(outcome.extras, start=2):
            extra_payload = self._settings.payload_dir / numbered_name(spec.output, index)
            extra_headers = self._settings.headers_dir / numbered_name(headers_path.name, index)
            write_json_atomic(extra_payload, extra.body)
            write_json_atomic(extra_headers, extra.headers)
            self._written_files.extend((extra_payload, extra_headers))
            self._logger.info(
                "%s 的第 %d 条请求另存为：%s", spec.name, index, extra_payload.name
            )

        return payload_path, headers_path

    # ── 单页重试 ──────────────────────────────────────────────
    def _capture_with_retry(self, browser: BrowserManager, spec: PageSpec) -> PageResult:
        """对单个页面执行捕获，失败按配置重试。"""
        max_attempt = max(1, self._settings.max_retry)
        started = time.monotonic()
        last_error = "未知错误"
        # 记录最终成功之前每次失败的原因，供摘要与通知展示
        retry_errors: list[str] = []

        wait_ms = spec.timeout_ms or self._settings.page_wait_seconds * 1000
        settle_ms = spec.settle_ms if spec.settle_ms is not None else DEFAULT_SETTLE_MS

        for attempt in range(1, max_attempt + 1):
            page = None
            try:
                page = browser.new_page()
                outcome = self._capturer.capture(
                    page, spec, wait_ms=wait_ms, settle_ms=settle_ms
                )

                payload_path, headers_path = self._write_outputs(spec, outcome)

                return PageResult(
                    page_name=spec.name,
                    source_url=spec.url,
                    success=True,
                    attempts=attempt,
                    duration_s=time.monotonic() - started,
                    captured=outcome.captured,
                    extra_requests=outcome.extras,
                    output_path=str(payload_path),
                    headers_path=str(headers_path),
                    retry_errors=retry_errors,
                )
            except (CaptureError, StorageError, FanzaPayloadError) as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"
                retry_errors.append(last_error)
                self._logger.warning(
                    "%s 第 %d/%d 次尝试失败：%s", spec.name, attempt, max_attempt, last_error
                )
            except Exception as exc:  # noqa: BLE001 - 兜底，避免单页异常中断整体
                last_error = f"{exc.__class__.__name__}: {exc}"
                retry_errors.append(last_error)
                self._logger.exception(
                    "%s 第 %d/%d 次尝试出现未预期异常", spec.name, attempt, max_attempt
                )
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        self._logger.debug("关闭页面失败，忽略")

            if attempt < max_attempt:
                time.sleep(DEFAULT_RETRY_INTERVAL_S)

        return PageResult(
            page_name=spec.name,
            source_url=spec.url,
            success=False,
            attempts=max_attempt,
            duration_s=time.monotonic() - started,
            error=last_error,
            retry_errors=retry_errors,
        )
