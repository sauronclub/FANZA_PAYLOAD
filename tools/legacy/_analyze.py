# -*- coding: utf-8 -*-
"""离线精确分析 all_hits_v8.json：按精确 page_url 映射，做 filter/值级别 diff。"""
import json, os
from collections import defaultdict, Counter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_out")
V102 = "D:/OneDrive/05-编程文件/FANZA/FANZA_PAYLOAD/GitHub Actions V1.02/PAYLOAD"

hits = json.load(open(os.path.join(OUT, "all_hits_v8.json"), encoding="utf-8"))

# 精确 page_url -> payload 名称
MAP = {
    "https://video.dmm.co.jp/av/content/?id=snos00097": "ID",
    "https://video.dmm.co.jp/av/list/?actress=1087625": "ACTRESS",
    "https://video.dmm.co.jp/av/ranking/?term=realtime": "REALTIME",
    "https://video.dmm.co.jp/av/ranking/?term=realtime&only=vr": "REALTIME_VR",
    "https://video.dmm.co.jp/av/list/?date=2026-08-01": "DATE",
    "https://video.dmm.co.jp/av/ranking/?term=daily": "DAILY",
    "https://video.dmm.co.jp/av/ranking/?term=weekly": "WEEKLY",
    "https://video.dmm.co.jp/av/ranking/?term=monthly": "MONTHLY",
    "https://video.dmm.co.jp/av/ranking/?term=monthly&type=actress": "MONTHLY_ACTRESS",
    "https://video.dmm.co.jp/av/ranking/?term=monthly&type=series": "MONTHLY_SERIES",
    "https://video.dmm.co.jp/av/ranking/?release=latest": "LATEST_RELEASE",
}
OP = {
    "ID": "ContentPageData", "ACTRESS": "AvSearch", "REALTIME": "ContentRankingPage",
    "REALTIME_VR": "ContentRankingPage", "DATE": "AvSearch", "DAILY": "ContentRankingPage",
    "WEEKLY": "ContentRankingPage", "MONTHLY": "ContentRankingPage",
    "MONTHLY_ACTRESS": "ActressRankingPage", "MONTHLY_SERIES": "SeriesRankingPage",
    "LATEST_RELEASE": "NewReleaseRankingPage",
}

by_page = defaultdict(list)
for h in hits:
    by_page[h["page_url"]].append(h)

print("=" * 90)
print("① 每个排名页的 filter（实测 live vs 存档）")
print("=" * 90)
for url, name in MAP.items():
    op = OP[name]
    recs = [h for h in by_page.get(url, []) if h["op"] == op]
    if not recs:
        print(f"[{name}] 该页未观察到 {op}")
        continue
    lv_filter = (recs[0]["parsed"].get("variables") or {}).get("filter")
    sp = os.path.join(V102, f"PAYLOAD_{name}.json")
    sv_filter = json.load(open(sp, encoding="utf-8"))["variables"].get("filter") if os.path.exists(sp) else None
    flag = "  ✔一致" if lv_filter == sv_filter else "  ✘不同!"
    print(f"[{name:<16}] {op}")
    print(f"   live  filter: {json.dumps(lv_filter, ensure_ascii=False)}{flag}")
    if lv_filter != sv_filter:
        print(f"   存档  filter: {json.dumps(sv_filter, ensure_ascii=False)}")

print()
print("=" * 90)
print("② 值级别 diff（精确映射，live 同页同 op 的首条 vs 存档）")
print("=" * 90)
for url, name in MAP.items():
    op = OP[name]
    recs = [h for h in by_page.get(url, []) if h["op"] == op]
    if not recs:
        continue
    lv = recs[0]["parsed"].get("variables") or {}
    sp = os.path.join(V102, f"PAYLOAD_{name}.json")
    if not os.path.exists(sp):
        continue
    sv = json.load(open(sp, encoding="utf-8")).get("variables") or {}
    diffs = {k: {"live": lv.get(k), "saved": sv.get(k)}
             for k in set(list(lv) + list(sv)) if lv.get(k) != sv.get(k)}
    print(f"[{name:<16}] 键集合一致: {sorted(lv)==sorted(sv)} | 值差异: {json.dumps(diffs, ensure_ascii=False) if diffs else '无'}")

print()
print("=" * 90)
print("③ 每页同 op 的触发次数（>1 说明有分页/批量，V1.02 只存首次）")
print("=" * 90)
for url, name in MAP.items():
    op = OP[name]
    n = len([h for h in by_page.get(url, []) if h["op"] == op])
    print(f"[{name:<16}] {op:<24} x{n}" + ("   <== 多次!" if n > 1 else ""))

print()
print("=" * 90)
print("④ 全部请求的顶层字段集合 / extensions 统计")
print("=" * 90)
ks = Counter(tuple(sorted(h["parsed"].keys())) for h in hits)
for k, c in ks.most_common():
    print(f"   {list(k)}  x{c}")
print("含 extensions 的请求数:", sum(1 for h in hits if "extensions" in h["parsed"]))
print("请求头集合:")
for k, c in Counter(tuple(sorted(h["headers"].keys())) for h in hits).most_common():
    print(f"   {list(k)}  x{c}")
print("\n全部 GraphQL 请求总数:", len(hits))
