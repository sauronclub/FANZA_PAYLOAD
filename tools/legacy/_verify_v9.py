# -*- coding: utf-8 -*-
"""验证 v9：A/B 对照 —— 注入 X-Forwarded-For 与不注入，对比 GraphQL 请求是否触发。"""
import time
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
URL = "https://video.dmm.co.jp/av/ranking/?term=realtime"


def trial(inject_header: bool):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=UA)
        if inject_header:
            ctx.set_extra_http_headers({"X-Forwarded-For": "202.214.23.45"})
        page = ctx.new_page()
        gql = [0]

        def handler(request):
            if request.method == "POST" and "api.video.dmm.co.jp/graphql" in request.url:
                gql[0] += 1

        page.on("request", handler)
        page.goto(URL, wait_until="domcontentloaded", timeout=70000)
        if "age_check" in page.url.lower():
            b = page.locator('a[href*="declared=yes"]')
            if b.count() > 0:
                b.first.click()
                page.wait_for_load_state("domcontentloaded", timeout=30000)
        page.wait_for_timeout(15000)
        # 记录该页实际发出的请求头里是否带了 X-Forwarded-For
        sent = []
        browser.close()
        return gql[0]


for inject in (True, False, True, False):
    n = trial(inject)
    print(f"注入 X-Forwarded-For = {inject!s:<5} -> 该页 GraphQL POST 请求数 = {n}")
