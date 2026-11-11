# -*- coding: utf-8 -*-
"""页面清单（Python 配置）。

用 Python 而不是 YAML 的原因：
  * 编辑器语法高亮、缩进提示、拼写检查都直接生效，改错一眼就能看出来；
  * 不引入第三方解析库（少一个依赖，少一处运行环境差异）；
  * 可以直接写注释、变量、推导式，后续批量增删页面更方便。

字段说明
--------
name            唯一标识（日志与 --only 参数用它），建议大写 + 下划线
url             页面地址；与 url_env 二选一（必须且只能有一个）
url_env         从环境变量读取页面地址（适合不想把地址写进仓库的场景）
operation_name  该页面需要捕获的 GraphQL operationName
output          负载输出文件名（落在 PAYLOAD/ 目录下）
headers_output  可选，请求头输出文件名（落在 HEADERS/ 目录下）。
                不填时由 output 自动推导：PAYLOAD_X.json -> HEADERS_X.json
enabled         False 表示临时停用，配置保留但本次不执行
tags            可选，用于分类统计与批量筛选（--tag）
description     可选，中文备注
settle_ms       可选，捕获到目标请求后额外等待的毫秒数（等待同页后续请求）
timeout_ms      可选，覆盖默认的单页等待超时（毫秒）

注意
----
AvSearch 被多个页面共用（演员 / 演员+类型 / 系列 / 日期），
因此必须按「页面」维度管理，不能靠 operationName 区分。

本文件由 src/core/page_registry.py 加载并校验：
字段写错、name 或 output 重复、url 与 url_env 冲突，都会在启动时直接报错。
"""


PAGES = [
    # ── 排行榜类 ────────────────────────────────────────────
    {
        "name": "RANKING_DAILY",
        "url": "https://video.dmm.co.jp/av/ranking/?term=daily",
        "operation_name": "ContentRankingPage",
        "output": "PAYLOAD_DAILY.json",
        "tags": ["ranking"],
        "description": "每日排行榜",
    },
    {
        "name": "RANKING_WEEKLY",
        "url": "https://video.dmm.co.jp/av/ranking/?term=weekly",
        "operation_name": "ContentRankingPage",
        "output": "PAYLOAD_WEEKLY.json",
        "tags": ["ranking"],
        "description": "周排行榜",
    },
    {
        "name": "RANKING_MONTHLY",
        "url": "https://video.dmm.co.jp/av/ranking/?term=monthly",
        "operation_name": "ContentRankingPage",
        "output": "PAYLOAD_MONTHLY.json",
        "tags": ["ranking"],
        "description": "月排行榜",
    },
    {
        "name": "RANKING_MONTHLY_ACTRESS",
        "url": "https://video.dmm.co.jp/av/ranking/?term=monthly&type=actress",
        "operation_name": "ActressRankingPage",
        "output": "PAYLOAD_MONTHLY_ACTRESS.json",
        "tags": ["ranking"],
        "description": "月演员排行榜",
    },
    {
        "name": "RANKING_MONTHLY_SERIES",
        "url": "https://video.dmm.co.jp/av/ranking/?term=monthly&type=series",
        "operation_name": "SeriesRankingPage",
        "output": "PAYLOAD_MONTHLY_SERIES.json",
        "tags": ["ranking"],
        "description": "月系列排行榜",
    },
    {
        "name": "RANKING_REALTIME",
        "url": "https://video.dmm.co.jp/av/ranking/?term=realtime",
        "operation_name": "ContentRankingPage",
        "output": "PAYLOAD_REALTIME.json",
        "tags": ["ranking"],
        "description": "实时排行榜",
    },
    {
        "name": "RANKING_REALTIME_VR",
        "url": "https://video.dmm.co.jp/av/ranking/?term=realtime&only=vr",
        "operation_name": "ContentRankingPage",
        "output": "PAYLOAD_REALTIME_VR.json",
        "tags": ["ranking", "vr"],
        "description": "VR 实时排行榜",
    },
    {
        "name": "RANKING_LATEST_RELEASE",
        "url": "https://video.dmm.co.jp/av/ranking/?release=latest",
        "operation_name": "NewReleaseRankingPage",
        "output": "PAYLOAD_LATEST_RELEASE.json",
        "tags": ["ranking"],
        "description": "新片排行榜",
    },

    # ── 详情类 ──────────────────────────────────────────────
    {
        "name": "MOVIE_DETAIL",
        "url": "https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=snos00097/",
        "operation_name": "ContentPageData",
        "output": "PAYLOAD_ID.json",
        "tags": ["detail"],
        "description": "影片详情页",
    },
    {
        "name": "SERIES_DETAIL",
        "url": "https://video.dmm.co.jp/av/list/?series=5087&sort=date",
        "operation_name": "AvSearch",
        "output": "PAYLOAD_SERIES.json",
        "tags": ["detail", "search"],
        "description": "系列详情页（系列内影片清单）",
    },

    # ── 清单类 ──────────────────────────────────────────────
    {
        "name": "ACTRESS_LIST",
        "url": "https://video.dmm.co.jp/av/list/?actress=1087625&sort=date",
        "operation_name": "AvSearch",
        "output": "PAYLOAD_ACTRESS.json",
        "tags": ["search"],
        "description": "演员影片清单页（按上映日期排序）",
    },
    {
        "name": "ACTRESS_SOLO",
        "url": "https://video.dmm.co.jp/av/list/?actress=1087625&genre=4025&sort=date",
        "operation_name": "AvSearch",
        "output": "PAYLOAD_ACTRESS_SOLO.json",
        "tags": ["search"],
        "description": "演员单人影片清单页（演员 + 类型双重过滤）",
    },
    {
        "name": "NEW_RELEASE_DATE",
        "url": "https://video.dmm.co.jp/av/list/?date=2026-10-01",
        "operation_name": "AvSearch",
        "output": "PAYLOAD_DATE.json",
        "tags": ["search"],
        "description": "按上映日期的影片清单页",
    },
]
