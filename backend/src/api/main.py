"""FastAPI application entry point with SSE streaming and lifecycle management."""
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.agent.paper_agent import PaperAgent
from src.agent.tools import init_tools
from src.cache.redis_manager import get_redis_manager
from src.config import get_settings
from src.ingestion.arxiv_fetcher import ArxivFetcher
from src.ingestion.chunker import PaperChunker
from src.ingestion.pdf_parser import PDFParser
from src.vectorstore.milvus_client import MilvusClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# ── Module-level service instances ───────────────────────────────────────────
_milvus: Optional[MilvusClient] = None
_paper_agent: Optional[PaperAgent] = None
_arxiv_fetcher: Optional[ArxivFetcher] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    global _milvus, _paper_agent, _arxiv_fetcher

    logger.info("Starting up ArXiv Agent...")

    # Connect Redis
    redis = get_redis_manager()
    await redis.connect()
    logger.info("Redis connected")

    # Connect Milvus
    _milvus = MilvusClient()
    try:
        _milvus.connect()
        logger.info("Milvus connected")
    except Exception as e:
        logger.warning(f"Milvus connection failed (non-fatal for dev): {e}")
        _milvus = None

    # Initialize ArXiv fetcher
    _arxiv_fetcher = ArxivFetcher()

    # Initialize agent tools
    if _milvus:
        init_tools(_arxiv_fetcher, _milvus)

    # Initialize and start agent
    _paper_agent = PaperAgent()
    try:
        _paper_agent.initialize()
        logger.info("PaperAgent initialized")
    except Exception as e:
        logger.warning(f"Agent initialization failed: {e}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await redis.disconnect()


app = FastAPI(
    title="ArXiv Research Agent API",
    description="Automated paper retrieval and analysis using LangChain + Milvus + Qwen",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(default=None)


class IngestRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    categories: Optional[list[str]] = None
    parse_pdf: bool = Field(default=False)


class IngestResponse(BaseModel):
    papers_fetched: int
    chunks_inserted: int
    paper_ids: list[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    redis = get_redis_manager()
    status = {"status": "ok", "services": {}}

    try:
        await redis.client.ping()
        status["services"]["redis"] = "ok"
    except Exception as e:
        status["services"]["redis"] = f"error: {e}"
        status["status"] = "degraded"

    if _milvus:
        try:
            stats = _milvus.get_collection_stats()
            status["services"]["milvus"] = f"ok ({stats.get('num_entities', 0)} vectors)"
        except Exception as e:
            status["services"]["milvus"] = f"error: {e}"
            status["status"] = "degraded"
    else:
        status["services"]["milvus"] = "not connected"

    status["services"]["agent"] = "ok" if _paper_agent else "not initialized"
    return status


@app.post("/api/agent/chat")
async def agent_chat(request: ChatRequest):
    """Stream Agent response via SSE.

    Returns Server-Sent Events with token, tool_end, and final event types.
    """
    if _paper_agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    session_id = request.session_id or str(uuid.uuid4())

    async def event_generator():
        try:
            async for event in _paper_agent.chat(
                user_input=request.message,
                session_id=session_id,
                stream=True,
            ):
                yield {
                    "event": event["type"],
                    "data": json.dumps(event, ensure_ascii=False),
                }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "content": str(e)}),
            }

    return EventSourceResponse(event_generator())


@app.post("/api/papers/ingest", response_model=IngestResponse)
async def ingest_papers(request: IngestRequest):
    """Fetch papers from ArXiv and store in Milvus vector store."""
    if _arxiv_fetcher is None:
        raise HTTPException(status_code=503, detail="ArXiv fetcher not initialized")
    if _milvus is None:
        raise HTTPException(status_code=503, detail="Milvus not connected")

    papers = await _arxiv_fetcher.search(
        query=request.query,
        max_results=request.limit,
        categories=request.categories,
    )

    chunker = PaperChunker()
    pdf_parser = PDFParser() if request.parse_pdf else None
    total_chunks = 0
    paper_ids = []

    for paper in papers:
        paper_ids.append(paper.paper_id)

        # Try PDF parsing if requested, fall back to abstract
        text = None
        if pdf_parser:
            try:
                text = await pdf_parser.download_and_parse(paper.pdf_url, paper.paper_id)
            except Exception as e:
                logger.warning(f"PDF parse failed for {paper.paper_id}: {e}")

        if text:
            chunks = chunker.chunk_paper(
                paper_id=paper.paper_id,
                text=text,
                title=paper.title,
                authors=paper.authors_str,
                published_date=paper.published_date,
                arxiv_url=paper.arxiv_url,
            )
        else:
            chunks = chunker.chunk_abstract_only(
                paper_id=paper.paper_id,
                title=paper.title,
                abstract=paper.abstract,
                authors=paper.authors_str,
                published_date=paper.published_date,
                arxiv_url=paper.arxiv_url,
            )

        if chunks:
            inserted = await _milvus.insert_chunks(chunks)
            total_chunks += inserted

    return IngestResponse(
        papers_fetched=len(papers),
        chunks_inserted=total_chunks,
        paper_ids=paper_ids,
    )


@app.delete("/api/papers/{paper_id}")
async def delete_paper(paper_id: str):
    """Delete a paper and all its chunks from the vector store."""
    if _milvus is None:
        raise HTTPException(status_code=503, detail="Milvus not connected")
    count = await _milvus.delete_paper(paper_id)
    return {"paper_id": paper_id, "deleted_chunks": count}


@app.get("/api/papers/search")
async def search_papers_endpoint(
    q: str = Query(..., min_length=1),
    top_k: int = Query(default=5, ge=1, le=20),
):
    """Semantic vector search for papers."""
    if _milvus is None:
        raise HTTPException(status_code=503, detail="Milvus not connected")

    results = await _milvus.search(q, top_k=top_k)
    return {"query": q, "results": results}


@app.get("/api/session/{session_id}")
async def get_session_history(session_id: str):
    """Retrieve conversation history for a session."""
    redis = get_redis_manager()
    history = await redis.get_session_history(session_id)
    return {"session_id": session_id, "history": history}


@app.delete("/api/cache")
async def clear_cache():
    """Clear all Redis cache (admin endpoint)."""
    redis = get_redis_manager()
    await redis.flush_all()
    return {"message": "Cache cleared"}


@app.delete("/api/cache/search")
async def clear_search_cache():
    """Clear only ArXiv search cache."""
    redis = get_redis_manager()
    count = await redis.flush_pattern("arxiv:query:*")
    return {"message": f"Cleared {count} search cache entries"}
