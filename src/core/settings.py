# -*- coding: utf-8 -*-
"""运行期设置：读取 .env 并做校验。

原则：
* 只负责「环境相关 / 私密」配置；页面清单交给 config/pages.py。
* 缺失必填项直接抛 :class:`ConfigError`，绝不在运行中途才发现问题。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .constants import DEFAULT_MAX_RETRY
from .exceptions import ConfigError

# 项目根目录：本文件位于 <root>/src/core/settings.py
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}


def _as_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _as_int(raw: Optional[str], default: int) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"配置项需要整数，实际为：{raw!r}") from exc


def _resolve_r2_endpoint() -> str:
    """解析 R2 的 S3 端点地址。

    优先使用 ``R2_ENDPOINT``（可直接填自定义或区域端点）；
    未填时用 ``R2_ACCOUNT_ID`` 拼出官方端点
    ``https://<account_id>.r2.cloudflarestorage.com``。
    """
    explicit = os.getenv("R2_ENDPOINT", "").strip()
    if explicit:
        return explicit.rstrip("/")
    account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
    if account_id:
        return f"https://{account_id}.r2.cloudflarestorage.com"
    return ""


@dataclass(frozen=True)
class Settings:
    """一次运行所依赖的全部环境配置。"""

    project_root: Path
    config_dir: Path
    payload_dir: Path
    headers_dir: Path
    logs_dir: Path

    graphql_api_url: str
    feishu_webhook_url: str
    feishu_sign_secret: str

    # ── Cloudflare R2（S3 兼容）──────────────────────────────
    r2_endpoint_url: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket: str
    r2_prefix: str

    headless: bool
    proxy: Optional[str]
    page_wait_seconds: int
    max_retry: int
    log_level: Optional[str]

    def validate(self) -> None:
        """校验必填项，不通过则抛异常。"""
        missing: list[str] = []
        if not self.graphql_api_url:
            missing.append("GRAPHQL_API_URL")
        if missing:
            raise ConfigError(
                "缺少必要的环境变量：" + "、".join(missing) + "（请检查 .env 文件）"
            )

        # R2 允许完全留空（表示不上传）；但不允许只填一半——
        # 半套配置会让「以为在上传、实际静默跳过」这种问题很难排查。
        if self.r2_partial:
            filled = [name for name, value in self._r2_fields().items() if value]
            raise ConfigError(
                "R2 配置不完整，已填写的项："
                + "、".join(filled)
                + "。请补齐 R2_ACCOUNT_ID（或 R2_ENDPOINT）、R2_BUCKET、"
                "R2_ACCESS_KEY_ID、R2_SECRET_ACCESS_KEY；"
                "或把这四项全部留空以关闭上传。"
            )

    def _r2_fields(self) -> dict[str, Optional[str]]:
        """R2 各项配置的当前取值，用于判断「未配置 / 已配置 / 配置一半」。"""
        return {
            "R2_ENDPOINT": self.r2_endpoint_url or None,
            "R2_BUCKET": self.r2_bucket or None,
            "R2_ACCESS_KEY_ID": self.r2_access_key_id or None,
            "R2_SECRET_ACCESS_KEY": self.r2_secret_access_key or None,
        }

    @property
    def r2_partial(self) -> bool:
        """是否处于「填了一部分但不足以工作」的状态。"""
        filled = [v for v in self._r2_fields().values() if v]
        if not filled:
            return False  # 完全没填 —— 视为主动关闭上传
        return not self.upload_enabled

    @property
    def notify_enabled(self) -> bool:
        return bool(self.feishu_webhook_url)

    @property
    def upload_enabled(self) -> bool:
        """是否启用对象存储上传。"""
        return bool(
            self.r2_endpoint_url
            and self.r2_bucket
            and self.r2_access_key_id
            and self.r2_secret_access_key
        )


def load_settings(
    project_root: Optional[Path] = None,
    env_file: Optional[Path] = None,
) -> Settings:
    """加载 .env 并构造 :class:`Settings`。

    :param project_root: 项目根目录，默认取本文件上溯两级
    :param env_file: 指定 .env 路径，默认取根目录下的 .env
    """
    root = (project_root or PROJECT_ROOT).resolve()
    dotenv_path = env_file or (root / ".env")
    if dotenv_path.exists():
        # override=False：真实环境变量优先于 .env，便于在 VPS 上临时覆盖
        load_dotenv(dotenv_path=dotenv_path, override=False)

    settings = Settings(
        project_root=root,
        config_dir=root / "config",
        payload_dir=root / "PAYLOAD",
        headers_dir=root / "HEADERS",
        logs_dir=root / "logs",
        graphql_api_url=os.getenv("GRAPHQL_API_URL", "").strip(),
        feishu_webhook_url=os.getenv("FEISHU_GROUP_BOT_WEBHOOK_URL", "").strip(),
        feishu_sign_secret=os.getenv("FEISHU_SIGN_SECRET", "").strip(),
        r2_endpoint_url=_resolve_r2_endpoint(),
        r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        r2_bucket=os.getenv("R2_BUCKET", "").strip(),
        r2_prefix=os.getenv("R2_PREFIX", "").strip().strip("/"),
        headless=_as_bool(os.getenv("BROWSER_HEADLESS"), default=True),
        proxy=(os.getenv("BROWSER_PROXY", "").strip() or None),
        page_wait_seconds=_as_int(os.getenv("PAGE_WAIT_SECONDS"), default=45),
        max_retry=_as_int(os.getenv("MAX_RETRY"), default=DEFAULT_MAX_RETRY),
        log_level=(os.getenv("LOG_LEVEL", "").strip() or None),
    )
    return settings
