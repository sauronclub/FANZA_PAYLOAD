# -*- coding: utf-8 -*-
"""全局常量与默认值。

集中管理所有「魔法值」，避免散落在各模块中；
需要调整默认行为时只改这里。
"""

from __future__ import annotations

# ── GraphQL 请求体字段 ────────────────────────────────────────
# 捕获时需要保存的请求体顶层字段（顺序即输出顺序）
GRAPHQL_BODY_FIELDS: tuple[str, ...] = (
    "operationName",
    "query",
    "variables",
    "extensions",
)

# ── 请求头 ────────────────────────────────────────────────────
# HTTP/2 伪头（:authority / :method / :path / :scheme）。
# 它们由 HTTP/2 协议帧承载、由客户端自动生成，不是可重放的 HTTP 头，
# 保存请求头时统一剔除。
HTTP2_PSEUDO_HEADER_PREFIX: str = ":"

# ── 页面上的辅助 operation ────────────────────────────────────
# 这些请求每页都会发，但不属于采集目标，日志中忽略以免干扰
IGNORED_OPERATIONS: frozenset[str] = frozenset(
    {
        "LegacyGuestId",
        "Root",
        "Maintenance",
        "SideBar",
        "PromotionBanners",
        "RecentlyViewedContents",
    }
)

# ── 年龄验证 ──────────────────────────────────────────────────
AGE_CHECK_URL_MARKER: str = "age_check"
AGE_CHECK_TEXT_MARKER: str = "年齢認証"
AGE_CHECK_BUTTON_SELECTOR: str = 'a[href*="declared=yes"]'

# ── 默认超时与重试 ────────────────────────────────────────────
DEFAULT_PAGE_LOAD_TIMEOUT_MS: int = 60_000
DEFAULT_WAIT_GRAPHQL_MS: int = 45_000
DEFAULT_SETTLE_MS: int = 1_500
DEFAULT_MAX_RETRY: int = 3
DEFAULT_RETRY_INTERVAL_S: float = 5.0

# ── 浏览器 ────────────────────────────────────────────────────
DEFAULT_VIEWPORT: dict[str, int] = {"width": 1280, "height": 800}
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_LOCALE: str = "ja-JP"
DEFAULT_TIMEZONE: str = "Asia/Tokyo"

# ── 输出 ──────────────────────────────────────────────────────
# 运行摘要（写入日志的 JSON）的结构版本。
# 注意：PAYLOAD/ 下的负载文件是服务端原始请求体，不含版本号，
#       这里只用于标识「运行摘要」这一结构化日志的格式。
PAYLOAD_SCHEMA_VERSION: str = "2.0"
