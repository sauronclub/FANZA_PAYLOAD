# -*- coding: utf-8 -*-
"""实机验证：不同页面捕获到的请求头，究竟是不是同一份。

对比三件事：
  1. request.headers      —— Playwright 常规 API（项目当前用的）
  2. request.all_headers() —— 完整头（含 cookie 等"附加"头）
  3. context.cookies()    —— 上下文里的 cookie

目的：判断 HEADERS/ 下 13 个文件完全相同，是代码缺陷还是客观事实。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.browser.age_gate import AgeGateHandler  # noqa: E402
from src.core.settings import load_settings  # noqa: E402

GRAPHQL_API_URL = load_settings().graphql_api_url

TARGETS = [
    ("RANKING_DAILY", "https://video.dmm.co.jp/av/ranking/?term=daily", "ContentRankingPage"),
    ("ACTRESS_LIST", "https://video.dmm.co.jp/av/list/?actress=1087625", "AvSearch"),
    ("RANKING_REALTIME", "https://video.dmm.co.jp/av/ranking/?term=realtime", "ContentRankingPage"),
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


def main() -> int:
    hits: list[dict] = []
    captured: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent=UA,
            locale="ja-JP",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        current = {"name": None, "op": None}

        def on_request(request):
            if current["name"] is None:
                return
            if "POST" != request.method or GRAPHQL_API_URL not in request.url:
                return
            raw = request.post_data
            if not raw:
                return
            try:
                body = json.loads(raw)
            except Exception:
                return
            op = body.get("operationName")
            if op != current["op"]:
                return
            try:
                all_h = request.all_headers()
            except Exception as exc:  # noqa: BLE001
                all_h = {"<all_headers 失败>": str(exc)}
            captured.append(
                {
                    "page": current["name"],
                    "op": op,
                    "headers": request.headers,
                    "all_headers": all_h,
                    "cookie_header": request.headers.get("cookie"),
                }
            )

        page.on("request", on_request)
        gate = AgeGateHandler()

        # 预热：先过年龄验证
        page.goto(TARGETS[0][1], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        gate.ensure_passed(page)

        for name, url, op in TARGETS:
            current["name"], current["op"] = name, op
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(7000)

        cookies = context.cookies()
        browser.close()

    # ── 输出 ─────────────────────────────────────────────
    print("=" * 78)
    print("① 每个页面捕获到的请求数")
    print("=" * 78)
    for name, _, _ in TARGETS:
        n = sum(1 for c in captured if c["page"] == name)
        print(f"  {name:<20} 捕获 {n} 个请求")

    print()
    print("=" * 78)
    print("② request.headers（常规 API）—— 逐页面给出")
    print("=" * 78)
    for c in captured:
        print(f"\n--- {c['page']} / {c['op']} ---")
        print(json.dumps(c["headers"], indent=2, ensure_ascii=False, sort_keys=True))

    print()
    print("=" * 78)
    print("③ all_headers() 比 headers 多出来的键")
    print("=" * 78)
    for c in captured:
        extra = {k: v for k, v in c["all_headers"].items() if k not in c["headers"]}
        print(f"  {c['page']:<20} 常规 {len(c['headers'])} 个键，all_headers {len(c['all_headers'])} 个键，"
              f"多出：{sorted(extra) if extra else '无'}")

    print()
    print("=" * 78)
    print("④ 跨页面差异：哪些头在不同页面取值不同")
    print("=" * 78)
    allkeys = set()
    for c in captured:
        allkeys |= set(c["headers"])
    for k in sorted(allkeys):
        vals = {}
        for c in captured:
            vals.setdefault(str(c["headers"].get(k)), []).append(c["page"])
        if len(vals) == 1:
            v = list(vals)[0]
            print(f"  [一致] {k:<24} = {v[:80]}")
        else:
            print(f"  [不同] {k}")
            for v, names in vals.items():
                print(f"          {names} -> {v[:80]}")

    print()
    print("=" * 78)
    print("⑤ 浏览器上下文里的 cookie")
    print("=" * 78)
    if not cookies:
        print("  无 cookie（站点未下发，或未持久化）")
    for ck in cookies:
        print(f"  {ck['name']:<26} domain={ck['domain']:<20} httpOnly={ck['httpOnly']} 长度={len(ck['value'])}")

    out = Path("tools/_probe_out.json")
    out.write_text(json.dumps(captured, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n原始记录已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
