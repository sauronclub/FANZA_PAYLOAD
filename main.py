# -*- coding: utf-8 -*-
"""FANZA GraphQL Payload 捕获器 —— 程序入口。

用法示例::

    python main.py                      # 捕获全部启用的页面
    python main.py --list               # 列出页面清单
    python main.py --validate           # 仅校验配置，不启动浏览器
    python main.py --only RANKING_DAILY,MOVIE_DETAIL
    python main.py --tag ranking        # 只跑带某标签的页面
    python main.py --headful            # 显示浏览器窗口（本机调试用）
    python main.py --no-notify          # 本次不推送飞书
    python main.py --no-upload          # 本次不上传到 Cloudflare R2

退出码：0 全部成功 / 1 存在失败 / 2 致命错误。
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

# 支持 `python main.py` 直接运行（把项目根目录加入模块搜索路径）
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import __version__  # noqa: E402
from src.core import ConfigError, PageSpec, load_pages, load_settings  # noqa: E402
from src.core.settings import Settings  # noqa: E402
from src.logkit import LOGGING_FILENAME, get_logger, setup_logging  # noqa: E402
from src.notify import build_notifier  # noqa: E402
from src.notify.base import Notifier, NullNotifier  # noqa: E402
from src.upload import build_uploader  # noqa: E402
from src.upload.base import NullUploader, Uploader  # noqa: E402
from src.runner import (  # noqa: E402
    EXIT_FATAL,
    Orchestrator,
    compute_exit_code,
    log_summary,
)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="fanza-payload",
        description="FANZA GraphQL Payload 捕获器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="配置目录（默认 ./config，内含 pages.py 与 logging.py）",
    )
    parser.add_argument("--only", default=None, help="仅运行指定页面，逗号分隔（不区分大小写）")
    parser.add_argument("--tag", default=None, help="仅运行带指定标签的页面")
    parser.add_argument("--list", action="store_true", help="列出页面清单后退出")
    parser.add_argument("--validate", action="store_true", help="仅校验配置后退出")
    parser.add_argument("--headful", action="store_true", help="以有界面模式运行（本机调试）")
    parser.add_argument("--no-notify", action="store_true", help="本次不推送通知")
    parser.add_argument("--no-upload", action="store_true", help="本次不上传到对象存储")
    parser.add_argument("--log-level", default=None, help="覆盖控制台日志级别（DEBUG/INFO/...）")
    return parser


def _new_run_id() -> str:
    """生成运行 ID：时间戳 + 随机后缀，便于日志聚合与人工识别。"""
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _select_pages(pages: list[PageSpec], only: Optional[str], tag: Optional[str]) -> list[PageSpec]:
    """按 --only / --tag 过滤页面。"""
    selected = pages

    if only:
        wanted = {name.strip().upper() for name in only.split(",") if name.strip()}
        selected = [p for p in selected if p.name.upper() in wanted]
        missing = wanted - {p.name.upper() for p in selected}
        if missing:
            raise ConfigError(f"--only 指定的页面不存在：{'、'.join(sorted(missing))}")

    if tag:
        wanted_tag = tag.strip()
        selected = [p for p in selected if wanted_tag in p.tags]
        if not selected:
            raise ConfigError(f"--tag 未匹配到任何页面：{wanted_tag}")

    return selected


def _print_page_list(pages: list[PageSpec]) -> None:
    """在控制台打印页面清单。"""
    print(f"{'名称':<24}{'状态':<6}{'operationName':<26}输出文件")
    print("-" * 92)
    for page in pages:
        status = "启用" if page.enabled else "停用"
        print(f"{page.name:<24}{status:<6}{page.operation_name:<26}{page.output}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """程序主入口。"""
    args = build_parser().parse_args(argv)

    # ── 1. 加载环境配置（此时日志尚未就绪，失败直接打到 stderr）──
    try:
        settings = load_settings()
        if args.config_dir:
            settings = dataclasses.replace(settings, config_dir=Path(args.config_dir).resolve())
        if args.headful:
            settings = dataclasses.replace(settings, headless=False)
    except ConfigError as exc:
        print(f"[致命错误] 环境配置加载失败：{exc}", file=sys.stderr)
        return EXIT_FATAL

    run_id = _new_run_id()

    # ── 2. 初始化日志 ──────────────────────────────────────────
    try:
        setup_logging(
            config_path=settings.config_dir / LOGGING_FILENAME,
            logs_dir=settings.logs_dir,
            run_id=run_id,
            level_override=args.log_level or settings.log_level,
        )
    except ConfigError as exc:
        print(f"[致命错误] 日志初始化失败：{exc}", file=sys.stderr)
        return EXIT_FATAL

    logger = get_logger("main")
    logger.info("=" * 68)
    logger.info("FANZA GraphQL Payload 捕获器 v%s（运行 ID：%s）", __version__, run_id)
    logger.info("=" * 68)

    # ── 3. 校验配置并加载页面清单 ──────────────────────────────
    try:
        settings.validate()
        pages = load_pages(settings.config_dir)
        selected = _select_pages(pages, args.only, args.tag)
    except ConfigError as exc:
        logger.critical("配置有误，无法继续：%s", exc)
        return EXIT_FATAL

    if args.list:
        _print_page_list(pages)
        logger.info("已列出 %d 个页面（--list 模式，未执行捕获）", len(pages))
        return 0

    if args.validate:
        logger.info("配置校验通过：共 %d 个页面，启用 %d 个", len(pages), sum(p.enabled for p in pages))
        print(f"配置校验通过：共 {len(pages)} 个页面，启用 {sum(p.enabled for p in pages)} 个")
        return 0

    if settings.notify_enabled:
        logger.info("已启用飞书通知")
    else:
        logger.info("未配置飞书 webhook，本次不推送通知")

    # ── 4. 装配通知与上传 ──────────────────────────────────────
    notifier: Notifier = (
        NullNotifier()
        if args.no_notify
        else build_notifier(settings.feishu_webhook_url, settings.feishu_sign_secret)
    )
    if args.no_notify:
        logger.info("命令行指定 --no-notify，本次不推送通知")

    uploader: Uploader
    if args.no_upload:
        uploader = NullUploader()
        logger.info("命令行指定 --no-upload，本次不上传")
    else:
        try:
            uploader = build_uploader(settings)
        except ConfigError as exc:
            logger.critical("上传配置有误，无法继续：%s", exc)
            return EXIT_FATAL
        if uploader.enabled:
            logger.info(
                "已启用对象存储上传：bucket=%s，前缀=%s",
                settings.r2_bucket,
                settings.r2_prefix or "（无）",
            )
        else:
            logger.info("未配置对象存储，本次不上传")

    # ── 5. 执行捕获 ────────────────────────────────────────────
    orchestrator = Orchestrator(
        settings=settings,
        pages=selected,
        notifier=notifier,
        run_id=run_id,
        uploader=uploader,
    )
    result = orchestrator.run()

    # ── 6. 输出摘要并推送通知 ──────────────────────────────────
    log_summary(logger, result)

    try:
        notifier.send_run_summary(result)
    except Exception as exc:  # noqa: BLE001 - 通知失败不影响主流程结果
        logger.warning("通知推送失败（不影响本次捕获结果）：%s", exc)

    exit_code = compute_exit_code(result)
    logger.info("进程退出码：%d", exit_code)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断", file=sys.stderr)
        sys.exit(130)
