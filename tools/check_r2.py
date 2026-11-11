# -*- coding: utf-8 -*-
"""R2 连通性与权限自检工具。

用途：本机或 VPS 上快速定位 R2 上传失败的原因（凭据错、桶名错、权限不足等）。
只读 + 一次「写入后立即删除」的干跑，不会留下任何残留对象。

用法：
    python tools/check_r2.py

读取顺序与主程序一致：先加载项目根目录的 .env，再读环境变量。
不依赖任何第三方 SDK —— 走项目自带的 :mod:`src.upload.sigv4`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 允许以 `python tools/check_r2.py` 直接运行（把项目根加入 sys.path）
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

from src.upload import R2Client  # noqa: E402

# 探测对象键名，固定且带下划线前缀，便于识别与清理
_PROBE_KEY = "_connectivity_check.json"


def _mask(value: str) -> str:
    """把密钥打码，避免自检输出泄露敏感信息。"""
    if not value:
        return "（未填）"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}（{len(value)} 字符）"


def main() -> int:
    account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
    endpoint = os.getenv("R2_ENDPOINT", "").strip()
    bucket = os.getenv("R2_BUCKET", "").strip()
    access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    prefix = os.getenv("R2_PREFIX", "").strip()

    if not endpoint:
        endpoint = (
            f"https://{account_id}.r2.cloudflarestorage.com" if account_id else ""
        )

    print("=" * 74)
    print("① 配置读取（密钥已打码）")
    print("=" * 74)
    print(f"  R2_ENDPOINT          = {endpoint or '（未填）'}")
    print(f"  R2_BUCKET            = {bucket or '（未填）'}")
    print(f"  R2_PREFIX            = {prefix or '（空，直接放桶根）'}")

    missing = [
        name
        for name, value in [
            ("R2_ENDPOINT（或 R2_ACCOUNT_ID）", endpoint),
            ("R2_BUCKET", bucket),
            ("R2_ACCESS_KEY_ID", access_key_id),
            ("R2_SECRET_ACCESS_KEY", secret),
        ]
        if not value
    ]
    if missing:
        print()
        print("  ✗ 配置不完整，缺少：" + "、".join(missing))
        print("    请补齐 .env 中对应项后重试。")
        return 2

    print(f"  R2_ACCESS_KEY_ID     = {_mask(access_key_id)}")
    print(f"  R2_SECRET_ACCESS_KEY = {_mask(secret)}")

    client = R2Client(
        endpoint_url=endpoint,
        access_key_id=access_key_id,
        secret_access_key=secret,
        bucket=bucket,
    )

    print()
    print("=" * 74)
    print("② 目标桶可访问性（HEAD）")
    print("=" * 74)
    print("  说明：R2 令牌若只授权到具体桶，列举桶列表会返回 AccessDenied ——")
    print("        这是正常现象。本工具不依赖列举桶，直接以 HEAD 结果为准。")
    try:
        client.head_bucket()
        print(f"  ✓ 桶存在且可访问：{bucket}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 访问失败：{exc}")
        print("    常见原因：桶名拼写错误 / 令牌未授权该桶 / 桶不在该账户下。")
        return 1

    print()
    print("=" * 74)
    print("③ 读取权限（ListObjectsV2）")
    print("=" * 74)
    try:
        total = 0
        preview: list[str] = []
        for obj in client.iter_objects():
            total += 1
            if len(preview) < 10:
                preview.append(f"{obj['size']:>8} B  {obj['key']}")
        print(f"  ✓ 可列举对象，桶内共 {total} 个：")
        for line in preview:
            print(f"      {line}")
        if total > len(preview):
            print(f"      ……（另有 {total - len(preview)} 个未显示）")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 列举失败：{exc}")
        return 1

    print()
    print("=" * 74)
    print("④ 写入权限（干跑：上传后立即删除一个探测对象）")
    print("=" * 74)
    try:
        body = b'{"check": "fanza-payload", "note": "connectivity probe"}'
        client.put_object(_PROBE_KEY, body)
        print(f"  ✓ 上传成功：{_PROBE_KEY}")

        fetched = client.get_object(_PROBE_KEY)
        print(f"  ✓ 回读一致：{fetched == body}")

        client.delete_object(_PROBE_KEY)
        print(f"  ✓ 已删除探测对象：{_PROBE_KEY}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 写入/回读失败：{exc}")
        print("    若为 AccessDenied，请确认令牌权限含「Object Read & Write」并限定到该桶。")
        return 1
    finally:
        client.close()

    print()
    print("  结论：R2 配置完全可用，可以开启上传。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
