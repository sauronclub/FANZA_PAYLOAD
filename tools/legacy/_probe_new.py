# -*- coding: utf-8 -*-
"""实测两个新增页面的 GraphQL operationName / variables / filter。"""
import json, os, time
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_out")
os.makedirs(OUT, exist_ok=True)

TARGETS = [
    ("ACTRESS_SOLO", "https://video.dmm.co.jp/av/list/?actress=1087625&genre=4025"),
    ("SERIES",       "https://video.dmm.co.jp/av/list/?series=5087&sort=date"),
    ("DATE_1001",    "https://video.dmm.co.jp/av/list/?date=2026-10-01"),
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=UA)
    page = ctx.new_page()
    hits = []

    def handler(request):
        if request.method != "POST" or "api.video.dmm.co.jp/graphql" not in request.url:
            return
        raw = request.post_data or ""
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        hits.append({"page_url": page.url, "op": parsed.get("operationName"),
                     "parsed": parsed, "headers": dict(request.headers)})

    page.on("request", handler)

    for name, url in TARGETS:
        hits.clear()
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        if "age_check" in page.url.lower():
            b = page.locator('a[href*="declared=yes"]')
            if b.count() > 0:
                b.first.click(); page.wait_for_load_state("domcontentloaded", timeout=30000)
        page.wait_for_timeout(9000)
        page.wait_for_timeout(9000)
        print(f"\n=== [{name}] {url}")
        print(f"    page.url = {page.url}")
        for h in hits:
            if h["op"] in ("LegacyGuestId", "Root", "Maintenance", "SideBar", "PromotionBanners"):
                continue
            v = h["parsed"].get("variables") or {}
            print(f"    op={h['op']}")
            print(f"      variables keys: {sorted(v.keys())}")
            print(f"      filter: {json.dumps(v.get('filter'), ensure_ascii=False)}")
            print(f"      query 长度: {len(h['parsed'].get('query') or '')}")
            print(f"      body 顶层字段: {list(h['parsed'].keys())}")
            print(f"      请求头: {sorted(h['headers'].keys())}")
            with open(os.path.join(OUT, f"new_{name}.json"), "w", encoding="utf-8") as f:
                json.dump(h["parsed"], f, indent=2, ensure_ascii=False)
        if not hits:
            print("    未捕获任何 GraphQL 请求")
    browser.close()

print("\n输出目录:", OUT)
