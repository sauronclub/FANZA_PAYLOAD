# -*- coding: utf-8 -*-
"""存储层：输出路径规划与 JSON 落盘。"""

from __future__ import annotations

from .layout import (  # noqa: F401
    HEADERS_PREFIX,
    PAYLOAD_PREFIX,
    headers_output_name,
    numbered_name,
    resolve_headers_path,
    resolve_payload_path,
)
from .writer import write_json_atomic  # noqa: F401

__all__ = [
    "HEADERS_PREFIX",
    "PAYLOAD_PREFIX",
    "headers_output_name",
    "numbered_name",
    "resolve_headers_path",
    "resolve_payload_path",
    "write_json_atomic",
]
