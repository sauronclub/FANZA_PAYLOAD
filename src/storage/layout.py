# -*- coding: utf-8 -*-
"""输出目录布局与文件命名。

目录职责（三者互不混杂）::

    PAYLOAD/  每个页面一个 JSON 文件，内容 = 服务端原始 GraphQL 请求体
              （顶层就是 operationName / query / variables，不做任何包装）
    HEADERS/  每个页面一个 JSON 文件，内容 = 该请求的请求头字典
    logs/     运行日志

命名规则：
    PAYLOAD_DAILY.json  ->  HEADERS_DAILY.json   （前缀 PAYLOAD_ 换成 HEADERS_）
    同一页面若目标 operation 触发多次，第 2 个及之后的文件追加 __2、__3 后缀，
    保证主文件名恒定不变，下游按固定文件名读取不受影响。
"""

from __future__ import annotations

from pathlib import Path

from ..core.models import PageSpec

# 输出文件名前缀
PAYLOAD_PREFIX = "PAYLOAD_"
HEADERS_PREFIX = "HEADERS_"


def headers_output_name(output: str) -> str:
    """由负载文件名推导请求头文件名。"""
    if output.startswith(PAYLOAD_PREFIX):
        return HEADERS_PREFIX + output[len(PAYLOAD_PREFIX) :]
    return HEADERS_PREFIX + output


def resolve_payload_path(payload_dir: Path, spec: PageSpec) -> Path:
    """负载文件路径（PAYLOAD/PAYLOAD_XXX.json）。"""
    return payload_dir / spec.output


def resolve_headers_path(headers_dir: Path, spec: PageSpec) -> Path:
    """请求头文件路径（HEADERS/HEADERS_XXX.json）。"""
    name = spec.headers_output or headers_output_name(spec.output)
    return headers_dir / name


def numbered_name(name: str, index: int) -> str:
    """给文件名追加序号：PAYLOAD_X.json -> PAYLOAD_X__2.json。"""
    path = Path(name)
    return f"{path.stem}__{index}{path.suffix}"
