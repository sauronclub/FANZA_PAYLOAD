# -*- coding: utf-8 -*-
"""JSON 落盘（PAYLOAD 负载文件与 HEADERS 请求头文件共用）。

采用「写临时文件 + 原子替换」策略，确保下游任何时刻读到的
文件要么是旧的完整内容、要么是新的完整内容，
不会出现写一半的残缺文件。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core.exceptions import StorageError
from ..logkit import get_logger

_logger = get_logger("storage.writer")


def write_json_atomic(path: Path, data: Any) -> None:
    """强制更新式写入 JSON 文件。

    流程：先写临时文件并落盘 → **删除旧文件** → 临时文件改名为正式文件。
    旧文件在新内容完全写好后才删除，因此不会出现「新内容写一半」的情况；
    但每次成功捕获都会重建文件，保证文件的创建/修改时间始终反映
    最新一次成功捕获，可通过时间戳直接判断产出是否正常。

    输出格式与 V1.02 保持一致：``indent=2``、``ensure_ascii=False``、
    末尾不额外追加换行符，便于与历史文件做字节级比对。

    :raises StorageError: 目录创建或写入失败
    """
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            path.unlink()
        os.replace(tmp_path, path)
    except OSError as exc:
        raise StorageError(f"写入文件失败：{path}（{exc}）") from exc
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                _logger.debug("清理临时文件失败：%s", tmp_path)
