# -*- coding: utf-8 -*-
"""
验证 v8：
1) variables 值级别 diff（live vs 存档）
2) 同一 operation 在同一页是否触发多次（分页/批量），V1.02 只存第一次
3) 输出各排名页 filter 取值
"""
import json
import os
from collections import defaultdict, Counter
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

V102 = "D:/OneDrive/05-编程文件/FANZA/FANZA_PAYLOAD/GitHub Actions V1.02/PAYLOAD"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_out")

TARGETS = [
    ("ID",              "https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=snos00097/", "ContentPageData"),
    ("ACTRESS",         "https://video.dmm.co.jp/av/list/?actress=1087625",              "AvSearch"),
    ("REALTIME",        "https://video.dmm.co.jp/av/ranking/?term=realtime",             "ContentRankingPage"),
    ("REALTIME_VR",     "https://video.dmm.co.jp/av/ranking/?term=realtime&only=vr",      "ContentRankingPage"),
    ("DATE",            "https://video.dmm.co.jp/av/list/?date=2026-08-01",              "AvSearch"),
    ("DAILY",           "https://video.dmm.co.jp/av/ranking/?term=daily",                "ContentRankingPage"),
    ("WEEKLY",          "https://video.dmm.co.jp/av/ranking/?term=weekly",               "ContentRankingPage"),
    ("MONTHLY",         "https://video.dmm.co.jp/av/ranking/?term=monthly",              "ContentRankingPage"),
    ("MONTHLY_ACTRESS", "https://video.dmm.co.jp/av/ranking/?term=monthly&type=actress",  "ActressRankingPage"),
    ("MONTHLY_SERIES",  "https://video.dmm.co.jp/av/ranking/?term=monthly&type=series",   "SeriesRankingPage"),
    ("LATEST_RELEASE",  "https://video.dmm.co.jp/av/ranking/?release=latest",            "NewReleaseRankingPage"),
]

all_hits = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=UA)
    page = ctx.new_page()

    def handler(request):
        if request.method != "POST" or "api.video.dmm.co.jp/graphql" not in request.url:
            return
        raw = request.post_data or ""
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        all_hits.append({"page_url": page.url, "op": parsed.get("operationName"),
                         "parsed": parsed, "raw": raw, "headers": dict(request.headers)})

    page.on("request", handler)
    for name, url, op in TARGETS:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=70000)
        except Exception:
            continue
        if "age_check" in page.url.lower():
            b = page.locator('a[href*="declared=yes"]')
            if b.count() > 0:
                b.first.click(); page.wait_for_load_state("domcontentloaded", timeout=30000)
        page.wait_for_timeout(10000)
    page.wait_for_timeout(8000)
    browser.close()

json.dump([{k: v for k, v in h.items()} for h in all_hits],
          open(os.path.join(OUT, "all_hits_v8.json"), "w", encoding="utf-8"),
          indent=2, ensure_ascii=False)

# 按 page_url 分组统计每个 op 出现次数
print("=" * 88)
print("每个页面上各 operation 的触发次数：")
bypage = defaultdict(Counter)
for h in all_hits:
    bypage[h["page_url"]][h["op"]] += 1
for u in sorted(bypage):
    print(f"\n  {u}")
    for op, c in bypage[u].most_common():
        mark = "  <== 多次触发!" if c > 1 else ""
        print(f"     {op:<26} x{c}{mark}")

print("\n" + "=" * 88)
print("variables 值级别 diff（live vs 存档）")
print("=" * 88)
for name, url, op in TARGETS:
    cands = [h for h in all_hits if h["op"] == op and h["page_url"] == url] \
            or [h for h in all_hits if h["op"] == op]
    if not cands:
        print(f"[{name}] 未观察到"); continue
    # 同页同 op 全部请求的 variables 差异
    uniq = []
    for h in cands:
        v = h["parsed"].get("variables")
        if v not in uniq:
            uniq.append(v)
    sp = os.path.join(V102, f"PAYLOAD_{name}.json")
    if not os.path.exists(sp):
        print(f"[{name}] 无存档"); continue
    sv = json.load(open(sp, encoding="utf-8")).get("variables")
    lv = uniq[0]
    # 逐键比较
    diffs = {}
    for k in set(list(lv or {}) + list(sv or {})):
        if lv.get(k) != sv.get(k):
            diffs[k] = {"live": lv.get(k), "saved": sv.get(k)}
    print(f"[{name}] 该页 {op} 出现的不同 variables 组合数: {len(uniq)}")
    if diffs:
        print(f"   >>> 值差异: {json.dumps(diffs, ensure_ascii=False)}")
    else:
        print("   >>> 第一组 variables 与存档完全一致（值级别）")
    if len(uniq) > 1:
        print(f"   >>> 注意：存在多组不同 variables（V1.02 只会保存第一组）")

print("\n" + "=" * 88)
print("各排名页 filter 取值：")
seen = set()
for name, url, op in TARGETS:
    for h in all_hits:
        if h["op"] == op and h["page_url"].startswith(url.split("?")[0]) :
            f = (h["parsed"].get("variables") or {}).get("filter")
            key = (name, json.dumps(f, ensure_ascii=False, sort_keys=True))
            if key not in seen and f is not None:
                seen.add(key)
                print(f"  [{name}] filter = {json.dumps(f, ensure_ascii=False)}")
            break
print("\n输出目录:", OUT)
