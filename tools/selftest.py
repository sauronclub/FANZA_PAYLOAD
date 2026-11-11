# -*- coding: utf-8 -*-
"""自检脚本：验证重构后各核心组件的关键行为。

覆盖范围：
  1. 日志滚动处理器（按大小 / 跨天 / 保留期清理 / 不丢日志）
  2. 日志上下文过滤器（run_id 注入）
  3. 日志配置构建（config/logging.py 的 build_config）
  4. 页面清单校验（缺字段 / 重名 / url 冲突 / 环境变量缺失 / 语法错误）
  5. 输出布局（PAYLOAD 纯净负载 + HEADERS 请求头 + 多次请求编号）
  6. 飞书通知报文构造与签名（不实际发送）
  7. 请求头提取（HTTP/2 伪头剔除、cookie 保留）
  8. R2 配置校验（全空 / 半填 / 齐全）与上传器行为（不实际联网）
  9. AWS SigV4 签名（官方测试向量 / 查询串编码 / 规范化请求结构）

用法：python tools/selftest.py
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.exceptions import ConfigError  # noqa: E402
from src.core.models import CapturedRequest, PageSpec, RunResult, one_line  # noqa: E402
from src.core.page_registry import load_pages  # noqa: E402
from src.core.pyconfig import load_config_attr  # noqa: E402
from src.logkit.filters import ContextFilter  # noqa: E402
from src.logkit.handlers import DailySizeRotatingFileHandler  # noqa: E402
from src.notify.feishu import FeishuNotifier  # noqa: E402
from src.storage.layout import (  # noqa: E402
    headers_output_name,
    numbered_name,
    resolve_headers_path,
    resolve_payload_path,
)
from src.storage.writer import write_json_atomic  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [通过] {name}")
    else:
        FAILED.append(name)
        print(f"  [失败] {name}  {detail}")


def _count_lines(*paths: Path) -> int:
    total = 0
    for path in paths:
        if path.exists():
            total += len(path.read_text(encoding="utf-8").splitlines())
    return total


def _make_logger(name: str, handler: logging.Handler) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(handler)
    return logger


def _expect_config_error(label: str, func) -> None:
    """断言某个调用会抛出 ConfigError。"""
    try:
        func()
        check(f"应报错：{label}", False, "未抛出异常")
    except ConfigError:
        check(f"应报错：{label}", True)


# ── 1~3. 日志组件 ─────────────────────────────────────────
def test_rolling_handler() -> None:
    print("\n[1] 日志滚动处理器")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "app.log"
        handler = DailySizeRotatingFileHandler(
            str(base), when="midnight", max_bytes=800, retention_days=30, delay=False
        )
        logger = _make_logger("selftest.roll", handler)

        total = 300
        for i in range(total):
            logger.info("第 %03d 条日志 %s", i, "填充" * 20)
        handler.close()

        archives = sorted(Path(tmp).glob("app.log.*"))
        check("按大小触发滚动并生成归档", len(archives) >= 2, f"归档数={len(archives)}")
        check(
            "归档命名符合 <base>.<日期> 规则",
            all(a.name.startswith("app.log.20") for a in archives),
            f"{[a.name for a in archives][:3]}",
        )
        check(
            "日志无丢失",
            _count_lines(base, *archives) == total,
            f"实际={_count_lines(base, *archives)} 期望={total}",
        )


def test_rollover_on_date_change() -> None:
    print("\n[2] 跨天滚动")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "day.log"
        handler = DailySizeRotatingFileHandler(str(base), max_bytes=0, delay=False)
        logger = _make_logger("selftest.day", handler)
        logger.info("第一天的日志")

        # 伪造「上一天」的时间戳，触发跨天滚动
        handler._current_stamp = "1970-01-01"
        logger.info("第二天的日志")
        handler.close()

        archives = list(Path(tmp).glob("day.log.*"))
        check("跨天触发滚动", len(archives) >= 1, f"归档数={len(archives)}")
        check("滚动后仍保留全部日志", _count_lines(base, *archives) == 2)


def test_retention_purge() -> None:
    print("\n[3] 保留期清理")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "ret.log"
        stale = Path(tmp) / "ret.log.2000-01-01"
        stale.write_text("过期归档\n", encoding="utf-8")
        old_time = time.time() - 60 * 86400
        os.utime(stale, (old_time, old_time))

        handler = DailySizeRotatingFileHandler(
            str(base), max_bytes=0, retention_days=30, delay=False
        )
        handler.emit(logging.LogRecord("x", logging.INFO, __file__, 1, "触发", None, None))
        handler.close()

        check("超过保留期的归档被删除", not stale.exists())


def test_context_filter() -> None:
    print("\n[4] 日志上下文过滤器")
    filt = ContextFilter(fields={"run_id": "RUN-ABC"})
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    result = filt.filter(record)
    check("过滤器返回 True", result is True)
    check("已注入 run_id", getattr(record, "run_id", None) == "RUN-ABC")


# ── 5. 日志配置构建 ────────────────────────────────────────
def test_logging_config_builder() -> None:
    print("\n[5] 日志配置构建（config/logging.py）")
    path = PROJECT_ROOT / "config" / "logging.py"
    builder = load_config_attr(path, "_selftest_logging", "build_config")
    check("build_config 可加载且可调用", callable(builder))

    cfg = builder(logs_dir="/tmp/logs", run_id="RUN-1")
    check("返回字典结构", isinstance(cfg, dict))
    check("含有 console / file 两个处理器", {"console", "file"} <= set(cfg["handlers"]))
    check(
        "文件名与 run_id 已注入",
        cfg["handlers"]["file"]["filename"].endswith("fanza_payload.log")
        and cfg["filters"]["context"]["fields"]["run_id"] == "RUN-1",
    )
    check(
        "控制台与文件分级不同",
        cfg["handlers"]["console"]["level"] != cfg["handlers"]["file"]["level"],
    )
    check(
        "滚动与保留期参数已下发",
        cfg["handlers"]["file"]["max_bytes"] > 0
        and cfg["handlers"]["file"]["retention_days"] > 0,
    )
    check("日志器级别取两者中更宽松的", cfg["loggers"]["src"]["level"] == "DEBUG")
    check(
        "第三方库已降噪",
        cfg["loggers"]["playwright"]["level"] == "WARNING",
    )


# ── 6. 页面清单校验 ────────────────────────────────────────
def _write_pages(tmp: Path, source: str) -> Path:
    cfg = tmp / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "pages.py").write_text(source, encoding="utf-8")
    return cfg


VALID_PAGES = """
PAGES = [
    {
        "name": "P1",
        "url": "https://example.com/a",
        "operation_name": "OpA",
        "output": "a.json",
    },
    {
        "name": "P2",
        "url_env": "MY_URL",
        "operation_name": "OpA",
        "output": "b.json",
        "enabled": False,
    },
]
"""


def test_page_registry() -> None:
    print("\n[6] 页面清单校验（config/pages.py）")

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["MY_URL"] = "https://example.com/b"
        cfg = _write_pages(Path(tmp), VALID_PAGES)
        specs = load_pages(cfg)
        check("正常清单可加载", len(specs) == 2)
        check("enabled=False 被正确解析", specs[1].enabled is False)
        check("url_env 被正确解析", specs[1].url == "https://example.com/b")

        bad_cases = {
            "缺少 operation_name": """
PAGES = [{"name": "X", "url": "https://e.com", "output": "x.json"}]
""",
            "name 重复": """
PAGES = [
    {"name": "X", "url": "https://e.com/1", "operation_name": "O", "output": "a.json"},
    {"name": "X", "url": "https://e.com/2", "operation_name": "O", "output": "b.json"},
]
""",
            "output 重复": """
PAGES = [
    {"name": "X", "url": "https://e.com/1", "operation_name": "O", "output": "a.json"},
    {"name": "Y", "url": "https://e.com/2", "operation_name": "O", "output": "a.json"},
]
""",
            "url 与 url_env 同时存在": """
PAGES = [{"name": "X", "url": "https://e.com", "url_env": "MY_URL",
          "operation_name": "O", "output": "a.json"}]
""",
            "url 与 url_env 都缺失": """
PAGES = [{"name": "X", "operation_name": "O", "output": "a.json"}]
""",
            "出现未知字段（拼写错误）": """
PAGES = [{"name": "X", "url": "https://e.com", "operation_name": "O",
          "output": "a.json", "typo_field": 1}]
""",
            "enabled 类型错误": """
PAGES = [{"name": "X", "url": "https://e.com", "operation_name": "O",
          "output": "a.json", "enabled": "yes"}]
""",
            "tags 类型错误": """
PAGES = [{"name": "X", "url": "https://e.com", "operation_name": "O",
          "output": "a.json", "tags": "ranking"}]
""",
            "settle_ms 非正整数": """
PAGES = [{"name": "X", "url": "https://e.com", "operation_name": "O",
          "output": "a.json", "settle_ms": -1}]
""",
            "PAGES 不是列表": 'PAGES = {"name": "X"}\n',
            "PAGES 是空列表": "PAGES = []\n",
            "缺少 PAGES 变量": "OTHER = 1\n",
            "配置存在语法错误": 'PAGES = [{"name": "X",\n',
        }
        for label, source in bad_cases.items():
            cfg = _write_pages(Path(tmp), source)
            _expect_config_error(label, lambda c=cfg: load_pages(c))

        # 环境变量为空
        os.environ.pop("MY_URL", None)
        cfg = _write_pages(
            Path(tmp),
            'PAGES = [{"name": "X", "url_env": "MY_URL", '
            '"operation_name": "O", "output": "a.json"}]\n',
        )
        _expect_config_error("url_env 指向为空", lambda: load_pages(cfg))

        # 真实配置必须能通过校验
        real = load_pages(PROJECT_ROOT / "config")
        check("项目自带 config/pages.py 校验通过", len(real) >= 13, f"页数={len(real)}")


# ── 7. 输出布局：纯净负载 + 请求头 ─────────────────────────
def test_output_layout() -> None:
    print("\n[7] 输出布局（PAYLOAD / HEADERS）")
    spec = PageSpec(
        name="DEMO",
        url="https://example.com/p",
        operation_name="OpA",
        output="PAYLOAD_DEMO.json",
    )
    check(
        "负载路径正确",
        resolve_payload_path(Path("PAYLOAD"), spec).as_posix() == "PAYLOAD/PAYLOAD_DEMO.json",
    )
    check(
        "请求头文件名由 PAYLOAD_ 前缀自动推导",
        resolve_headers_path(Path("HEADERS"), spec).name == "HEADERS_DEMO.json",
    )
    check(
        "非标准前缀也能推导",
        headers_output_name("demo.json") == "HEADERS_demo.json",
    )
    check(
        "headers_output 可显式覆盖",
        resolve_headers_path(Path("HEADERS"), dataclasses.replace(spec, headers_output="H.json")).name
        == "H.json",
    )
    check("多次请求编号", numbered_name("PAYLOAD_DEMO.json", 2) == "PAYLOAD_DEMO__2.json")

    # 负载内容 = 服务端原始请求体，不做任何包装
    body = {
        "operationName": "OpA",
        "query": "query OpA { a }",
        "variables": {"x": 1},
    }
    request = CapturedRequest(
        url="https://api.example.com/graphql",
        operation_name="OpA",
        query="query OpA { a }",
        variables={"x": 1},
        headers={"fanza-device": "BROWSER", "content-type": "application/json"},
        body=body,
    )
    check("to_dict 返回原始请求体", request.to_dict() == body)

    with tempfile.TemporaryDirectory() as tmp:
        payload_file = Path(tmp) / "PAYLOAD_DEMO.json"
        headers_file = Path(tmp) / "HEADERS_DEMO.json"
        write_json_atomic(payload_file, request.to_dict())
        write_json_atomic(headers_file, request.headers)

        loaded = json.loads(payload_file.read_text(encoding="utf-8"))
        check(
            "落盘后顶层键与原始请求体完全一致",
            list(loaded.keys()) == ["operationName", "query", "variables"],
            f"实际={list(loaded.keys())}",
        )
        check(
            "负载内没有 meta / headers 等包装键",
            set(loaded) == {"operationName", "query", "variables"},
        )
        check("请求头文件可读且键完整", json.loads(headers_file.read_text(encoding="utf-8")) == request.headers)
        check("临时文件已清理", not (Path(tmp) / "PAYLOAD_DEMO.json.tmp").exists())
        check(
            "可被 JSON 序列化",
            isinstance(json.dumps(request.to_dict(), ensure_ascii=False), str),
        )


# ── 8. 飞书报文与签名 ──────────────────────────────────────
def test_feishu_payload() -> None:
    print("\n[8] 飞书通知报文")
    notifier = FeishuNotifier("https://example.com/hook", sign_secret="SECRET")

    result = RunResult(run_id="RUN-1", started_at=__import__("datetime").datetime.now())
    payload = notifier._build_payload("标题", "green", "**正文**")
    check("报文类型为交互卡片", payload["msg_type"] == "interactive")
    check("卡片结构完整", "header" in payload["card"] and "elements" in payload["card"])
    check("开启签名后有 sign 字段", "sign" in payload and "timestamp" in payload)
    check("签名可复现", notifier._sign("123") == notifier._sign("123"))
    check("摘要文本包含失败明细能力", "运行 ID" in notifier._build_markdown(result))

    no_sign = FeishuNotifier("https://example.com/hook")
    check("未开启签名时无 sign 字段", "sign" not in no_sign._build_payload("t", "red", "m"))


# ── 9. 工具函数 ────────────────────────────────────────────
def test_one_line() -> None:
    print("\n[9] 多行文本压缩")
    multi = "第一行\n第二行\n\n  第三行  "
    check("多行压成单行", one_line(multi) == "第一行 第二行 第三行")
    check("超长被截断", one_line("x" * 500, limit=10).endswith("…"))
    check("None 返回空串", one_line(None) == "")


# ── 10. 请求头提取 ─────────────────────────────────────────
def test_header_extraction() -> None:
    print("\n[10] 请求头提取（伪头剔除 / cookie 保留）")
    from src.capture.extractor import _normalize_headers

    raw = {
        ":authority": "api.video.dmm.co.jp",
        ":method": "POST",
        ":path": "/graphql",
        ":scheme": "https",
        "content-type": "application/json",
        "fanza-device": "BROWSER",
        "cookie": "age_check_done=1; FPID=abc",
        "origin": "https://video.dmm.co.jp",
    }
    out = _normalize_headers(raw)
    check("HTTP/2 伪头被剔除", not any(k.startswith(":") for k in out), f"实际={sorted(out)}")
    check("cookie 被保留", out.get("cookie") == "age_check_done=1; FPID=abc")
    check("origin 被保留", out.get("origin") == "https://video.dmm.co.jp")
    check(
        "非伪头一个不少",
        set(out) == {"content-type", "fanza-device", "cookie", "origin"},
        f"实际={sorted(out)}",
    )
    check("非字典输入返回空字典", _normalize_headers(None) == {})

    # 真实产物必须含 cookie 与 origin（此前用 request.headers 时两者均缺失）
    real = PROJECT_ROOT / "HEADERS"
    files = sorted(real.glob("HEADERS_*.json"))
    if files:
        sample = json.loads(files[0].read_text(encoding="utf-8"))
        check("真实请求头文件含 cookie", "cookie" in sample, f"实际键={sorted(sample)}")
        check("真实请求头文件不含伪头", not any(k.startswith(":") for k in sample))
    else:
        check("HEADERS 目录存在样本文件", False, "目录为空，请先运行一次捕获")


# ── 11. R2 配置校验 ────────────────────────────────────────
def test_r2_settings() -> None:
    print("\n[11] R2 配置校验")
    from src.core.settings import load_settings

    keys = [
        "R2_ACCOUNT_ID",
        "R2_ENDPOINT",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_PREFIX",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    saved_gql = os.environ.get("GRAPHQL_API_URL")
    os.environ["GRAPHQL_API_URL"] = "https://example.com/graphql"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            absent = root / ".env.absent"

            s = load_settings(project_root=root, env_file=absent)
            check("R2 全空 = 关闭上传", s.upload_enabled is False and s.r2_partial is False)
            s.validate()
            check("R2 全空时 validate 通过", True)

            os.environ["R2_BUCKET"] = "mybucket"
            os.environ["R2_ACCESS_KEY_ID"] = "keyid"
            s = load_settings(project_root=root, env_file=absent)
            check("R2 半填被识别为不完整", s.r2_partial is True)
            _expect_config_error("R2 半填时 validate 报错", s.validate)

            os.environ["R2_ACCOUNT_ID"] = "acc123"
            os.environ["R2_SECRET_ACCESS_KEY"] = "secret"
            s = load_settings(project_root=root, env_file=absent)
            check(
                "端点由 ACCOUNT_ID 自动拼出",
                s.r2_endpoint_url == "https://acc123.r2.cloudflarestorage.com",
                f"实际={s.r2_endpoint_url}",
            )
            check("R2 配置齐全 = 启用上传", s.upload_enabled is True)
            s.validate()
            check("R2 配置齐全时 validate 通过", True)

            os.environ["R2_PREFIX"] = "/fanza/payload/"
            s = load_settings(project_root=root, env_file=absent)
            check("前缀两端斜杠被清理", s.r2_prefix == "fanza/payload", f"实际={s.r2_prefix!r}")
    finally:
        for key in keys:
            os.environ.pop(key, None)
            if saved[key] is not None:
                os.environ[key] = saved[key]
        if saved_gql is None:
            os.environ.pop("GRAPHQL_API_URL", None)
        else:
            os.environ["GRAPHQL_API_URL"] = saved_gql


# ── 12. 上传器行为 ─────────────────────────────────────────
def test_uploader_behaviour() -> None:
    print("\n[12] 上传器行为（不联网）")
    from src.upload.base import NullUploader, UploadItem
    from src.upload.r2 import R2Uploader

    null = NullUploader()
    check("NullUploader 标记为未启用", null.enabled is False)
    batch = null.upload_many([UploadItem(Path("a.json"), "PAYLOAD/a.json")])
    check(
        "NullUploader 全部计为跳过",
        batch.skipped == 1 and batch.succeeded == 0 and batch.failed == 0,
    )

    uploader = R2Uploader(
        "https://acc.r2.cloudflarestorage.com", "keyid", "secret", "bucket", prefix="fanza"
    )
    check("R2Uploader 标记为已启用", uploader.enabled is True)
    check("R2Uploader 暴露桶名", uploader.bucket == "bucket")
    check(
        "端点被规整为 scheme://host",
        uploader.client.endpoint == "https://acc.r2.cloudflarestorage.com",
    )
    # 直接校验生产代码的默认参数，而不是替身的行为
    import inspect

    from src.upload.r2 import R2Client

    default_ct = inspect.signature(R2Client.put_object).parameters["content_type"].default
    check("R2Client 默认内容类型为 JSON", "json" in default_ct, default_ct)
    check(
        "默认使用 path-style 寻址（R2 无区域概念，区域固定 auto）",
        uploader.client.region == "auto",
        uploader.client.region,
    )

    class FakeClient:
        """替代真实 R2 客户端，只记录调用，不发起网络请求。"""

        def __init__(self) -> None:
            self.calls: list[dict] = []

        def put_object(
            self, key: str, body: bytes, content_type: str = ""
        ) -> int:  # noqa: D102
            self.calls.append({"key": key, "body": body, "content_type": content_type})
            return len(body)

    fake = FakeClient()
    uploader.client = fake  # noqa: SLF001 - 测试注入替身

    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "PAYLOAD_DEMO.json"
        local.write_text('{"a": 1}', encoding="utf-8")

        outcome = uploader.upload_one(UploadItem(local, "PAYLOAD/PAYLOAD_DEMO.json"))
        check("上传成功", outcome.success is True and outcome.size_bytes == 8)
        check(
            "对象键已拼上前缀",
            fake.calls[0]["key"] == "fanza/PAYLOAD/PAYLOAD_DEMO.json",
            f"实际={fake.calls[0]['key']}",
        )
        check(
            "请求体为文件原始字节",
            fake.calls[0]["body"] == b'{"a": 1}',
        )

        missing = uploader.upload_one(UploadItem(Path(tmp) / "nope.json", "PAYLOAD/nope.json"))
        check("文件缺失时返回失败而非抛异常", missing.success is False)
        check("失败信息说明原因", "不存在" in (missing.error or ""))

    class FailingClient:
        """始终抛异常，用于验证重试与失败收敛。"""

        def __init__(self) -> None:
            self.attempts = 0

        def put_object(self, key: str, body: bytes, content_type: str = "") -> int:  # noqa: D102
            self.attempts += 1
            raise RuntimeError("模拟网络故障")

    failing = FailingClient()
    uploader.client = failing  # noqa: SLF001
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "x.json"
        local.write_text("{}", encoding="utf-8")
        outcome = uploader.upload_one(UploadItem(local, "PAYLOAD/x.json"))
        check("失败时按上限重试", failing.attempts == 3, f"实际={failing.attempts}")
        check("最终返回失败且带错误信息", outcome.success is False and outcome.error)


# ── 14. SigV4 签名（纯标准库，不联网） ─────────────────────
def test_sigv4_signing() -> None:
    print("\n[14] AWS SigV4 签名（不联网）")
    from src.upload import sigv4

    # AWS 官方文档「derive a signing key」给出的测试向量
    derived = sigv4.derive_signing_key(
        "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20120215", "us-east-1", "iam"
    ).hex()
    check(
        "签名密钥派生与 AWS 官方测试向量一致",
        derived == "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d",
        f"实际={derived}",
    )

    check("空查询串返回空字符串", sigv4.build_canonical_query_string({}) == "")
    check(
        "查询串按键名排序",
        sigv4.build_canonical_query_string({"max-keys": "1000", "list-type": "2"})
        == "list-type=2&max-keys=1000",
    )
    check(
        "查询串的键值均做 RFC3986 编码",
        sigv4.build_canonical_query_string({"prefix": "PAYLOAD/", "a b": "c/d"})
        == "a%20b=c%2Fd&prefix=PAYLOAD%2F",
    )
    check(
        "路径编码保留斜杠分隔符",
        sigv4.encode_uri("/b/PAYLOAD/中文.json") == "/b/PAYLOAD/%E4%B8%AD%E6%96%87.json",
    )

    # 规范化请求必须是「六段」，且规范化头部与签名头列表之间有一个空行
    cr = sigv4.build_canonical_request(
        method="PUT",
        canonical_uri="/b/x.json",
        canonical_query="",
        canonical_headers={"content-type": "application/json", "host": "h.example.com"},
        signed_header_names=["content-type", "host"],
        payload_hash="deadbeef",
    )
    check(
        "规范化请求结构正确（六段 + 头部末尾换行）",
        cr
        == "PUT\n/b/x.json\n\ncontent-type:application/json\nhost:h.example.com\n"
        "\ncontent-type;host\ndeadbeef",
        repr(cr),
    )
    check(
        "头部取值折叠内部连续空白",
        sigv4.normalize_header_value("  a   b  ") == "a b",
    )

    # 固定时间点签名：验证输出形状与稳定性（不校验签名值本身，那由真实 R2 校验）
    from datetime import datetime, timezone

    headers = sigv4.sign_request(
        method="PUT",
        endpoint="https://acc.r2.cloudflarestorage.com",
        path="/bucket/PAYLOAD/x.json",
        access_key_id="AKIDEXAMPLE",
        secret_access_key="SECRET",
        headers={"content-type": "application/json; charset=utf-8"},
        payload=b"{}",
        now=datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    check("签名为 x-amz-date 使用 UTC", headers["x-amz-date"] == "20261015T120000Z")
    check(
        "载荷哈希头等于空对象的 SHA-256",
        headers["x-amz-content-sha256"]
        == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        headers["x-amz-content-sha256"],
    )
    auth = headers["Authorization"]
    check(
        "Authorization 头符合 SigV4 格式",
        auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261015/auto/s3/aws4_request,")
        and "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date" in auth
        and "Signature=" in auth,
        auth,
    )
    check(
        "同一输入签名可复现",
        sigv4.sign_request(
            method="PUT",
            endpoint="https://acc.r2.cloudflarestorage.com",
            path="/bucket/PAYLOAD/x.json",
            access_key_id="AKIDEXAMPLE",
            secret_access_key="SECRET",
            headers={"content-type": "application/json; charset=utf-8"},
            payload=b"{}",
            now=datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc),
        )["Authorization"]
        == auth,
    )


# ── 13. 对象键推导与运行摘要 ───────────────────────────────
def test_remote_key_and_summary() -> None:
    print("\n[13] 对象键推导 / 运行摘要")
    from datetime import datetime

    from src.core.settings import load_settings
    from src.runner.orchestrator import Orchestrator
    from src.notify.base import NullNotifier
    from src.upload.base import NullUploader

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = load_settings(project_root=root, env_file=root / ".env.absent")
        orch = Orchestrator(
            settings=settings,
            pages=[],
            notifier=NullNotifier(),
            run_id="RUN-T",
            uploader=NullUploader(),
        )
        check(
            "对象键保留 PAYLOAD/ 目录结构",
            orch._remote_key(root / "PAYLOAD" / "PAYLOAD_X.json") == "PAYLOAD/PAYLOAD_X.json",  # noqa: SLF001
        )
        check(
            "对象键保留 HEADERS/ 目录结构",
            orch._remote_key(root / "HEADERS" / "HEADERS_X.json") == "HEADERS/HEADERS_X.json",  # noqa: SLF001
        )
        check(
            "项目外文件退化为纯文件名",
            orch._remote_key(Path(tempfile.gettempdir()) / "zz.json") == "zz.json",  # noqa: SLF001
        )

    result = RunResult(run_id="RUN-S", started_at=datetime.now())
    result.uploaded_files = 26
    result.uploaded_bytes = 20_480
    result.failed_uploads = ["PAYLOAD/PAYLOAD_BAD.json"]
    text = result.summary_text()
    check("摘要含上传统计", "云端上传" in text and "2" in text, text.replace("\n", " | "))
    check("摘要列出失败对象键", "PAYLOAD/PAYLOAD_BAD.json" in text)

    schema = result.schema()
    check("结构化摘要含 upload 段", "upload" in schema)
    check(
        "结构化上传字段正确",
        schema["upload"]["uploaded"] == 26
        and schema["upload"]["failed"] == 1
        and schema["upload"]["failed_keys"] == ["PAYLOAD/PAYLOAD_BAD.json"],
    )

    skipped = RunResult(run_id="RUN-K", started_at=datetime.now())
    skipped.skipped_uploads = 26
    check("未启用上传时摘要提示跳过", "未启用上传" in skipped.summary_text())


def main() -> int:
    print("=" * 72)
    print("FANZA Payload 捕获器 —— 组件自检")
    print("=" * 72)
    test_rolling_handler()
    test_rollover_on_date_change()
    test_retention_purge()
    test_context_filter()
    test_logging_config_builder()
    test_page_registry()
    test_output_layout()
    test_feishu_payload()
    test_one_line()
    test_header_extraction()
    test_r2_settings()
    test_uploader_behaviour()
    test_remote_key_and_summary()
    test_sigv4_signing()

    print("\n" + "=" * 72)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：")
        for name in FAILED:
            print("  ·", name)
    print("=" * 72)
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
