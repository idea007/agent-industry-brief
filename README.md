# 行业新闻简报

行业新闻简报帮助用户快速了解感兴趣行业的最新动态：选择预置行业或创建自定义主题，系统
结合行业定向新闻源、用户自定义来源和 AI 信息探测，发现最新消息，并把每一篇值得关注
的新闻整理成一张带摘要、重要度、可信度和来源依据的卡片。

产品的核心不是展示 Agent 如何运行，而是让用户更快回答三个问题：

- 这个行业最近发生了什么？
- 哪些新闻值得我现在关注？
- 结论来自哪里，是否可信？

产品定义与工程约束：

- [项目架构](docs/项目架构.md)
- [开发原则](docs/开发原则.md)
- [设计规范](docs/设计规范.md)

## 当前产品闭环

```text
选择行业或自定义主题
→ 读取行业来源策略
→ 采集 RSS / Atom / 公开网页 / 用户来源
→ AI 扩展探测并筛选相关内容
→ 去重、正文提取与安全清洗
→ 相关性/新颖度评分、事件聚类与独立证据链识别
→ AI 生成摘要、关键事实、重要度和可信度
→ 事实级引用与 Eval 硬门禁
→ 同一新闻事件生成一张主卡
→ 点击卡片阅读引用、时间线、变化摘要并提交可撤销反馈
```

Agent Runtime、Tool Policy、Eval、Event Log 和 Approval 仍作为服务端可靠性机制保留，
但只出现在辅助诊断和工程文档中，不构成普通用户的主要操作路径。

## 当前能力

- 十三个预置行业，可选择一个或多个关注领域。
- 分行业配置的核心来源、行业来源、关键词和 AI 探测查询。
- 自定义 RSS、网站和公开内容来源。
- 手动扫描与每日/工作日 Scheduler。
- RSS / Atom 解析、受控网页抓取和 Trafilatura 正文提取。
- 每个新闻事件对应一张 AI 整理卡片，相关报道作为来源证据聚合展示。
- 新闻分类、AI 摘要、重要度、可信度、事实与判断。
- 单列 Markdown 新闻详情和原始来源链接。
- FastAPI + SQLite 服务端和 Next.js 客户端。
- SSE 扫描事件、失败重试和中断任务对账。
- 真实模型不可用时的显式降级。
- 来源引用、Prompt Injection 和结构化输出校验。
- 事实级支持/冲突引文、摘要数字忠实度与独立证据链校验。
- Story 时间线、变化摘要、订阅级偏好、站内提醒和日报/周报数据。
- 服务端测试、客户端 Lint、生产构建和渲染测试。

## 运行模式

应用启动时向上查找最近的 `.env`，不会覆盖已经存在的进程环境变量。

- 默认使用 DeepSeek `real + rss`，标准 Base URL、主模型和回退模型由项目提供默认值。
- 必须配置 `CONTENT_AI_API_KEY`；缺少 Key 时启动失败，不会静默降级为 Mock。
- 只有显式设置 `INTEL_RADAR_MODEL_MODE=mock` 时才使用 Mock Model；离线开发通常同时设置
  `INTEL_RADAR_SOURCE_MODE=fixture`。
- 可通过 `CONTENT_AI_*`、`INTEL_RADAR_MODEL_MODE` 和 `INTEL_RADAR_SOURCE_MODE` 显式覆盖。
- 聚类、事实级 Eval 和个性化分别由
  `INTEL_RADAR_STORY_CLUSTERING_ENABLED`、`INTEL_RADAR_CLAIM_EVAL_ENABLED`
  和 `INTEL_RADAR_PERSONALIZATION_ENABLED` 控制；关闭后不会删除已有 Story、引用或反馈。

Mock Model 和 Fixture 只用于离线开发与固定回归，页面必须明确标记演示状态，不能冒充
真实新闻。真实与 Mock 模式共用状态、策略、预算、事件和输出校验链路。

每个行业的来源策略位于 [feeds.json](./feeds.json)，包括：

- 行业关键词。
- 行业排除词，用于过滤同名歧义和常见噪声。
- 核心与行业来源。
- 可跨行业复用的论坛、证券市场、投融资、峰会、沙龙和行业媒体来源组。
- 来源可靠度和地区。
- AI 探测查询模板。

每个内置行业至少展开为 19 个定向来源：保留各行业独立维护的 8–9 个专业源（其中至少
3 个为中国来源），再叠加经过统一校验的跨行业情报来源组。行业关键词、排除词和 8 组
AI 检索规则仍按行业独立维护，采集后继续使用当前行业关键词过滤不相关内容。

扫描时会并行执行定向 RSS/Atom、配置的公开网页和 Google News RSS 检索。普通 HTTPS
自定义网站会优先发现 Feed，找不到时再受控提取站内文章；聚合器文章会在安全边界内
尝试还原原始发布页。所有外部内容均作为不可信数据处理。

首页会显示最近一次扫描的“候选 → 入选 → 未采用”漏斗。新闻卡数量是 AI 整理与 Eval
之后的入选结果，不等于采集器发现的候选总量。

新闻统一归入“新闻、融资、技术、活动、访谈”五类。分类描述内容类型而不是来源类型；
同一套行业来源可以发现多类新闻，某一类显示 `0` 只表示当前入选结果没有对应内容。

## 项目结构

```text
.
├── client/                  # Next.js Web 客户端
│   ├── app/
│   │   ├── components/      # 新闻卡片、Markdown 详情、来源和运行信息
│   │   ├── RadarDashboard.tsx
│   │   ├── radar-types.ts
│   │   └── radar-initial.ts
│   └── package.json
├── server/                  # FastAPI 行业新闻采集与 AI 整理服务
│   ├── app/
│   │   ├── api/
│   │   ├── domain/
│   │   ├── harness/         # 内部 Runtime、Model、Tools、Policy、Eval
│   │   ├── persistence/
│   │   └── scheduler.py
│   └── pyproject.toml
├── test/                    # 统一测试目录
│   ├── client/              # 客户端 Node 测试
│   └── server/              # 服务端 pytest 测试
├── fixtures/                # 可重复的离线外部资料
├── scripts/                 # 局域网预览等项目脚本
├── docs/                    # 架构、设计和开发文档
├── feeds.json               # 分行业来源和 AI 探测策略
├── data/                    # 本地 SQLite，Git 忽略
└── .env.example             # 可公开的环境变量示例
```

## 环境要求

- Python 3.12+
- Node.js 22.13+
- npm

## 启动服务端

首次运行可以使用 Mock 模型和 Fixture，体验扫描流程。真实新闻模式的配置见 [.env.example](./.env.example)。

```bash
cd server

python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
INTEL_RADAR_MODEL_MODE=mock \
INTEL_RADAR_SOURCE_MODE=fixture \
INTEL_RADAR_SCHEDULER_ENABLED=false \
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

服务地址：

- API：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`
- Health：`http://127.0.0.1:8000/health`
- 运行配置：`http://127.0.0.1:8000/api/system/status`

Health 和运行配置不会返回 API Key。

### 通过 Model Dock 使用本机 Codex

在同一台机器上启动 [Model Dock](https://github.com/idea007/model-dock)，添加已登录的 Codex，
发现并启用模型，将模型绑定到 `industry-brief` 别名，再创建只授权该别名的项目密钥。
在仓库根目录的 `.env` 中设置以下值，填入项目密钥后重启服务端。

```dotenv
CONTENT_AI_PROVIDER=model-dock-codex
CONTENT_AI_BASE_URL=http://127.0.0.1:4317/v1
CONTENT_AI_API_KEY=
CONTENT_AI_MODEL=industry-brief
CONTENT_AI_FALLBACK_MODELS=
CONTENT_AI_REASONING_EFFORT=low
INTEL_RADAR_MODEL_MODE=real
INTEL_RADAR_SOURCE_MODE=rss
INTEL_RADAR_MODEL_TIMEOUT_SECONDS=240
INTEL_RADAR_MODEL_MAX_RETRIES=0
INTEL_RADAR_MAX_CONCURRENT_RUNS=1
```

推理强度可留空以沿用模型默认值，或填写 Model Dock 模型目录支持的值。Codex 同时只处理一个
模型请求，本项目将后续扫描排队。服务端通过回环地址调用网关，Codex 的外网连接由 Model Dock
管理。macOS 上，网关在未显式设置代理时会在启动 Codex 子进程时读取系统的本机代理。

## 启动客户端

打开另一个终端：

```bash
cd client

npm ci
npm run dev
```

打开 `http://127.0.0.1:3000`。Next.js 默认将同源 `/api` 请求转发给
`http://127.0.0.1:8000`。服务端可用时，页面读取服务端数据。服务端不可用时，
页面显示未连接空态。Mock + Fixture 模式会标记为演示。

如需修改服务端地址：

```bash
RADAR_API_URL=http://127.0.0.1:18000 npm run dev
```

需要运行生产构建时，在 `client/` 执行 `npm run build` 和 `npm start`。
如果 API 使用自定义地址，在执行构建时设置 `RADAR_API_URL`。

## 手机局域网访问

项目提供单命令局域网模式，只向局域网暴露一个 HTTP 入口。页面和 API 在浏览器看来
属于同一来源，手机不需要单独配置服务端地址。

```bash
cd client
npm run lan
```

脚本会：

1. 构建客户端生产版本。
2. 在本机内部端口启动客户端与服务端。
3. 在 80 端口启动同源入口。
4. 输出手机可以直接打开的 `http://局域网IP/`。

手机与电脑必须连接同一 Wi-Fi。按 `Ctrl+C` 会同时停止三个进程。默认仅用于可信局域
网；当前产品没有用户登录，不应通过路由器端口映射直接暴露到公网。

可选覆盖项：

```bash
INTEL_RADAR_LAN_IP=192.168.1.10 \
RADAR_LAN_PORT=8080 \
npm run lan
```

脚本可在 macOS 自动识别局域网 IP。其他环境可显式设置 `INTEL_RADAR_LAN_IP`。
当 80 端口被占用时，可用 `RADAR_LAN_PORT` 指定其他端口，手机地址也需包含该端口。

## 使用流程

1. 首次进入时选择要关注的行业。
2. 选择当前扫描目标；需要时打开“来源策略”补充自定义来源。
3. 点击“立即扫描”。
4. 在新闻信息流中按标题、AI 摘要、重要度和可信度快速判断。
5. 点击卡片，在 Markdown 详情中先阅读中文新闻内容，再查看关注理由、关键事实、
   AI 判断和原始来源；非中文来源会在扫描时生成并保存中文译文。
6. 扫描失败或需要排障时，再打开“运行信息”。

如果启用公开预览，系统会在发送前请求一次性 Approval。默认 Web Inbox 不需要公开发布。

## Scheduler

Scheduler 默认关闭，避免开发环境启动后自动产生模型费用：

```bash
INTEL_RADAR_SCHEDULER_ENABLED=true \
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

支持：

- `每天 HH:MM`
- `工作日 HH:MM`

同一订阅、日期和时间槽使用稳定 idempotency key。手动验证一次 Tick：

```bash
curl -X POST 'http://127.0.0.1:8000/api/scheduler/tick?force=true'
```

`force=true` 忽略当前时间窗口，但仍保持同一时间槽幂等。

## 测试

服务端：

```bash
cd server
.venv/bin/python -m pytest -q
```

客户端：

```bash
cd client
npm run lint
npm run build
node --test ../test/client/rendered-html.test.mjs
```

## 主要 API

```text
GET  /api/dashboard
GET  /api/system/status
GET  /api/subscriptions
POST /api/subscriptions
GET  /api/source-profiles
GET  /api/custom-sources
POST /api/custom-sources
GET  /api/source-documents

GET  /api/runs
POST /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/source-documents
POST /api/runs/{run_id}/cancel
POST /api/runs/{run_id}/retry
GET  /api/runs/{run_id}/events
GET  /api/runs/{run_id}/events/history

GET  /api/intel-events
GET  /api/stories
GET  /api/stories/{story_id}
GET  /api/stories/{story_id}/timeline
GET  /api/intel-events/{event_id}/feedback
POST /api/intel-events/{event_id}/feedback
DELETE /api/intel-events/{event_id}/feedback/{feedback_type}
GET  /api/subscriptions/{subscription_id}/preferences
PUT  /api/subscriptions/{subscription_id}/preferences
GET  /api/alerts
POST /api/alerts
PUT  /api/alerts/{alert_id}
GET  /api/alerts/matches
GET  /api/digests
GET  /api/approvals
POST /api/approvals/{approval_id}/decisions
POST /api/scheduler/tick
```

## 已知边界

- 付费墙、强依赖客户端渲染的页面和受限站点会退回 Feed 摘要。
- 全文提取目前只处理每次检索中优先级最高的候选新闻。
- 当前跨来源聚类使用确定性文本相似度；模糊区采取保守拆分，仍可能漏合并，但不会由
  规则强行吞掉主体不同的事件。
- 引用校验使用最短必要正文片段和轻量文本匹配；尚未引入 Embedding 或在线学习排序。
- 日报、周报和提醒已持久化并提供 API，行业首页的独立入口和趋势下钻仍待迭代。
- 自定义主题的完整编辑能力仍需补齐。
- Scheduler 是单进程轮询器，不是分布式任务平台。
- SQLite 适合个人使用、单进程 MVP，不是生产多用户数据库方案。
- 运行信息仍包含部分内部术语，后续继续向用户语言收敛。

下一阶段优先级：

1. 完整的自定义主题、关键词和排除词。
2. 扩充离线聚类与事实支持评测集，基于标注结果校准阈值。
3. 来源健康状态、失败重试和漏报反馈。
4. 反馈指标、偏好管理与提醒规则的独立页面。
5. 独立的周期简报和可下钻趋势入口，不与新闻卡片混排。
