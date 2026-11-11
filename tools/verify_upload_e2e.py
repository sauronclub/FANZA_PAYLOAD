# -*- coding: utf-8 -*-
"""端到端验证：真实捕获全部页面 + 替身 R2 客户端验证上传链路。

用替身客户端替换真实 R2 客户端，因此**不会真的往 R2 发请求**，
但走的是与生产完全相同的代码路径：配置加载 → 上传器构造 →
编排器收集本轮文件 → 逐文件上传 → 统计回填 → 运行摘要。

用法：python tools/verify_upload_e2e.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# 用环境变量喂入一套「完整但虚构」的 R2 配置；
# load_dotenv(override=False) 不会覆盖已存在的环境变量，因此这里必定生效。
os.environ.update(
    {
        "R2_ACCOUNT_ID": "verify-account",
        "R2_BUCKET": "verify-bucket",
        "R2_ACCESS_KEY_ID": "verify-key-id",
        "R2_SECRET_ACCESS_KEY": "verify-secret",
        "R2_PREFIX": "fanza",
    }
)

from src.core.page_registry import load_pages  # noqa: E402
from src.core.settings import load_settings  # noqa: E402
from src.notify.base import NullNotifier  # noqa: E402
from src.runner.orchestrator import Orchestrator  # noqa: E402
from src.upload.r2 import build_uploader  # noqa: E402


class FakeR2Client:
    """只记录调用，不发起真实网络请求。"""

    def __init__(self, bucket: str) -> None:
        self.bucket = bucket
        self.endpoint = "https://verify-account.r2.cloudflarestorage.com"
        self.region = "auto"
        self.calls: list[dict] = []

    def put_object(self, key: str, body: bytes, content_type: str = "") -> int:
        """记录一次上传调用。"""
        self.calls.append({"key": key, "size": len(body), "content_type": content_type})
        return len(body)


def main() -> int:
    settings = load_settings()
    settings.validate()
    pages = load_pages(settings.config_dir)

    uploader = build_uploader(settings)
    print(f"上传器：{type(uploader).__name__}（enabled={uploader.enabled}）")
    print(f"端点：{settings.r2_endpoint_url}")
    print(f"桶：{settings.r2_bucket}    前缀：{settings.r2_prefix!r}")
    if not uploader.enabled:
        print("[中止] 上传器未启用，说明配置未生效")
        return 1

    fake = FakeR2Client(settings.r2_bucket)
    uploader.client = fake  # noqa: SLF001 - 注入替身

    orchestrator = Orchestrator(
        settings=settings,
        pages=pages,
        notifier=NullNotifier(),
        run_id="RUN-E2E",
        uploader=uploader,
    )
    result = orchestrator.run()

    print()
    print("=" * 78)
    print("运行摘要")
    print("=" * 78)
    print(result.summary_text())

    print()
    print("=" * 78)
    print(f"替身客户端共收到 {len(fake.calls)} 次 put_object")
    print("=" * 78)
    payload_calls = [c for c in fake.calls if str(c["key"]).split("/")[1] == "PAYLOAD"]
    header_calls = [c for c in fake.calls if str(c["key"]).split("/")[1] == "HEADERS"]
    print(f"  PAYLOAD 对象：{len(payload_calls)} 个")
    print(f"  HEADERS 对象：{len(header_calls)} 个")
    print()
    for call in fake.calls[:6]:
        print(f"  key={call['key']:<46} {call['size']:>6} 字节")
    if len(fake.calls) > 6:
        print(f"  ...（其余 {len(fake.calls) - 6} 个略）")

    bad_keys = [c["key"] for c in fake.calls if not str(c["key"]).startswith("fanza/")]
    print()
    print(f"未带前缀的对象：{bad_keys or '无'}")
    print(f"空文件对象：{[c['key'] for c in fake.calls if c['size'] == 0] or '无'}")
    print(
        f"统计回填：uploaded={result.uploaded_files} bytes={result.uploaded_bytes} "
        f"skipped={result.skipped_uploads} failed={len(result.failed_uploads)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
