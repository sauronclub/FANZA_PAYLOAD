# -*- coding: utf-8 -*-
"""请求提取：把 Playwright 的 Request 对象转换为结构化数据。

这里是「捕获完整性」的关键所在——历史上曾只保存
operationName / query / variables 三个字段而丢掉请求头，
本版本同时保存原始请求体与请求头，避免信息损失。

两处关键设计：

1. ``CapturedRequest.body`` 保存的是**服务端原样收到的请求体字典**，
   不做字段裁剪、不做重排。PAYLOAD 文件直接写它，因此今后服务端新增任何
   顶层字段（如 extensions、persistedQuery 等）都会被自动保留，不存在漏参风险。

2. 请求头使用 ``request.all_headers()`` 而非 ``request.headers``。
   后者只返回 Playwright 认可的「常规」头（约 9 个），会**丢掉 cookie、
   origin、accept-encoding 等**；而站点真正用于识别会话的正是 cookie。
   实测同一批页面里，只有 cookie 会随会话状态变化，其余头都是浏览器级常量。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from playwright.sync_api import Request

from ..core.constants import GRAPHQL_BODY_FIELDS, HTTP2_PSEUDO_HEADER_PREFIX
from ..core.models import CapturedRequest
from ..logkit import get_logger

_logger = get_logger("capture.extractor")


def _normalize_headers(raw: Any) -> dict[str, str]:
    """把请求头规整为 ``{str: str}`` 字典，并剔除 HTTP/2 伪头。

    以 ``:`` 开头的键（``:authority`` / ``:method`` / ``:path`` / ``:scheme``）
    是 HTTP/2 帧字段而非 HTTP 头，重放时由客户端自行生成，因此丢弃；
    其余（含 cookie、origin、accept-encoding 等）一律原样保留。
    """
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if not str(key).startswith(HTTP2_PSEUDO_HEADER_PREFIX)
    }


def _read_headers(request: Request) -> dict[str, str]:
    """读取完整请求头，失败时退回常规头，保证捕获不中断。"""
    try:
        return _normalize_headers(request.all_headers())
    except Exception as exc:  # noqa: BLE001 - 读取头失败不应导致整页捕获失败
        _logger.warning("读取完整请求头失败，退回常规头：%s", exc)
        return _normalize_headers(request.headers)


def build_captured_request(request: Request) -> Optional[CapturedRequest]:
    """从请求对象提取载荷。

    :return: 提取成功返回 :class:`CapturedRequest`；非 POST、无 body、
             或 body 非法（无 operationName）时返回 None
    """
    if request.method != "POST":
        return None

    raw_body = request.post_data
    if not raw_body:
        return None

    try:
        body = json.loads(raw_body)
    except (ValueError, TypeError):
        _logger.debug("请求体不是合法 JSON，已跳过：%s", request.url)
        return None

    if not isinstance(body, dict):
        _logger.debug("请求体不是 JSON 对象，已跳过：%s", request.url)
        return None

    operation_name = body.get("operationName")
    if not isinstance(operation_name, str) or not operation_name:
        _logger.debug("请求体缺少 operationName，已跳过：%s", request.url)
        return None

    variables = body.get("variables")
    if not isinstance(variables, dict):
        variables = {}

    # 记录实际出现过的顶层字段，便于持续确认捕获完整性
    extra_fields = [key for key in body if key not in GRAPHQL_BODY_FIELDS]
    if extra_fields:
        _logger.info(
            "operation %s 的请求体出现额外字段：%s（已原样保留，无需改代码）",
            operation_name,
            "、".join(extra_fields),
        )

    return CapturedRequest(
        url=request.url,
        operation_name=operation_name,
        query=body.get("query") or "",
        variables=variables,
        headers=_read_headers(request),
        body=dict(body),
        method=request.method,
    )
