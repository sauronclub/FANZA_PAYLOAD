# GraphQL Payload 捕获逻辑 —— 验证报告

**验证对象**：`GitHub Actions V1.02`（`src/capture.py` 为主）
**验证方式**：用 Playwright 实机复现 11 个目标页面，抓取**完整原始请求体 + 请求头**，再与仓库内已保存的 `PAYLOAD_*.json` 逐字段对比。
**验证时间**：2026-10-15

---

## 一、V1.02 是怎么捕获的

`src/capture.py` 的核心是一个挂到 `page.on("request")` 的监听器：

```python
def handler(request):
    if request.method != "POST": return          # 只收 POST
    if settings.GRAPHQL_API_URL not in request.url: return   # 只收该 GraphQL 端点
    if not request.post_data: return             # 必须有 body
    post_data = json.loads(request.post_data)
    op = post_data.get("operationName")
    if op in self._current_operations and self.payload_request is None:
        self.payload_request = {                 # ← 只挑 3 个字段
            "operationName": op,
            "query":         post_data.get("query"),
            "variables":     post_data.get("variables"),
        }
        self._save_payload(self.payload_request, filepath)   # 命中即落盘
```

要点：

1. **按 `operationName` 白名单匹配**（`config.py` 里的 `TARGET_OPERATIONNAME_*`），每个页面只认 1 个目标 op。
2. **只保存请求体的 3 个顶层字段**：`operationName` / `query` / `variables`。
3. **只保存"第一个"命中请求**（`self.payload_request is None` 守卫）。
4. **完全不保存请求头**。
5. 页面导航 → 过年龄验证 → 等标题元素或超时（`SELECTOR_TIMEOUT` / `WAIT_GRAPHQL`）。

---

## 二、实测结论：请求体没有漏参数

一轮完整访问共观察到 **59 个** `POST https://api.video.dmm.co.jp/graphql` 请求：

| 检查项 | 实测结果 |
|---|---|
| 顶层字段集合 | **全部 59 个都是 `['operationName','query','variables']`**，只有这一种 |
| 含 `extensions` 的请求 | **0 个**（Apollo 持久化查询等场景常见的字段，此处不存在） |
| `variables` 键集合 | 11 个页面**全部与存档一致** |
| `variables` 值（含 `filter`） | 11 个页面**全部与存档一致（值级别）** |
| `query` 字符串 | 11 个页面**全部与存档逐字相同** |

各排名页 `filter` 实测值（均与存档一致，说明没有串页/串参）：

```
REALTIME       {"trending": {"contentType": "TWO_DIMENSION", "floor": "AV"}}
REALTIME_VR    {"trending": {"contentType": "VR",            "floor": "AV"}}
DAILY          {"daily":    {"floor": "AV"}}
WEEKLY         {"weekly":   {"floor": "AV"}}
MONTHLY        {"monthly":  {"floor": "AV"}}
ACTRESS        {"actressIds": {"ids":[{"id":"1087625"}], "op":"AND"}, "isSaleItemsOnly": false}
DATE           {"deliveryStartDate": "2026-08-01", "isSaleItemsOnly": false}
```

> **结论：你怀疑的"body 里漏参数"不成立。** 就当前这些页面/操作而言，V1.02 保存的 3 个字段已覆盖服务端实际发送的全部顶层字段，且值完全一致。

---

## 三、但确实存在 4 处真实的"漏"，只是不在 body 里

### 缺口 1（最重要）：请求头完全没保存

实测每个 GraphQL 请求**都**带这些头，V1.02 一个都没记：

```
content-type: application/json
accept: application/graphql-response+json, application/graphql+json, application/json, text/event-stream, multipart/mixed
fanza-device: BROWSER        ← DMM 自定义头
referer / user-agent / accept-language / sec-ch-ua* 
```

其中 `fanza-device: BROWSER` 是 DMM 自定义头，**重放请求时很可能必须带上**。V1.02 的 `.env` 里虽然配了 `HEADER_KEY/HEADER_VALUE`（= `X-Forwarded-For`），但那是**往请求里注入**一个头，不是**保存**服务端要求的头，方向反了。

### 缺口 2：只保存"首个"命中请求

`self.payload_request is None` 这个守卫意味着：同一页内同一 op 触发第 2 次时（例如用户翻页 / 无限滚动，`variables.offset` 变化）会被**静默丢弃**。
本次实测中 11 个页面每个 op 都只触发 **1 次**，所以暂时没造成损失；但这是结构性隐患——**一旦页面加载时批量请求，就会漏**。

### 缺口 3：`.env` 里有个页面根本没被采集

`.env` 第 8 行有：

```
TYPE_ACTRESS_GENRE_URL=https://video.dmm.co.jp/av/list/?actress=1099472&genre=4025
```

而 `config.py` 里**没有这个变量**，`handlers.py` 的 `get_capture_configs()` 里也**没有任何 CaptureConfig 对应它**。→ 这个"女优+类型"组合页被整页漏抓。

### 缺口 4：每个页面的其余 op 未采集（需确认是否为设计意图）

实测每页除了目标 op，还会有：

```
LegacyGuestId / Root / Maintenance / SideBar / PromotionBanners / RecentlyViewedContents
```

其中 `Root`、`LegacyGuestId` 可能携带初始化/游客态参数。若下游需要它们，目前是拿不到的。

---

## 四、附带澄清（避免误判）

1. **`X-Forwarded-For` 不是问题。** 我最初怀疑注入它会导致 GraphQL 不触发，做了 A/B 对照：注入与不注入，每页都是 **5 个** GraphQL 请求。该头**对结果无影响**，只是冗余配置。
2. **存档不是陈旧的。** 11 个存档与实测的 `query` 字符串逐字相同，说明 V1.02 存档是当前版本的。
3. 关于"滞后一拍"：同一浏览器上下文里连续访问，请求会滞后到下一页才落网——这是**我验证脚本的时序问题**，不是 V1.02 的代码缺陷。

---

## 五、建议改动（按优先级）

1. **补存请求头**：把 `request.headers` 一并写入 payload（或至少存 `fanza-device` / `accept` / `content-type`）。
2. **改"只存首个"为"存全部"**：按 `operationName` 收集成列表，或按 `(operationName, offset)` 去重保存。
3. **补上漏掉的页面**：在 `config.py` + `handlers.py` + `PAYLOAD.yml` 中增加 `TYPE_ACTRESS_GENRE_URL` 对应项。
4. **清理无效配置**：`.env` 的 `HEADER_KEY/HEADER_VALUE` 实测无效，可移除或改作正式用途。
