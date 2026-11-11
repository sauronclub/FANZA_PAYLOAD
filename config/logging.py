# -*- coding: utf-8 -*-
"""日志配置（Python 配置）。

本模块只做一件事：返回 logging.config.dictConfig 需要的字典。
想调整日志行为，直接改下面「可调参数」区的常量即可，不需要懂 dictConfig 语法。

分级策略
--------
  控制台   只输出 CONSOLE_LEVEL 及以上，面向人工观察（嫌吵就把级别调高）
  日志文件 记录 FILE_LEVEL 及以上全量，面向事后排查
  两者级别都可用命令行 --log-level 或 .env 的 LOG_LEVEL 覆盖「控制台」级别

滚动策略
--------
  按天滚动 + 单文件大小上限 + 超期归档自动清理

上下文
------
  每条日志都会带上本次运行的 run_id，便于把一次运行的所有行捞出来。
"""

# ══════════════════════════════════════════════════════════════
# 可调参数（改这几行就够了）
# ══════════════════════════════════════════════════════════════

CONSOLE_LEVEL = "INFO"          # 控制台级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
FILE_LEVEL = "DEBUG"            # 文件级别：留 DEBUG 表示全量留存

ROLLOVER_WHEN = "midnight"      # 滚动时机：midnight=每天 0 点 / hourly=每小时
MAX_BYTES = 10 * 1024 * 1024    # 单文件上限（字节），超出立即滚动；0 表示不按大小滚动
RETENTION_DAYS = 30             # 归档保留天数，超期自动删除；0 表示永不删除

LOG_BASENAME = "fanza_payload.log"   # 日志文件名（统一落在 logs/ 目录下）
ENCODING = "utf-8"

# 第三方库降噪：这些库的 DEBUG 日志通常没有价值
THIRD_PARTY_LEVELS = {
    "playwright": "WARNING",
    "urllib3": "WARNING",
}

# ══════════════════════════════════════════════════════════════
# 格式模板（% 风格，logging 标准）
# ══════════════════════════════════════════════════════════════

CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-26s | %(message)s"
FILE_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(run_id)s | "
    "%(name)-26s | %(funcName)s:%(lineno)d | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def build_config(logs_dir: str, run_id: str) -> dict:
    """构造 dictConfig 配置字典。

    :param logs_dir: 日志目录的绝对路径（已由调用方创建好）
    :param run_id: 本次运行的唯一 ID，会注入到每一条日志
    :return: 可直接交给 logging.config.dictConfig 的字典
    """
    # 统一使用正斜杠，Windows / Linux 都能正确解析
    log_path = f"{logs_dir.rstrip('/')}/{LOG_BASENAME}"

    config = {
        "version": 1,
        "disable_existing_loggers": False,

        "formatters": {
            "console": {"format": CONSOLE_FORMAT, "datefmt": DATE_FORMAT},
            "file": {"format": FILE_FORMAT, "datefmt": DATE_FORMAT},
        },

        "filters": {
            # 为每条日志注入 run_id，便于跨文件追踪同一次运行
            "context": {
                "()": "src.logkit.filters.ContextFilter",
                "fields": {"run_id": run_id},
            },
        },

        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": CONSOLE_LEVEL,
                "formatter": "console",
                "filters": ["context"],
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "src.logkit.handlers.DailySizeRotatingFileHandler",
                "level": FILE_LEVEL,
                "formatter": "file",
                "filters": ["context"],
                "filename": log_path,
                "when": ROLLOVER_WHEN,
                "max_bytes": MAX_BYTES,
                "retention_days": RETENTION_DAYS,
                "encoding": ENCODING,
                # delay=True：进程未写日志时不创建空文件
                "delay": True,
            },
        },

        "loggers": {
            # 本项目所有模块统一使用 src.* 命名，便于集中控制
            "src": {
                "level": min(FILE_LEVEL, CONSOLE_LEVEL, key=_level_order),
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },

        "root": {"level": "WARNING", "handlers": ["console"]},
    }

    # 第三方库降噪（逐个写入，便于在配置里一眼看出哪些库被压了级别）
    for name, level in THIRD_PARTY_LEVELS.items():
        config["loggers"][name] = {"level": level, "propagate": True}

    return config


# 级别由低到高的排序权重，用于取「两个级别中更宽松的那个」作为 logger 级别
_LEVEL_WEIGHT = {
    "NOTSET": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _level_order(level: str) -> int:
    """返回级别的排序权重（未知级别按 INFO 处理）。"""
    return _LEVEL_WEIGHT.get(str(level).upper(), 20)
