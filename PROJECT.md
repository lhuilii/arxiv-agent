# ArXiv Agent — 项目总览文档

> 最后更新：2026-04-07

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [需求分析](#2-需求分析)
3. [技术选型](#3-技术选型)
4. [系统架构设计](#4-系统架构设计)
5. [项目结构](#5-项目结构)
6. [分阶段实现计划](#6-分阶段实现计划)
7. [当前进度](#7-当前进度)
8. [快速启动](#8-快速启动)

---

## 1. 项目背景与目标

### 背景

学术研究者每天面对海量 ArXiv 论文，人工筛选、阅读、比较效率极低。本项目构建一个端到端的智能论文检索与分析系统，让用户用自然语言即可完成"搜索 → 检索 → 分析 → 报告"的全流程。

### 核心目标

- **工程能力展示**：RAG Pipeline、Redis 缓存优化、LangSmith 链路追踪、高可用架构
- **实用性**：支持中英文对话，流式输出，工具调用可视化
- **可部署性**：本地 Docker Compose 开发，一键部署至云服务器

### 开发环境

| 环境 | 设备 |
|------|------|
| 本地开发 | MacBook Air 2022（M2 / 8-16GB） |
| 生产部署 | 阿里云 ECS 4核8GB（推荐 ecs.c7.xlarge） |

---

## 2. 需求分析

### 功能需求

| 模块 | 需求描述 |
|------|---------|
| 论文检索 | 按关键词调用 ArXiv API 搜索论文，支持分类/日期过滤 |
| 向量入库 | 下载论文 PDF（或摘要），分块后生成 Embedding 并写入 Milvus |
| 语义搜索 | 用自然语言查询，从 Milvus 向量库召回相关 chunks |
| 论文分析 | RAG 方式：取论文 chunks 作上下文，由 Qwen 生成结构化分析 |
| 多论文对比 | 汇聚多篇论文内容，横向比较方法/贡献/局限 |
| 报告生成 | 给定主题，检索相关论文并生成 Markdown 研究报告 |
| 多轮对话 | 会话历史持久化于 Redis，支持上下文连续追问 |
| 流式输出 | Agent 思考过程和 LLM token 通过 SSE 实时推送前端 |
| 工具链可视 | 前端展示每次回复的 tool call 调用链（可折叠） |

### 非功能需求

- **性能**：相同查询第二次响应 < 50ms（Redis 缓存命中）
- **可观测**：LangSmith 记录完整工具链、Token 消耗、延迟、缓存命中标记
- **可靠性**：所有服务 `restart: always`，数据 volume 持久化
- **安全性**：Nginx 限流（30 req/min），生产环境 Redis 密码保护

---

## 3. 技术选型

### 技术栈总览

| 层次 | 技术 | 版本 |
|------|------|------|
| Agent 框架 | LangChain | ≥ 0.3 |
| LLM | 通义千问 qwen-plus | via DashScope |
| Embedding | text-embedding-v3（阿里云） | dim=1536 |
| 向量数据库 | Milvus Standalone | 2.4.6 |
| 缓存 | Redis | 7.2 |
| 数据源 | ArXiv API | arxiv≥2.1 |
| PDF 解析 | PyMuPDF (fitz) | ≥1.24 |
| 链路追踪 | LangSmith | ≥0.1 |
| 后端框架 | FastAPI + uvicorn | ≥0.115 |
| SSE | sse-starlette | ≥2.1 |
| 前端框架 | React 18 + TypeScript | Vite 5 |
| 样式 | Tailwind CSS | 3.x |
| 容器化 | Docker Compose | v2 |
| 语言 | Python 3.11+ / TypeScript | — |
| 依赖管理 | uv（后端）/ npm（前端） | — |
| CI/CD | GitHub Actions | — |

### 选型决策

#### 为何选 Milvus 而非 Chroma / Pinecone？

| 因素 | Milvus | Chroma | Pinecone |
|------|--------|--------|----------|
| 自托管 | 是 | 是 | 否（SaaS） |
| 国内访问 | 无限制 | 无限制 | 被墙 |
| 生产就绪 | 是（企业级） | 偏开发用途 | 是 |
| 费用 | 仅基础设施 | 免费 | $70+/月 |
| 索引类型 | IVF_FLAT / HNSW / DiskANN | HNSW | 托管 |

**结论**：Milvus 自托管无 API 成本，国内访问稳定，适合生产演示。

#### 为何选 Qwen 而非 OpenAI？

| 因素 | 通义千问 qwen-plus | GPT-4o |
|------|-----------------|--------|
| 国内网络 | 原生支持，无需代理 | 被墙 |
| 价格（输入/1M tokens） | ≈ ¥0.8 | ≈ ¥25 |
| 上下文窗口 | 128K | 128K |
| Function Calling | 支持 | 支持 |
| 流式输出 | 支持 | 支持 |

**结论**：Qwen 在同等能力下成本低约 30 倍，且开发全程无 VPN 依赖。

---

## 4. 系统架构设计

### 4.1 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                            │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / SSE
              ┌────────────▼────────────┐
              │         Nginx            │  SSL 终止 + 限流
              │     （反向代理）          │  静态文件服务
              └──────┬──────────────────┘
                     │
        ┌────────────▼────────────┐
        │        FastAPI           │  uvicorn 4 workers
        │   （后端 API + 生命周期）  │  CORS / Pydantic 校验
        └───────┬─────────────────┘
                │
    ┌───────────▼────────────┐
    │       PaperAgent        │  LangChain Tool Calling Agent
    │   （ReAct 多轮对话）     │  ChatTongyi(qwen-plus)
    │   max_iterations=8      │  AsyncIteratorCallbackHandler
    └──┬───────┬──────┬───────┘
       │       │      │
  ┌────▼──┐ ┌──▼──┐ ┌─▼─────────────┐
  │ArXiv  │ │Redis│ │    Milvus       │
  │  API  │ │Cache│ │（向量存储）      │
  └───────┘ └─────┘ └───────┬────────┘
                             │
                   ┌─────────▼──────────┐
                   │    etcd + MinIO     │
                   │  （Milvus 元数据）  │
                   └────────────────────┘
```

### 4.2 RAG Pipeline

#### Indexing 阶段（数据入库）

```
POST /api/papers/ingest
       │
       ▼
ArxivFetcher.search()          ← arxiv Python SDK，支持分类/日期过滤
       │
       ▼
PDFParser.download_and_parse() ← httpx 下载 + PyMuPDF 提取正文（可选）
       │ 失败时 fallback 到摘要
       ▼
PaperChunker                   ← RecursiveCharacterTextSplitter
  chunk_size=512, overlap=50     chunk_text 上限 2048 字符
       │
       ▼
DashScopeEmbeddings            ← text-embedding-v3，批量 25 条
  .aembed_documents()            异步并发调用
       │
       ▼
MilvusClient.insert_chunks()   ← COSINE IVF_FLAT 索引
  先查重，跳过已存在的 chunks     nlist=1024
```

#### Retrieval 阶段（查询时）

```
用户 Query
    │
    ▼
Redis 缓存检查（key: arxiv:query:{md5}）
    ├─ HIT  ──────────────────────────► 直接返回，< 50ms
    │
    └─ MISS
         │
         ▼
DashScopeEmbeddings.aembed_query_for_search()
  text_type="query"（非对称检索优化）
         │
         ▼
Milvus ANN 搜索  nprobe=16，COSINE 相似度
         │
         ▼
Top-K chunks → 拼装 LLM 上下文
         │
         ▼
ChatTongyi(qwen-plus) 流式生成
         │
         ▼
Redis 缓存写入（按 TTL 策略）
```

### 4.3 Milvus Collection Schema

```
Collection: arxiv_papers

字段名          类型              说明
──────────────────────────────────────────────
id             INT64 (PK, auto)  主键
paper_id       VARCHAR(64)       ArXiv ID，如 "2401.12345"
title          VARCHAR(512)      论文标题
authors        VARCHAR(256)      作者列表（前 5 位）
published_date VARCHAR(32)       发布日期，格式 "YYYY-MM-DD"
chunk_index    INT32             chunk 在原文中的序号
chunk_text     VARCHAR(2048)     chunk 文本内容
embedding      FLOAT_VECTOR(1536) text-embedding-v3 向量
arxiv_url      VARCHAR(256)      论文链接
```

索引：`IVF_FLAT`，`metric_type=COSINE`，`nlist=1024`

### 4.4 Redis 缓存策略

| 缓存对象 | Key 格式 | TTL | 说明 |
|---------|---------|-----|------|
| ArXiv 搜索结果 | `arxiv:query:{md5(query+params)}` | 3600s | ArXiv 数据变化慢 |
| 论文详情 | `detail:{paper_id}` | 86400s | 内容稳定，缓存 24h |
| LLM 分析结果 | `llm:{md5(query+ids)}` | 86400s | 分析结果昂贵，24h 有效 |
| 会话历史 | `session:{session_id}:history` | 1800s | 30 分钟会话窗口 |
| Embedding 向量 | `embed:{paper_id}:{chunk_idx}` | 永久（-1） | 向量是确定性的 |

**防穿透**：对空结果写入 `"__NULL__"` sentinel，避免频繁穿透到数据源。

### 4.5 Agent 工具链

| 工具 | 功能 | 缓存 |
|------|------|------|
| `search_papers` | ArXiv API + Milvus 向量检索混合召回 | Redis 3600s |
| `get_paper_detail` | 获取指定 paper 的全文 chunks | Redis 86400s |
| `analyze_paper` | RAG 分析：取 chunks 组装 prompt 交给 LLM | Redis 86400s |
| `compare_papers` | 多篇论文内容汇聚，返回对比上下文 | 无（透传） |
| `generate_report` | 检索相关论文，生成 Markdown 报告上下文 | 无（透传） |

所有工具均标注 `@traceable`，LangSmith 可追踪每次调用的输入/输出/延迟。

### 4.6 SSE 流式事件协议

前后端通过 SSE 传输 Agent 的实时状态，事件类型：

```
{ "type": "token",    "content": "..." }      ← LLM 逐 token 输出
{ "type": "tool_end", "tool": "...", "output": "..." }  ← 工具调用结束
{ "type": "final",    "content": "...", "steps": [...] } ← 最终答案 + 完整步骤
{ "type": "error",    "content": "..." }      ← 错误信息
```

### 4.7 生产高可用架构

```
公网 IP
  └── Nginx（SSL 终止 + 反向代理 + 限流 30req/min）
       ├── /api  → FastAPI（uvicorn 4 workers）
       └── /     → React 静态文件（dist/）
            ├── Milvus Standalone（host volume 持久化）
            ├── Redis 7（AOF appendfsync everysec）
            └── etcd + MinIO（Milvus 依赖）

宿主机目录挂载：
  /opt/arxiv-agent/etcd/    ← etcd 数据
  /opt/arxiv-agent/minio/   ← 对象存储
  /opt/arxiv-agent/milvus/  ← Milvus 数据
  /opt/arxiv-agent/redis/   ← AOF 日志
```

---

## 5. 项目结构

```
arxiv-agent/
├── backend/
│   ├── src/
│   │   ├── config.py                  # pydantic-settings 统一配置
│   │   ├── ingestion/
│   │   │   ├── arxiv_fetcher.py       # ArXiv API 异步封装，含重试
│   │   │   ├── pdf_parser.py          # PyMuPDF PDF 下载与解析
│   │   │   └── chunker.py             # RecursiveCharacterTextSplitter
│   │   ├── vectorstore/
│   │   │   ├── embeddings.py          # DashScope text-embedding-v3 异步客户端
│   │   │   └── milvus_client.py       # Collection 管理、插入、搜索
│   │   ├── cache/
│   │   │   └── redis_manager.py       # 异步连接池、Key 构造、@redis_cache 装饰器
│   │   ├── agent/
│   │   │   ├── tools.py               # 5 个 LangChain Tool，均含 @traceable
│   │   │   └── paper_agent.py         # PaperAgent：LLM + 工具 + SSE 流 + 会话记忆
│   │   └── api/
│   │       └── main.py                # FastAPI 入口，lifespan 管理，7 个 REST 端点
│   ├── pyproject.toml                 # uv 依赖管理
│   └── Dockerfile                     # 多阶段构建，非 root 用户
├── frontend/
│   ├── src/
│   │   ├── types.ts                   # 共享 TypeScript 类型
│   │   ├── api.ts                     # fetch 封装 + SSE streamChat()
│   │   ├── App.tsx                    # 主布局：Header + SearchBar + 左右分栏
│   │   └── components/
│   │       ├── SearchBar.tsx          # 搜索 + 一键 Index 按钮
│   │       ├── PaperList.tsx          # 论文卡片列表，含相似度进度条
│   │       ├── ChatPanel.tsx          # SSE 流式对话面板，Markdown 渲染
│   │       └── AgentTrace.tsx         # 工具调用链可视化（按颜色区分工具类型）
│   ├── vite.config.ts                 # Vite 配置，/api 代理到 :8080
│   ├── tailwind.config.js
│   └── package.json
├── docker-compose.yml                 # 开发环境：Milvus + etcd + MinIO + Redis + Attu
├── docker-compose.prod.yml            # 生产：资源限制 + restart:always + host volumes
├── nginx/
│   └── nginx.conf                     # SSE 专项配置（proxy_buffering off）+ 限流
├── .github/
│   └── workflows/
│       └── ci-cd.yml                  # lint → Docker build → SSH 部署
├── scripts/
│   └── health_check.py                # 异步检查 Redis / Milvus / DashScope / Qwen
├── tests/
│   └── eval_dataset.json              # 20 条 LangSmith 评估集（中英双语）
├── docs/
│   └── architecture.md                # 技术架构详细文档
├── .env.example                       # 环境变量模板
└── .gitignore
```

---

## 6. 分阶段实现计划

### Phase 0 — 环境搭建与服务验证

**目标**：本地所有服务跑通，API Keys 配置完毕

- 初始化 Python 项目（uv 管理依赖）
- 编写 `docker-compose.yml`：Milvus + etcd + MinIO + Redis + Attu
- 配置 `.env`：DASHSCOPE_API_KEY、LANGCHAIN_API_KEY
- 编写 `scripts/health_check.py` 验证所有服务连通性
- 初始化 React 前端项目（Vite + TypeScript + Tailwind）

**验收**：`python scripts/health_check.py` 全部服务输出 ✓

---

### Phase 2 — 数据摄入 Pipeline

**目标**：论文数据可检索（RAG Indexing 阶段）

- `arxiv_fetcher.py`：异步 ArXiv API，支持关键词/分类/时间过滤，tenacity 重试
- `pdf_parser.py`：httpx 下载 PDF + PyMuPDF 提取正文，失败 fallback 到摘要
- `chunker.py`：`RecursiveCharacterTextSplitter`（chunk=512, overlap=50），自动注入元数据 header
- `embeddings.py`：DashScope `text-embedding-v3`，批量 25 条异步调用，支持 `text_type="query"`
- `milvus_client.py`：Collection 自动创建（COSINE IVF_FLAT），插入前去重

---

### Phase 3 — Redis 缓存层

**目标**：降低重复调用开销，体现缓存工程能力

- `redis_manager.py`：`asyncio` 异步连接池（max_connections=20）
- 统一 Key 构造方法（MD5 哈希防 key 过长）
- `__NULL__` sentinel 防止缓存穿透
- `@redis_cache(key_fn, ttl)` 通用装饰器
- 会话历史 append-only 写入，TTL=1800s

---

### Phase 4 — Agent 核心逻辑

**目标**：可多轮对话的智能论文分析 Agent

- `tools.py`：5 个工具均含 Redis 缓存 + `@traceable` 追踪
- `paper_agent.py`：`ChatTongyi(qwen-plus, streaming=True, temperature=0.1)`
- `create_tool_calling_agent` + `AgentExecutor(max_iterations=8)`
- `AsyncIteratorCallbackHandler` 驱动 SSE token 流
- 对话历史从 Redis 加载，响应后追加写回

---

### Phase 5 — LangSmith 链路追踪

**目标**：Agent 执行全程可观测

- 通过环境变量启用：`LANGCHAIN_TRACING_V2=true`
- 每次 `ainvoke` 携带 `run_name`、`tags`、`metadata`
- 所有工具标注 `@traceable(name=...)`
- `tests/eval_dataset.json`：20 条评估查询（含中文），覆盖全部工具类型

---

### Phase 6 — FastAPI 后端 + React 前端

**目标**：完整可交互的 Web 应用

**FastAPI（7 个端点）**：

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/health` | 服务健康状态 |
| POST | `/api/agent/chat` | SSE 流式 Agent 对话 |
| POST | `/api/papers/ingest` | ArXiv 抓取 + Milvus 入库 |
| GET | `/api/papers/search` | 向量语义搜索 |
| GET | `/api/session/{id}` | 获取会话历史 |
| DELETE | `/api/cache` | 清空全部缓存 |
| DELETE | `/api/cache/search` | 仅清空搜索缓存 |

**React 前端功能**：
- Header：实时健康状态指示（绿/红）
- SearchBar：关键词搜索 + 一键 Index 入库
- PaperList：论文卡片，含相似度进度条，点击跳转 ArXiv
- ChatPanel：SSE 流式对话，Markdown 渲染，Shift+Enter 换行
- AgentTrace：工具调用折叠面板，按工具类型着色

---

### Phase 1 — 架构文档

**目标**：输出技术文档，供项目展示

- `docs/architecture.md`：系统数据流图、技术选型决策、RAG Pipeline、缓存策略、高可用方案、API 清单

---

### Phase 7 — 生产部署配置

**目标**：可对外演示的生产环境

- `docker-compose.prod.yml`：资源限制（Milvus≤2G、Redis≤512M）、host volume 挂载、`restart: always`
- `nginx/nginx.conf`：SSE 专项配置（`proxy_buffering off`、`proxy_read_timeout 300s`）、限流
- `.github/workflows/ci-cd.yml`：
  - `test` job：ruff lint + mypy type check
  - `build-backend` job：Docker 构建 + 推送 GHCR
  - `build-frontend` job：`npm ci && npm run build`
  - `deploy` job：SSH 拉取镜像 + `docker compose up -d`

---

## 7. 当前进度

### 总体状态

**代码实现：100% 完成**（全部阶段骨架代码已就位，待配置 API Key 后可直接运行）

### 各阶段明细

| 阶段 | 内容 | 状态 | 说明 |
|------|------|------|------|
| Phase 0 | 环境搭建 | **完成** | docker-compose、pyproject.toml、.env.example、health_check.py、前端脚手架全部就绪 |
| Phase 2 | 数据摄入 Pipeline | **完成** | arxiv_fetcher / pdf_parser / chunker / embeddings / milvus_client 均已实现 |
| Phase 3 | Redis 缓存层 | **完成** | 连接池、Key 构造、sentinel 防穿透、装饰器、会话管理全部实现 |
| Phase 4 | Agent 核心 | **完成** | 5 个工具 + PaperAgent（qwen-plus、SSE 流、Redis 记忆）实现完毕 |
| Phase 5 | LangSmith 追踪 | **完成** | 环境变量配置、@traceable 标注、20 条评估集已写入 |
| Phase 6 | 前后端 | **完成** | FastAPI 7 个端点 + React 4 个组件全部实现 |
| Phase 1 | 架构文档 | **完成** | docs/architecture.md 已输出 |
| Phase 7 | 生产部署 | **完成** | docker-compose.prod.yml、nginx.conf、CI/CD workflow 已就绪 |

### 待完成事项（运行前必做）

以下是代码之外、需要手动操作的部分：

- [ ] **配置 API Key**：复制 `.env.example` → `.env`，填写 `DASHSCOPE_API_KEY` 和 `LANGCHAIN_API_KEY`
- [ ] **安装前端依赖**：`cd frontend && npm install`（需网络下载 npm 包）
- [ ] **安装后端依赖**：`cd backend && uv pip install -e .`
- [ ] **启动 Docker 服务**：`docker compose up -d`，等待 Milvus 健康检查通过
- [ ] **端到端验证**：按下方"快速启动"中的验证清单逐步检查

### 待开发功能（未来迭代）

- [ ] 单元测试 / 集成测试（pytest）
- [ ] LangSmith 评估集自动运行脚本
- [ ] 前端：LangSmith Trace 链接展示（需后端透传 run_url）
- [ ] 前端：论文详情 Modal（标题、完整摘要、分析结果）
- [ ] 生产环境 SSL 证书配置（Let's Encrypt）
- [ ] 监控告警（Docker stats + Redis INFO 定时上报）

---

## 8. 快速启动

### 前置条件

- Docker Desktop（macOS）已安装并运行
- Python 3.11+（推荐通过 `pyenv` 管理）
- Node.js 20+
- 已获取 [DashScope API Key](https://dashscope.aliyun.com/) 和 [LangSmith API Key](https://smith.langchain.com/)

### 步骤

```bash
# 1. 进入项目目录
cd arxiv-agent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写：
#   DASHSCOPE_API_KEY=sk-xxxx
#   LANGCHAIN_API_KEY=ls__xxxx

# 3. 启动基础服务（Milvus + Redis + Attu）
docker compose up -d
# 等待约 30s，Milvus 启动较慢

# 4. 验证服务健康（需先安装依赖）
cd backend
uv pip install -e .
python ../scripts/health_check.py

# 5. 启动后端
uvicorn src.api.main:app --host 0.0.0.0 --port 8080 --reload

# 6. 启动前端（新终端）
cd ../frontend
npm install
npm run dev
# 访问 http://localhost:5173
```

### 端到端验证清单

```bash
# 1. 健康检查
curl http://localhost:8080/api/health

# 2. 论文入库
curl -X POST http://localhost:8080/api/papers/ingest \
  -H "Content-Type: application/json" \
  -d '{"query": "RAG survey", "limit": 5}'

# 3. 向量检索
curl "http://localhost:8080/api/papers/search?q=attention+mechanism&top_k=3"

# 4. 缓存验证（第二次应 < 50ms）
curl "http://localhost:8080/api/papers/search?q=attention+mechanism&top_k=3"

# 5. 前端 Chat 面板输入：
#    "分析 2024 年 RAG 领域的最新进展"
#    → 观察流式输出 + AgentTrace 工具调用链
```

### 服务端口一览

| 服务 | 端口 | 说明 |
|------|------|------|
| FastAPI | 8080 | REST API + SSE |
| React Dev Server | 5173 | 前端开发服务器 |
| Milvus gRPC | 19530 | 向量库接入 |
| Attu（Milvus GUI） | 8000 | 可视化管理界面 |
| Redis | 6379 | 缓存服务 |

---

*文档由项目实现代码自动整理，反映当前实际状态。*
