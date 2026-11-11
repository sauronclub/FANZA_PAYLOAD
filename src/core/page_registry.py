# -*- coding: utf-8 -*-
"""页面清单加载与校验（config/pages.py）。

职责：
* 加载 Python 配置模块并取出 ``PAGES`` 列表；
* 逐条校验字段完整性、类型正确性、url / url_env 二选一；
* 校验 name 与 output 全局唯一；
* 输出不可变的 :class:`PageSpec` 列表。

配置本身是 Python 文件，写错字段名 / 类型会在启动时立刻报错，
不会带着错误配置跑一半才失败。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .exceptions import ConfigError
from .models import PageSpec
from .pyconfig import load_config_attr

PAGES_FILENAME = "pages.py"
PAGES_ATTR = "PAGES"
_CONFIG_MODULE_NAME = "_fanza_config_pages"

# 每条页面记录允许出现的字段，出现未知字段时报错（多半是拼写错误）
_ALLOWED_FIELDS = {
    "name",
    "url",
    "url_env",
    "operation_name",
    "output",
    "headers_output",
    "enabled",
    "tags",
    "description",
    "settle_ms",
    "timeout_ms",
}


def _require_str(item: dict[str, Any], key: str, idx: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"pages.py 第 {idx} 条记录缺少有效字段 `{key}`")
    return value.strip()


def _parse_page(item: Any, idx: int) -> PageSpec:
    if not isinstance(item, dict):
        raise ConfigError(f"pages.py 第 {idx} 条记录应为字典（dict）结构")

    unknown = set(item) - _ALLOWED_FIELDS
    if unknown:
        raise ConfigError(
            f"pages.py 第 {idx} 条记录出现未知字段：{'、'.join(sorted(unknown))}"
            f"（允许的字段：{'、'.join(sorted(_ALLOWED_FIELDS))}）"
        )

    name = _require_str(item, "name", idx)
    operation_name = _require_str(item, "operation_name", idx)
    output = _require_str(item, "output", idx)

    # url 与 url_env 必须且只能有一个
    url_literal = item.get("url")
    url_env = item.get("url_env")
    has_literal = isinstance(url_literal, str) and url_literal.strip()
    has_env = isinstance(url_env, str) and url_env.strip()
    if has_literal and has_env:
        raise ConfigError(f"[{name}] 只能设置 url 或 url_env 中的一个")
    if not has_literal and not has_env:
        raise ConfigError(f"[{name}] 必须设置 url 或 url_env 中的一个")

    if has_literal:
        url = url_literal.strip()
    else:
        env_key = url_env.strip()
        url = (os.getenv(env_key) or "").strip()
        if not url:
            raise ConfigError(f"[{name}] url_env={env_key} 指向的环境变量为空或未设置")

    tags_raw = item.get("tags") or []
    if not isinstance(tags_raw, list) or any(not isinstance(t, str) for t in tags_raw):
        raise ConfigError(f"[{name}] tags 应为字符串列表")
    tags = tuple(t.strip() for t in tags_raw if t.strip())

    enabled_raw = item.get("enabled", True)
    if not isinstance(enabled_raw, bool):
        raise ConfigError(f"[{name}] enabled 应为布尔值（True / False）")

    def _opt_int(key: str) -> int | None:
        value = item.get(key)
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigError(f"[{name}] {key} 应为正整数")
        return value

    def _opt_str(key: str) -> str | None:
        value = item.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"[{name}] {key} 应为非空字符串")
        return value.strip()

    return PageSpec(
        name=name,
        url=url,
        operation_name=operation_name,
        output=output,
        enabled=enabled_raw,
        tags=tags,
        description=str(item.get("description") or "").strip(),
        settle_ms=_opt_int("settle_ms"),
        timeout_ms=_opt_int("timeout_ms"),
        url_env=_opt_str("url_env"),
        headers_output=_opt_str("headers_output"),
    )


def _validate_unique(specs: list[PageSpec]) -> None:
    seen_names: set[str] = set()
    seen_outputs: set[str] = set()
    for spec in specs:
        if spec.name in seen_names:
            raise ConfigError(f"页面 name 重复：{spec.name}")
        seen_names.add(spec.name)
        if spec.output in seen_outputs:
            raise ConfigError(f"输出文件名重复：{spec.output}（页面 {spec.name}）")
        seen_outputs.add(spec.output)


def load_pages(config_dir: Path) -> list[PageSpec]:
    """加载并校验页面清单。

    :param config_dir: 存放 pages.py 的目录
    :return: 页面定义列表（保持配置中的顺序）
    """
    path = config_dir / PAGES_FILENAME
    raw = load_config_attr(path, _CONFIG_MODULE_NAME, PAGES_ATTR)

    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{PAGES_FILENAME} 中的 `{PAGES_ATTR}` 必须是非空列表")

    specs = [_parse_page(item, idx) for idx, item in enumerate(raw, start=1)]
    _validate_unique(specs)
    return specs
