# -*- coding: utf-8 -*-
"""基础设施层：配置、数据模型、异常与常量。"""

from __future__ import annotations

from .constants import (  # noqa: F401
    AGE_CHECK_BUTTON_SELECTOR,
    AGE_CHECK_TEXT_MARKER,
    AGE_CHECK_URL_MARKER,
    DEFAULT_MAX_RETRY,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    DEFAULT_RETRY_INTERVAL_S,
    DEFAULT_SETTLE_MS,
    DEFAULT_USER_AGENT,
    DEFAULT_VIEWPORT,
    DEFAULT_WAIT_GRAPHQL_MS,
    GRAPHQL_BODY_FIELDS,
    IGNORED_OPERATIONS,
    PAYLOAD_SCHEMA_VERSION,
)
from .exceptions import (  # noqa: F401
    BrowserError,
    CaptureError,
    CaptureTimeoutError,
    ConfigError,
    FanzaPayloadError,
    NotifyError,
    StorageError,
)
from .models import (  # noqa: F401
    CapturedRequest,
    PageResult,
    PageSpec,
    RunResult,
)
from .page_registry import load_pages  # noqa: F401
from .settings import Settings, load_settings  # noqa: F401

__all__ = [
    "AGE_CHECK_BUTTON_SELECTOR",
    "AGE_CHECK_TEXT_MARKER",
    "AGE_CHECK_URL_MARKER",
    "BrowserError",
    "CapturedRequest",
    "CaptureError",
    "CaptureTimeoutError",
    "ConfigError",
    "DEFAULT_MAX_RETRY",
    "DEFAULT_PAGE_LOAD_TIMEOUT_MS",
    "DEFAULT_RETRY_INTERVAL_S",
    "DEFAULT_SETTLE_MS",
    "DEFAULT_USER_AGENT",
    "DEFAULT_VIEWPORT",
    "DEFAULT_WAIT_GRAPHQL_MS",
    "FanzaPayloadError",
    "GRAPHQL_BODY_FIELDS",
    "IGNORED_OPERATIONS",
    "NotifyError",
    "PAYLOAD_SCHEMA_VERSION",
    "PageResult",
    "PageSpec",
    "RunResult",
    "Settings",
    "StorageError",
    "load_pages",
    "load_settings",
]
