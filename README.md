# FANZA GraphQL Payload 捕获器

从 FANZA（DMM）各榜单 / 清单 / 详情页面中捕获前端发出的 GraphQL 请求，
按页面输出两个文件：

* `PAYLOAD/*.json` —— **纯净的负载内容**（就是服务端原样收到的请求体）
* `HEADERS/*.json` —— 该请求的**请求头**

本版本为 **生产级重构版**：分层架构、分级日志、全量捕获、可选飞书告警、
可选 Cloudflare R2 上传，目标运行环境是 **日本 VPS**（不再依赖 GitHub Actions）。

---

## 目录结构

```
.
├── main.py                      # 程序入口（CLI + 依赖装配）
├── requirements.txt
├── config/
│   ├── pages.py                 # ★ 页面清单（增删页面只改这里）
│   └── logging.py               # ★ 日志配置（级别 / 滚动 / 保留期）
├── src/
│   ├── core/                    # 基础设施：配置、模型、异常、常量
│   │   ├── constants.py
│   │   ├── exceptions.py
│   │   ├── models.py
│   │   ├── pyconfig.py          #   Python 配置模块安全加载器
│   │   ├── page_registry.py
│   │   └── settings.py
│   ├── logkit/                  # 日志：初始化、分级过滤器、滚动处理器
│   │   ├── setup.py
│   │   ├── filters.py
│   │   └── handlers.py
│   ├── browser/                 # 浏览器生命周期 + 年龄验证
│   │   ├── manager.py
│   │   └── age_gate.py
│   ├── capture/                 # 捕获核心
│   │   ├── listener.py          #   请求监听与收集
│   │   ├── extractor.py         #   请求体 / 请求头提取
│   │   └── page_capturer.py     #   单页流程编排
│   ├── storage/                 # 输出：路径规划 + 原子写
│   │   ├── layout.py
│   │   └── writer.py
│   ├── notify/                  # 通知：飞书
│   │   ├── base.py
│   │   └── feishu.py
│   ├── upload/                  # 上传：Cloudflare R2（S3 兼容）
│   │   ├── base.py              #   接口与空实现
│   │   ├── sigv4.py             #   AWS SigV4 签名（纯标准库，无第三方依赖）
│   │   └── r2.py                #   R2 客户端与上传实现
│   └── runner/                  # 编排：批量执行、重试、上传、摘要
│       ├── orchestrator.py
│       └── summary.py
├── scripts/
│   ├── run.sh                   # 手动运行
│   ├── fanza-payload.service    # systemd 服务
│   └── fanza-payload.timer      # systemd 定时器
├── logs/                        # 运行日志（自动滚动）
├── PAYLOAD/                     # 捕获结果：纯净负载
├── HEADERS/                     # 捕获结果：请求头
├── docs/                        # 设计与验证文档
└── tools/                       # 运维与开发脚本（非运行依赖）
    ├── check_r2.py              #   R2 连通性与权限自检（只读诊断）
    ├── selftest.py              #   组件自检（不触网）
    ├── verify_upload_e2e.py     #   端到端验证：抓取 + 上传（替身客户端）
    ├── verify_r2_objects.py     #   核对远端对象与本地文件是否逐字节一致
    ├── probe_headers.py         #   实机探测请求头全貌
    └── legacy/                  #   早期验证脚本与原始证据（按需复跑）
```

---

## 快速开始（本机）

```bash
# 1. 准备虚拟环境
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. 安装依赖与浏览器
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium   # 仅 Linux 需要

# 3. 配置
cp .env.example .env               # 填入 GRAPHQL_API_URL 与飞书 webhook

# 4. 校验配置（不会启动浏览器）
python main.py --validate

# 5. 查看页面清单
python main.py --list

# 6. 正式捕获
python main.py
```

> **运行报 `ModuleNotFoundError`？** 说明当前解释器缺依赖。
> 在 Trae 的终端里用**同一个** Python 执行
> `python -m pip install -r requirements.txt`（或 `pip install playwright python-dotenv requests`）。
> 本项目已不再依赖 PyYAML —— 配置全部是 Python 文件。

---

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--list` | 列出页面清单后退出 |
| `--validate` | 仅校验配置（.env / pages.py / logging.py）后退出 |
| `--only NAME[,NAME]` | 只运行指定页面（名称不区分大小写） |
| `--tag TAG` | 只运行带指定标签的页面（如 `ranking`） |
| `--headful` | 以有界面模式运行，便于本机调试 |
| `--no-notify` | 本次不推送通知 |
| `--no-upload` | 本次不上传到 Cloudflare R2 |
| `--log-level LEVEL` | 覆盖控制台日志级别（DEBUG / INFO / WARNING / ERROR） |
| `--config-dir PATH` | 指定配置目录 |

**退出码**：`0` 全部成功 ｜ `1` 存在失败 ｜ `2` 致命错误（配置或浏览器不可用）

---

## 配置说明

### 1. `config/pages.py` —— 页面清单

新增 / 停用页面**只需改这一个文件**，无需改代码。

```python
PAGES = [
    {
        "name": "RANKING_DAILY",        # 唯一标识，日志与 --only 使用
        "url": "https://video.dmm.co.jp/av/ranking/?term=daily",
        "operation_name": "ContentRankingPage",
        "output": "PAYLOAD_DAILY.json",  # 落在 PAYLOAD/ 下
        "tags": ["ranking"],             # 可选，配合 --tag 批量筛选
        "description": "每日排行榜",      # 可选，中文备注
    },
    # ...
]
```

可选字段：

| 字段 | 说明 |
|---|---|
| `url_env` | 用环境变量提供地址（与 `url` 二选一），适合不想把地址写进仓库 |
| `headers_output` | 请求头文件名；不填时由 `output` 自动推导（`PAYLOAD_X.json` → `HEADERS_X.json`） |
| `enabled` | `False` 表示本次跳过（配置保留） |
| `settle_ms` | 捕获到目标请求后额外等待的毫秒数，用于收集同页后续请求 |
| `timeout_ms` | 覆盖默认的「等待 GraphQL 请求」超时（毫秒） |

写错字段名、`name`/`output` 重复、`url` 与 `url_env` 冲突、类型不对——
都会在**启动时立刻报错**，不会带着错误配置跑到一半才失败。

> ⚠️ `AvSearch` 被 4 个页面共用（演员 / 演员+类型 / 系列 / 日期），
> 因此**必须按页面维度管理**，不能靠 `operationName` 区分。

**为什么用 Python 而不是 YAML？**
编辑器语法高亮 / 缩进提示 / 拼写检查直接生效，改错一眼可见；
不引入额外解析库（少一个环境差异点）；可以写注释和变量。
`config/logging.py` 同理，它只做一件事——返回 `dictConfig` 需要的字典。

### 2. `.env` —— 环境与私密配置

| 变量 | 说明 |
|---|---|
| `GRAPHQL_API_URL` | GraphQL 端点（必填） |
| `FEISHU_GROUP_BOT_WEBHOOK_URL` | 飞书群机器人 webhook，留空则不推送 |
| `FEISHU_SIGN_SECRET` | 机器人开启「签名校验」时的密钥 |
| `R2_ACCOUNT_ID` | Cloudflare 账户 ID，用于拼出 R2 端点 |
| `R2_ENDPOINT` | 自定义 / 区域端点（优先级高于 `R2_ACCOUNT_ID`） |
| `R2_BUCKET` | 存储桶名称 |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | R2 API 令牌密钥对 |
| `R2_PREFIX` | 可选，对象键的顶层前缀；桶名已能区分内容时**建议留空**，避免 `fanza/PAYLOAD/...` 这类冗余层级 |
| `BROWSER_HEADLESS` | 是否无头模式，VPS 上保持 `true` |
| `BROWSER_PROXY` | 可选代理，如 `http://127.0.0.1:7890` |
| `PAGE_WAIT_SECONDS` | 单页等待 GraphQL 请求的最长秒数（默认 45） |
| `MAX_RETRY` | 单页最大重试次数（默认 3） |
| `LOG_LEVEL` | 覆盖控制台日志级别，留空用 `config/logging.py` 的默认值 |

### 3. `config/logging.py` —— 日志

顶部「可调参数」区就能改完全部行为：

```python
CONSOLE_LEVEL = "INFO"        # 控制台级别
FILE_LEVEL = "DEBUG"          # 文件级别（全量留存）
ROLLOVER_WHEN = "midnight"    # 每天 0 点滚动
MAX_BYTES = 10 * 1024 * 1024  # 单文件上限 10 MiB，超出立即滚动
RETENTION_DAYS = 30           # 归档保留 30 天，超期自动删除
THIRD_PARTY_LEVELS = {"playwright": "WARNING", "urllib3": "WARNING"}
```

* **分级**：控制台输出 `INFO` 及以上；日志文件记录 `DEBUG` 及以上全量；
* **上下文**：每条日志带本次运行的 `run_id`，便于按批次检索。

---

## 输出格式

### `PAYLOAD/` —— 纯净负载

每个页面一个文件，内容就是**服务端原样收到的 GraphQL 请求体**，
不做任何包装、不裁剪、不重排（与 V1.02 的格式完全一致）：

```json
{
  "operationName": "ContentRankingPage",
  "query": "query ContentRankingPage(...) { ... }",
  "variables": { "filter": { "daily": { "floor": "AV" } }, "...": "..." }
}
```

> 因为写的是**原始请求体**，服务端今后新增任何顶层字段（`extensions`、
> `persistedQuery` 等）都会被自动保留 —— 「漏参数」在结构上不可能再发生。

### `HEADERS/` —— 请求头

文件名与负载一一对应（`PAYLOAD_X.json` ↔ `HEADERS_X.json`），内容就是**完整请求头**：

```json
{
  "accept": "application/graphql-response+json, application/graphql+json, application/json, ...",
  "accept-encoding": "gzip, deflate, br, zstd",
  "accept-language": "ja-JP",
  "content-length": "2122",
  "content-type": "application/json",
  "cookie": "i3_ab=...; age_check_done=1; ...",
  "fanza-device": "BROWSER",
  "origin": "https://video.dmm.co.jp",
  "referer": "https://video.dmm.co.jp/",
  "sec-ch-ua": "\"Chromium\";v=\"141\", ...",
  "user-agent": "Mozilla/5.0 ..."
}
```

两点要知道：

* 使用 Playwright 的 `all_headers()` 获取**完整头集合**，而非 `request.headers`
  （后者只给约 9 个「常规」头，**会丢掉 `cookie`**，导致无法重放请求）。
* 仅剔除 HTTP/2 伪头（`:authority` / `:method` / `:path` / `:scheme`）——
  它们由协议帧承载、客户端自动生成，不是可重放的 HTTP 头。

> **13 个页面的请求头几乎完全相同，这是正常的，不是 bug。**
> 这些头都是浏览器级 / 站点级常量（`accept-language`、`user-agent`、
> `fanza-device`、站点根 `referer` …），本身不含页面路径信息。
> 真正区分页面的是 `PAYLOAD` 里的 `variables`（`filter` / `sort` 等）；
> 请求头里唯一可能随会话变化的只有 `cookie`。

同一页面若目标 operation 触发多次（翻页、批量加载），
第 2 条及之后另存为 `PAYLOAD_X__2.json` / `HEADERS_X__2.json`，
**主文件名恒定不变**，下游按固定名字读取不受影响，且不丢数据。

---

## 上传到 Cloudflare R2

未配置时自动跳过；配齐后每轮运行结束会把**本轮写出的文件**推到 R2，
远端同名对象被覆盖 —— 云端始终保有各页面的最新一版。

**零额外依赖**：不使用官方 SDK `boto3`，而是由 `src/upload/sigv4.py`
用标准库（`hashlib` / `hmac`）+ 已有的 `requests` 自行完成 AWS SigV4 签名。
好处是本机与 VPS 都不必再装任何东西 —— 换机器、换解释器都不会再遇到
「缺少 boto3」这类报错。签名正确性由 `tools/selftest.py` 的官方测试向量与
真实 R2 上传共同保证。

### 1. 在 Cloudflare 侧准备

1. **建桶**：R2 → Create bucket，记下桶名。
2. **建 API 令牌**：R2 → API → Manage API tokens → Create API token，
   权限选 **Object Read & Write**，范围限定到该桶；记下
   `Access Key ID` 与 `Secret Access Key`（Secret 只显示一次）。
3. **记下账户 ID**：R2 概览页右侧的 Account ID，
   端点即 `https://<AccountID>.r2.cloudflarestorage.com`。

### 2. 填入 `.env`

```dotenv
R2_ACCOUNT_ID=<你的账户 ID>
R2_BUCKET=<桶名>
R2_ACCESS_KEY_ID=<Access Key ID>
R2_SECRET_ACCESS_KEY=<Secret Access Key>
R2_PREFIX=                     # 可选，留空则直接放在桶根目录
```

> 这一组**要么全填、要么全空**。只填一半会在启动时直接报错，
> 避免「以为在上传、其实静默跳过」。

### 3. 先自检连通性（推荐）

```bash
python tools/check_r2.py
```

只读诊断，依次检查四项：配置是否齐全 → 凭据是否有效 → 桶能否访问 →
写入权限（上传一个探测对象后立即删除）。密钥在输出中自动打码。

输出里若看到 `ListBuckets ... AccessDenied`，**属于正常现象** ——
R2 的令牌若只授权到某个具体桶，就不允许列举桶列表，这与凭据本身是否
有效无关，以第 ③ 步（`HeadBucket`）的结果为准。

### 4. 对象键结构

保持与本地一致的目录层级（`R2_PREFIX` 非空时作为顶层前缀）：

```
PAYLOAD/PAYLOAD_DAILY.json
PAYLOAD/PAYLOAD_SERIES.json
HEADERS/HEADERS_DAILY.json
HEADERS/HEADERS_SERIES.json
...
```

### 5. 行为说明

| 场景 | 表现 |
|---|---|
| 上传成功 | 日志 `上传完成：N 个文件全部成功`，摘要与飞书含上传统计 |
| 单个文件失败 | 自动重试 **3 次**；仍失败则记录 ERROR 并列入摘要，**不影响本地文件与退出码** |
| 未配置 / `--no-upload` | 日志提示跳过，摘要标注「未启用上传，跳过 N 个文件」 |
| 仅部分页失败 | 失败页不产出文件，成功页照常上传 |

上传在**浏览器关闭之后**执行，不与抓取争抢资源。
除已有的 `requests` 外**不引入任何新依赖**。

### 6. 复核脚本

```bash
python tools/check_r2.py             # 连通性 / 权限自检（含写入干跑，自动清理）
python tools/verify_r2_objects.py    # 远端对象与本地逐字节比对 + 结构校验
```

两个脚本都只用项目自身的 `R2Client`，无需 boto3；`verify_r2_objects.py`
在发现不一致时以退出码 1 结束，可直接串进 CI 或定时任务。

---

## 与 V1.02 的差异

| 项目 | V1.02 | 本版本 |
|---|---|---|
| 页面清单 | 硬编码在 `handlers.py` + `.env` | `config/pages.py` 集中管理 |
| 页面数量 | 11 | 13（新增演员+类型、系列详情） |
| 请求头 | **未保存** | 输出到 `HEADERS/`（完整头，含 `cookie`） |
| 云端备份 | 无 | 可选上传 Cloudflare R2 |
| 负载格式 | 三键纯净 JSON | **同 V1.02**（原始请求体，纯净） |
| 重复请求 | 只保存第一个 | 全部保存（`__2`、`__3`…） |
| 日志 | 仅控制台，单一级别 | 分级 + 滚动文件 + 保留期 + run_id |
| 告警 | 无 | 飞书运行摘要 |
| 调度 | GitHub Actions | systemd timer（日本 VPS） |
| 配置格式 | YAML | **Python 模块**（无需 PyYAML） |
| 可测试性 | 逻辑耦合 | 分层解耦，`tools/selftest.py` 一键自检 |

---

## VPS 部署（systemd）

以 Debian / Ubuntu 为例，部署到 `/opt/fanza-payload`：

```bash
# 1. 创建专用用户（不建议用 root 跑浏览器）
sudo useradd --create-home --shell /usr/sbin/nologin fanza

# 2. 拉取代码
sudo mkdir -p /opt/fanza-payload
sudo chown -R fanza:fanza /opt/fanza-payload
sudo -u fanza git clone <你的仓库地址> /opt/fanza-payload

# 3. 安装依赖
cd /opt/fanza-payload
sudo -u fanza python3 -m venv .venv
sudo -u fanza .venv/bin/pip install -r requirements.txt
sudo -u fanza .venv/bin/playwright install chromium
sudo .venv/bin/playwright install-deps chromium     # 安装系统级依赖库

# 4. 配置
sudo -u fanza cp .env.example .env
sudo -u fanza vi .env                               # 填入 webhook 等

# 5. 手动验证一次
sudo -u fanza ./scripts/run.sh --validate
sudo -u fanza ./scripts/run.sh --only RANKING_DAILY

# 6. 安装 systemd 单元
sudo cp scripts/fanza-payload.service /etc/systemd/system/
sudo cp scripts/fanza-payload.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fanza-payload.timer

# 7. 查看状态与日志
systemctl list-timers fanza-payload.timer
journalctl -u fanza-payload.service -n 100 --no-pager
```

> 定时器默认 **每天日本时间 01:00** 触发（`OnCalendar` 已显式带时区，
> 不受 VPS 系统时区影响）。修改时间请编辑 `scripts/fanza-payload.timer`。

### 常用运维命令

```bash
# 立即手动跑一次（走 systemd，会记录到 journal）
sudo systemctl start fanza-payload.service

# 查看应用自身日志文件（含 DEBUG 全量）
tail -f logs/fanza_payload.log

# 校验定时器下次触发时间
systemctl list-timers fanza-payload.timer
```

---

## 自检

```bash
python tools/selftest.py
```

覆盖日志滚动 / 保留期清理 / 日志配置构建 / 页面清单校验 / 输出布局 /
飞书报文与签名 / 请求头提取（伪头剔除、`cookie` 保留）/ R2 配置校验与
上传器行为（重试、失败收敛），共 80+ 项断言，全程不触网。

端到端（含真实上传）与 R2 诊断：

```bash
python tools/verify_upload_e2e.py    # 真实抓取 + 替身客户端验证上传链路
python tools/check_r2.py             # 真实 R2 连通性与权限自检
python tools/verify_r2_objects.py    # 真实 R2 对象与本地逐字节比对
```

---

## 故障排查

| 现象 | 排查方向 |
|---|---|
| `ModuleNotFoundError: No module named 'playwright'`（或 dotenv / requests） | 用**当前解释器**执行 `python -m pip install -r requirements.txt` |
| `浏览器启动失败` | 执行 `playwright install chromium` 与 `playwright install-deps chromium` |
| 某页 `等待 N 秒仍未捕获到 ...` | 用 `--headful` 观察页面是否弹验证码 / 网络异常；查看日志中的 `已出现的业务 operation` |
| 频繁触发重试 | 调大 `.env` 的 `PAGE_WAIT_SECONDS`；或临时 `BROWSER_PROXY` 换出口 IP |
| 飞书未收到消息 | 确认 `.env` 的 webhook；机器人若开签名校验需填 `FEISHU_SIGN_SECRET` |
| `R2 配置不完整` | 该组变量要求全填或全空，按报错提示补齐 `R2_*` |
| 上传报 403 / SignatureDoesNotMatch | 先跑 `python tools/check_r2.py`；核对 Account ID 是否与令牌所属账户一致，令牌权限需含 Object Read & Write |
| `ListBuckets ... AccessDenied` | **正常现象**，令牌只授权到具体桶时不允许列举桶；以 `HeadBucket` 结果为准 |
| 摘要显示「未启用上传」但你已配置 | 检查 `R2_ACCOUNT_ID`（或 `R2_ENDPOINT`）与桶名是否漏填 |
| 年龄验证页卡住 | 查看日志「年龄验证」相关行；确认目标站点结构未变更 |
| 配置文件报错 | 报错会带 `config/pages.py` 的行号与原因，按提示改即可 |
