# -*- coding: utf-8 -*-
"""Python 配置模块加载器。

项目把原本的 YAML 配置换成了 .py 配置（config/pages.py、config/logging.py），
理由是：可读性更好、编辑器能直接做语法检查、并且不引入 PyYAML 依赖。

安全加载要点
------------
* 按「文件路径」加载，而不是 import 语句，所以配置目录不需要是包；
* 使用唯一的模块名注册（``_fanza_config_xxx``），且**绝不把 config/ 目录
  加入 sys.path**——否则 ``config/logging.py`` 会遮蔽标准库的 ``logging``；
* 配置文件内的语法错误、运行期异常都会包装成 :class:`ConfigError`，
  附带出错行号，避免出现难以定位的裸 traceback。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .exceptions import ConfigError


def load_config_module(path: Path, module_name: str) -> ModuleType:
    """把指定 .py 文件加载为模块对象。

    :param path: 配置文件路径
    :param module_name: 注册到 sys.modules 的唯一名字（避免与标准库重名）
    :raises ConfigError: 文件不存在、语法错误或执行失败
    """
    if not path.exists():
        raise ConfigError(f"未找到配置文件：{path}")

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 极少数异常场景
        raise ConfigError(f"无法加载配置文件：{path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except SyntaxError as exc:
        raise ConfigError(
            f"配置文件存在语法错误：{path}（第 {exc.lineno} 行：{exc.msg}）"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 统一转为配置错误，便于集中处理
        raise ConfigError(
            f"配置文件执行失败：{path}（{exc.__class__.__name__}: {exc}）"
        ) from exc
    return module


def load_config_attr(path: Path, module_name: str, attr: str) -> Any:
    """加载配置文件并取出指定的变量 / 函数。

    :raises ConfigError: 文件加载失败，或文件中缺少指定名称
    """
    module = load_config_module(path, module_name)
    if not hasattr(module, attr):
        raise ConfigError(f"配置文件 {path} 缺少必需的变量或函数：{attr}")
    return getattr(module, attr)
