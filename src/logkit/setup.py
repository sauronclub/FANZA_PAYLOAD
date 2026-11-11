# -*- coding: utf-8 -*-
"""日志初始化。

调用 config/logging.py 的 ``build_config(logs_dir, run_id)`` 拿到
dictConfig 配置字典后生效（配置文件是 Python 模块，改起来比 YAML 直观）。

级别分工：
  * 控制台 —— 面向人工观察，级别由配置文件的 CONSOLE_LEVEL 决定；
  * 日志文件 —— 面向事后排查，默认记录 DEBUG 及以上全量；
  * 控制台级别还可用 .env 的 LOG_LEVEL 或 --log-level 临时覆盖。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import logging.config

from ..core.exceptions import ConfigError
from ..core.pyconfig import load_config_attr

LOGGING_FILENAME = "logging.py"
LOGGING_BUILDER = "build_config"
_CONFIG_MODULE_NAME = "_fanza_config_logging"

_VALID_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}


def setup_logging(
    config_path: Path,
    logs_dir: Path,
    run_id: str,
    level_override: Optional[str] = None,
) -> None:
    """初始化全局日志配置。

    :param config_path: config/logging.py 路径
    :param logs_dir: 日志目录（会被自动创建）
    :param run_id: 本次运行的唯一 ID，会注入到每条日志
    :param level_override: 覆盖控制台日志级别（如 DEBUG）
    :raises ConfigError: 配置缺失、构建失败或级别非法
    """
    logs_dir.mkdir(parents=True, exist_ok=True)

    builder = load_config_attr(config_path, _CONFIG_MODULE_NAME, LOGGING_BUILDER)
    if not callable(builder):
        raise ConfigError(f"{config_path} 中的 `{LOGGING_BUILDER}` 必须是函数")

    try:
        config: Any = builder(logs_dir=logs_dir.as_posix(), run_id=run_id)
    except TypeError as exc:
        raise ConfigError(
            f"日志配置函数签名不正确，应形如 "
            f"`{LOGGING_BUILDER}(logs_dir: str, run_id: str) -> dict`：{exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 统一转为配置错误
        raise ConfigError(
            f"日志配置构建失败（{exc.__class__.__name__}: {exc}）"
        ) from exc

    if not isinstance(config, dict):
        raise ConfigError(f"{config_path} 的 `{LOGGING_BUILDER}` 必须返回字典")

    if level_override:
        level = str(level_override).strip().upper()
        if level not in _VALID_LEVELS:
            raise ConfigError(
                f"LOG_LEVEL 取值非法：{level_override!r}"
                f"（可选：{', '.join(sorted(_VALID_LEVELS))}）"
            )
        config.setdefault("handlers", {}).setdefault("console", {})["level"] = level

    try:
        logging.config.dictConfig(config)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ConfigError(f"日志配置生效失败：{exc}") from exc
