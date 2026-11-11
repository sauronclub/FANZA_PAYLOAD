# -*- coding: utf-8 -*-
"""核对 R2 上的对象与本地文件是否一致。

用途：上传之后做一次「远程 ↔ 本地」的独立复核，确认：
① 远端对象齐全（与本地文件一一对应）；
② 内容逐字节一致；
③ 结构仍然合规（PAYLOAD 顶层键只有三个 / HEADERS 是纯请求头字典）。

用法：
    python tools/verify_r2_objects.py [--prefix PAYLOAD/]

不依赖任何第三方 SDK —— 走项目自带的 :mod:`src.upload.sigv4`。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

from src.upload import R2Client  # noqa: E402

# 负载文件顶层应当**只有**这三个键（纯净负载，无任何包装）
_PAYLOAD_KEYS = ["operationName", "query", "variables"]


def _headers_structure(data: object) -> str:
    """校验请求头文件的结构，返回一句人话结论。"""
    if not isinstance(data, dict):
        return f"异常：顶层不是字典（{type(data).__name__}）"
    pseudo = [k for k in data if k.startswith(":")]
    return (
        f"纯请求头字典 ✓（{len(data)} 键，"
        f"cookie={'有' if 'cookie' in data else '无'}，"
        f"伪头={'有' if pseudo else '无'}）"
    )


def _payload_structure(data: object) -> str:
    """校验负载文件的结构，返回一句人话结论。"""
    if not isinstance(data, dict):
        return f"异常：顶层不是字典（{type(data).__name__}）"
    if list(data.keys()) == _PAYLOAD_KEYS:
        return "顶层键仅三个 ✓"
    return f"异常：顶层键为 {list(data.keys())}"


def main() -> int:
    parser = argparse.ArgumentParser(description="核对 R2 对象与本地文件一致性")
    parser.add_argument("--prefix", default="", help="只核对指定前缀下的对象")
    args = parser.parse_args()

    client = R2Client(
        endpoint_url=os.environ["R2_ENDPOINT"],
        access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        bucket=os.environ["R2_BUCKET"],
    )

    print("=" * 92)
    heading = f"桶 [{client.bucket}] 对象清单"
    if args.prefix:
        heading += f"（前缀 {args.prefix}）"
    print(heading)
    print("=" * 92)

    objects = sorted(client.iter_objects(prefix=args.prefix), key=lambda o: o["key"])
    if not objects:
        print("  （空）")
        client.close()
        return 0

    print(f"{'对象键':<38}{'远端大小':>10}{'MD5前12':>16}{'字节一致':>10}{'结构校验'}")
    print("-" * 92)

    missing_local = 0
    mismatch: list[str] = []
    struct_bad: list[str] = []

    for obj in objects:
        key = obj["key"]
        remote = client.get_object(key)
        local = _ROOT / key

        if local.is_file():
            same = local.read_bytes() == remote
        else:
            same = False
            missing_local += 1

        if not same:
            mismatch.append(key)

        try:
            data = json.loads(remote.decode("utf-8"))
            valid = True
        except Exception:  # noqa: BLE001
            data, valid = None, False

        if not valid:
            structure = "异常：不是合法 JSON"
        elif key.startswith("PAYLOAD/"):
            structure = _payload_structure(data)
        elif key.startswith("HEADERS/"):
            structure = _headers_structure(data)
        else:
            structure = f"非预期前缀（{type(data).__name__}）"

        if "✓" not in structure:
            struct_bad.append(key)

        print(
            f"{key:<38}{obj['size']:>10}{obj['etag'][:12]:>16}"
            f"{('是' if same else '否'):>10}  {structure}"
        )

    client.close()

    print("-" * 92)
    print(f"对象总数：{len(objects)}    远端总字节：{sum(o['size'] for o in objects)}")
    print(f"本地缺失：{missing_local}    内容不一致：{len(mismatch)}    结构异常：{len(struct_bad)}")

    if mismatch:
        print()
        print("内容不一致的对象：")
        for key in mismatch:
            hint = "" if (_ROOT / key).is_file() else "（本地无此文件）"
            print(f"  · {key}{hint}")

    ok = not mismatch and not struct_bad
    print()
    print("总体结论：" + ("全部一致且结构正确 ✓" if ok else "存在不一致，请检查 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
