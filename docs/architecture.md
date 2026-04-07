# ArXiv Agent — System Architecture

## 1. System Overview

A full-stack intelligent paper retrieval and analysis system combining RAG, Redis caching, LangSmith observability, and a streaming React UI.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User (Browser)                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP / SSE
                    ┌──────────▼──────────┐
                    │     Nginx            │  SSL termination
                    │  (Reverse Proxy)     │  Static file serving
                    └──────┬──────┬────────┘
                           │      │
              ┌────────────▼──┐ ┌─▼───────────────┐
              │  FastAPI       │ │  React SPA       │
              │  (uvicorn 4w)  │ │  (Vite build)    │
              └───────┬────────┘ └─────────────────┘
                      │
          ┌───────────▼────────────┐
          │     PaperAgent          │
          │  (LangChain ReAct)      │
          │  LLM: qwen-plus         │
          └──┬──────┬──────┬────────┘
             │      │      │
    ┌────────▼─┐ ┌──▼──┐ ┌─▼──────────────┐
    │  ArXiv   │ │Redis│ │  Milvus         │
    │  API     │ │Cache│ │  (Vector Store) │
    └──────────┘ └─────┘ └─────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  etcd + MinIO       │
                    │  (Milvus backend)   │
                    └────────────────────┘
```

---

## 2. Data Flow: RAG Pipeline

### Indexing (Ingestion)

```
POST /api/papers/ingest
        │
        ▼
ArxivFetcher.search()
  └─ arxiv Python SDK → ArXiv API
        │
        ▼
PDFParser.download_and_parse()   ← optional, fallback to abstract
  └─ httpx download + PyMuPDF extraction
        │
        ▼
PaperChunker.chunk_paper()
  └─ RecursiveCharacterTextSplitter (chunk=512, overlap=50)
        │
        ▼
DashScopeEmbeddings.aembed_documents()
  └─ text-embedding-v3 API (batches of 25)
        │
        ▼
MilvusClient.insert_chunks()
  └─ COSINE similarity IVF_FLAT index (dim=1536)
```

### Retrieval (Query Time)

```
User query
    │
    ▼
Redis cache check (key: arxiv:query:{md5})
    │ HIT ────────────────────────────────► return cached
    │ MISS
    ▼
DashScopeEmbeddings.aembed_query_for_search()
  └─ text_type="query" for asymmetric retrieval
    │
    ▼
Milvus ANN search (nprobe=16, COSINE)
    │
    ▼
Top-K chunks → LLM context window
    │
    ▼
ChatTongyi(qwen-plus) → response
    │
    ▼
Redis cache set (TTL varies by type)
```

---

## 3. Technology Decisions

### Why Milvus vs Chroma / Pinecone?

| Factor | Milvus | Chroma | Pinecone |
|--------|--------|--------|----------|
| Self-hosted | Yes | Yes | No (SaaS) |
| Scale | Billions of vectors | Millions | Billions |
| China network | Excellent (no proxy) | Good | Blocked |
| Production ready | Yes (v2.4) | Dev-focused | Yes |
| Cost | Free (infra only) | Free | $70+/mo |
| Index types | IVF, HNSW, DiskANN | HNSW only | Managed |

**Decision**: Milvus chosen for self-hosting capability, no API cost at scale, and stable access without VPN.

### Why Qwen vs OpenAI?

| Factor | Qwen (DashScope) | OpenAI |
|--------|-----------------|--------|
| China network | Native | Blocked |
| Price (input/1M) | ¥0.8 (qwen-plus) | ~¥25 (gpt-4o) |
| Context window | 128K | 128K |
| Tool calling | Supported | Supported |
| Streaming | Supported | Supported |

**Decision**: Qwen offers 30× cost reduction with equivalent capabilities for RAG use cases and eliminates VPN dependency for development.

### Why Redis for Caching?

- **AOF persistence**: Cache survives service restarts
- **Async client**: `redis.asyncio` integrates with FastAPI's event loop
- **Data structures**: String (JSON blobs), List (session history)
- **TTL per key type**: Search results expire (stale data), embeddings persist (stable)

---

## 4. Cache Strategy

| Cache Type | Redis Key | TTL | Rationale |
|-----------|-----------|-----|-----------|
| ArXiv search | `arxiv:query:{md5(q+params)}` | 3600s | ArXiv data changes slowly |
| Embedding vectors | `embed:{paper_id}:{chunk_idx}` | -1 (permanent) | Embeddings are deterministic |
| LLM analysis | `llm:{md5(q+ids)}` | 86400s | Analysis is expensive, valid for 24h |
| Session history | `session:{id}:history` | 1800s | 30-min session window |

**Null value caching**: Store `"__NULL__"` sentinel to prevent cache penetration on absent keys.

---

## 5. Agent Architecture

```
User Input
    │
    ▼
ChatTongyi (qwen-plus, streaming)
    │
    ▼
Tool Calling Loop (max_iterations=8)
    ├─ search_papers      → ArXiv API + Milvus vector search
    ├─ get_paper_detail   → Milvus chunk retrieval
    ├─ analyze_paper      → RAG: chunks → LLM analysis
    ├─ compare_papers     → Multi-paper context assembly
    └─ generate_report    → Comprehensive Markdown report
    │
    ▼
AsyncIteratorCallbackHandler → SSE stream to frontend
    │
    ▼
Redis session history (last 10 turns)
    │
    ▼
LangSmith trace (tool calls, token counts, latency)
```

---

## 6. High Availability Design

### Local Development (Docker Compose)
- All services on single machine
- Named volumes for data persistence
- `unless-stopped` restart policy

### Production (Cloud ECS 4c8g)
```
/opt/arxiv-agent/
├── etcd/        ← host-mounted volume
├── minio/       ← host-mounted volume
├── milvus/      ← host-mounted volume
└── redis/       ← host-mounted volume
```

**Resilience measures**:
1. All containers: `restart: always`
2. Redis: `appendonly yes` + `appendfsync everysec` (max 1s data loss)
3. Milvus: host-volume persistence (data survives container replacement)
4. FastAPI: 4 uvicorn workers (handles up to ~200 concurrent requests)
5. Nginx: upstream keepalive + health check
6. GitHub Actions: zero-downtime deploy (pull new image → `up -d`)

### Monitoring
```bash
# Container resource usage
docker stats --no-stream

# Redis health
redis-cli info stats | grep -E 'keyspace|commands'

# Milvus entity count
python -c "from pymilvus import Collection; print(Collection('arxiv_papers').num_entities)"
```

---

## 7. LangSmith Observability

Each agent invocation creates a LangSmith run with:
- Full tool call chain with inputs/outputs
- Token consumption (input + output separately)
- Tool execution latency per step
- Cache hit metadata (`cache_hit=true` tag)
- Error traces with full stack context

**Evaluation**: `tests/eval_dataset.json` contains 20 queries covering:
- Multilingual queries (Chinese + English)
- Single-paper analysis
- Multi-paper comparison
- Report generation
- Various research domains

LangSmith evaluation can be triggered via the SDK:
```python
from langsmith import Client
client = Client()
dataset = client.create_dataset("arxiv-agent-eval")
# Upload eval_dataset.json queries as examples
```

---

## 8. API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Service health status |
| POST | `/api/agent/chat` | SSE streaming agent chat |
| POST | `/api/papers/ingest` | Fetch + index papers from ArXiv |
| GET | `/api/papers/search` | Semantic vector search |
| GET | `/api/session/{id}` | Get conversation history |
| DELETE | `/api/cache` | Clear all Redis cache |
| DELETE | `/api/cache/search` | Clear search cache only |
