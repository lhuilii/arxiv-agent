# 项目启动指南

## 前置条件

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| Docker Desktop | 最新版 | 运行 Milvus / Redis 等基础服务 |
| Python | 3.11+ | 后端运行环境 |
| Node.js | 20+ | 前端构建工具 |
| uv | 任意 | Python 依赖管理（`pip install uv`）|

---

## 第一次启动（完整流程）

### 1. 配置环境变量

```bash
cd arxiv-agent
cp .env.example .env
```

编辑 `.env`，至少填写以下两项：

```env
DASHSCOPE_API_KEY=sk-xxxxxxxx        # 必填：通义千问 + Embedding
LANGCHAIN_API_KEY=ls__xxxxxxxx       # 可选：LangSmith 链路追踪
```

> 获取 DashScope Key：https://dashscope.console.aliyun.com/
> 获取 LangSmith Key：https://smith.langchain.com/
> 不需要 LangSmith 时，将 `.env` 中 `LANGCHAIN_TRACING_V2` 改为 `false`

---

### 2. 启动基础服务（Docker）

```bash
docker compose up -d
```

等待所有容器变为 `healthy`（约 30 秒）：

```bash
docker compose ps
```

期望输出：

```
NAME           STATUS
arxiv-attu     Up X seconds
arxiv-etcd     Up X seconds (healthy)
arxiv-milvus   Up X seconds (healthy)
arxiv-minio    Up X seconds (healthy)
arxiv-redis    Up X seconds (healthy)
```

---

### 3. 安装后端依赖

```bash
pip install uv
cd backend
uv pip install --system -e .
```

---

### 4. 验证服务连通性

```bash
cd ..
python scripts/health_check.py
```

期望输出：

```
==================================================
 ArXiv Agent - Service Health Check
==================================================
  ✓ Redis     : Redis 7.x OK
  ✓ Milvus    : Milvus 2.4.x OK
  ✓ DashScope : DashScope text-embedding-v3 OK
  ✓ Qwen API  : Qwen API OK (response: OK...)
==================================================
  All services OK - ready to start!
```

---

### 5. 启动后端

```bash
cd backend
uvicorn src.api.main:app --host 0.0.0.0 --port 8080 --reload
```

看到以下日志说明启动成功：

```
INFO  Redis connected
INFO  Milvus connected
INFO  PaperAgent initialized with qwen-plus and 5 tools
INFO  Uvicorn running on http://0.0.0.0:8080
```

---

### 6. 安装前端依赖并启动（新终端窗口）

```bash
cd frontend
npm install
npm run dev
```

看到以下输出后访问浏览器：

```
  VITE v5.x.x  ready in xxx ms
  ➜  Local:   http://localhost:5173/
```

打开 **http://localhost:5173** 即可使用。

---

## 日常启动（服务已安装过）

```bash
# 终端 1：启动 Docker 服务
docker compose up -d

# 终端 2：启动后端
cd backend && uvicorn src.api.main:app --host 0.0.0.0 --port 8080 --reload

# 终端 3：启动前端
cd frontend && npm run dev
```

---

## 服务端口一览

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端界面 | http://localhost:5173 | React 开发服务器 |
| 后端 API | http://localhost:8080 | FastAPI + SSE |
| API 文档 | http://localhost:8080/docs | Swagger UI |
| Attu（Milvus GUI）| http://localhost:8000 | 向量库可视化管理 |
| Redis | localhost:6379 | 缓存服务 |
| Milvus gRPC | localhost:19530 | 向量库接入 |

---

## 功能验证清单

### 1. 健康检查

```bash
curl http://localhost:8080/api/health
```

期望：`{"status":"ok","services":{"redis":"ok","milvus":"ok ...","agent":"ok"}}`

### 2. 论文入库

```bash
curl -X POST http://localhost:8080/api/papers/ingest \
  -H "Content-Type: application/json" \
  -d '{"query": "RAG survey", "limit": 5}'
```

期望：`{"papers_fetched":5,"chunks_inserted":N,"paper_ids":[...]}`

### 3. 向量检索

```bash
curl "http://localhost:8080/api/papers/search?q=attention+mechanism&top_k=3"
```

### 4. 缓存验证

连续执行两次相同检索，第二次响应应 < 50ms：

```bash
time curl "http://localhost:8080/api/papers/search?q=attention+mechanism&top_k=3"
time curl "http://localhost:8080/api/papers/search?q=attention+mechanism&top_k=3"
```

### 5. Agent 对话

在前端 Chat 面板输入：

```
分析 2024 年 RAG 领域的最新进展
```

观察：流式 token 输出 + 右侧 AgentTrace 工具调用链展开。

---

## 停止服务

```bash
# 停止 Docker 服务（数据保留）
docker compose down

# 停止 Docker 服务并清除所有数据（慎用）
docker compose down -v
```

---

## 常见问题

**Milvus 连接失败**
```
# 检查容器状态
docker compose ps
# 查看 Milvus 日志
docker compose logs milvus --tail=50
```

**`ModuleNotFoundError` 后端报错**
```bash
# 重新安装依赖
cd backend && uv pip install --system -e .
```

**前端 `/api` 请求 404**
- 确认后端已在 `:8080` 运行
- Vite 开发服务器会将 `/api/*` 自动代理到 `http://localhost:8080`

**DashScope API 鉴权失败**
- 检查 `.env` 中 `DASHSCOPE_API_KEY` 是否正确
- 确认账户余额充足（[控制台](https://dashscope.console.aliyun.com/)）
