"""Agent tools for paper search, analysis, and report generation."""
import json
import logging
from typing import Any, Optional

from langchain.tools import tool
from langsmith import traceable

from src.cache.redis_manager import get_redis_manager
from src.ingestion.arxiv_fetcher import ArxivFetcher
from src.vectorstore.milvus_client import MilvusClient

logger = logging.getLogger(__name__)

# Module-level singletons (initialized once when app starts)
_arxiv_fetcher: Optional[ArxivFetcher] = None
_milvus_client: Optional[MilvusClient] = None


def init_tools(arxiv_fetcher: ArxivFetcher, milvus_client: MilvusClient) -> None:
    """Inject dependencies into tools module."""
    global _arxiv_fetcher, _milvus_client
    _arxiv_fetcher = arxiv_fetcher
    _milvus_client = milvus_client


def _get_fetcher() -> ArxivFetcher:
    if _arxiv_fetcher is None:
        raise RuntimeError("Tools not initialized. Call init_tools() first.")
    return _arxiv_fetcher


def _get_milvus() -> MilvusClient:
    if _milvus_client is None:
        raise RuntimeError("Tools not initialized. Call init_tools() first.")
    return _milvus_client


# ── Tool: search_papers ───────────────────────────────────────────────────────

@tool
@traceable(name="search_papers")
async def search_papers(query: str, max_results: int = 5) -> str:
    """Search for academic papers on ArXiv and in the vector store.

    Combines ArXiv API search with semantic vector search.
    Results are cached in Redis for 1 hour.

    Args:
        query: Natural language search query
        max_results: Number of papers to return (default 5, max 10)

    Returns:
        JSON string with list of paper metadata
    """
    max_results = min(max_results, 10)
    redis = get_redis_manager()
    cache_key = redis.arxiv_search_key(query, max_results=max_results)

    # Check Redis cache first
    cached = await redis.get(cache_key)
    if cached and cached != "__NULL__":
        logger.info(f"Cache HIT for search: {query!r}")
        return json.dumps(cached, ensure_ascii=False)

    fetcher = _get_fetcher()
    papers = await fetcher.search(query, max_results=max_results)

    results = [p.to_dict() for p in papers]

    # Cache results
    await redis.set(cache_key, results, ttl=3600)

    # Also do vector search if Milvus has data
    try:
        milvus = _get_milvus()
        vector_hits = await milvus.search(query, top_k=max_results)
        # Merge: add vector results not already in arxiv results
        existing_ids = {r["paper_id"] for r in results}
        for hit in vector_hits:
            if hit["paper_id"] not in existing_ids:
                results.append(
                    {
                        "paper_id": hit["paper_id"],
                        "title": hit["title"],
                        "authors": hit["authors"],
                        "published_date": hit["published_date"],
                        "arxiv_url": hit["arxiv_url"],
                        "score": hit["score"],
                        "source": "vector_store",
                    }
                )
    except Exception as e:
        logger.warning(f"Vector search failed (non-fatal): {e}")

    return json.dumps(results[:max_results], ensure_ascii=False)


# ── Tool: get_paper_detail ────────────────────────────────────────────────────

@tool
@traceable(name="get_paper_detail")
async def get_paper_detail(paper_id: str) -> str:
    """Get the full text chunks for a specific paper from the vector store.

    Args:
        paper_id: ArXiv paper ID (e.g. '2401.12345')

    Returns:
        JSON string with paper chunks concatenated as readable text
    """
    redis = get_redis_manager()
    cache_key = f"detail:{paper_id}"

    cached = await redis.get(cache_key)
    if cached and cached != "__NULL__":
        logger.info(f"Cache HIT for paper detail: {paper_id}")
        return json.dumps(cached, ensure_ascii=False)

    milvus = _get_milvus()
    chunks = await milvus.get_paper_chunks(paper_id)

    if not chunks:
        # Fallback: fetch from ArXiv API
        fetcher = _get_fetcher()
        paper = await fetcher.fetch_by_id(paper_id)
        if paper is None:
            return json.dumps({"error": f"Paper {paper_id} not found"})
        result = {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "authors": paper.authors_str,
            "abstract": paper.abstract,
            "arxiv_url": paper.arxiv_url,
            "source": "arxiv_api",
        }
    else:
        full_text = "\n\n".join(c["chunk_text"] for c in chunks)
        result = {
            "paper_id": paper_id,
            "title": chunks[0].get("title", ""),
            "authors": chunks[0].get("authors", ""),
            "published_date": chunks[0].get("published_date", ""),
            "arxiv_url": chunks[0].get("arxiv_url", ""),
            "full_text": full_text[:8000],  # cap for context window
            "chunk_count": len(chunks),
            "source": "vector_store",
        }

    await redis.set(cache_key, result, ttl=86400)
    return json.dumps(result, ensure_ascii=False)


# ── Tool: analyze_paper ───────────────────────────────────────────────────────

@tool
@traceable(name="analyze_paper")
async def analyze_paper(paper_id: str) -> str:
    """Analyze a paper using RAG: retrieve its chunks and generate a structured summary.

    The analysis includes: summary, methodology, key contributions, and limitations.

    Args:
        paper_id: ArXiv paper ID

    Returns:
        Structured analysis as a markdown string
    """
    redis = get_redis_manager()
    cache_key = f"analysis:{paper_id}"

    cached = await redis.get(cache_key)
    if cached and cached != "__NULL__":
        logger.info(f"Cache HIT for analysis: {paper_id}")
        return cached if isinstance(cached, str) else json.dumps(cached)

    # Get paper details - returns a JSON string
    detail_json = await get_paper_detail.ainvoke({"paper_id": paper_id})
    detail = json.loads(detail_json)

    if "error" in detail:
        return f"Error: {detail['error']}"

    title = detail.get("title", "Unknown")
    text = detail.get("full_text") or detail.get("abstract", "No text available")

    # Semantic search for related context
    try:
        milvus = _get_milvus()
        related = await milvus.search(title, top_k=3)
        context_chunks = [r["chunk_text"] for r in related if r["paper_id"] == paper_id][:3]
        context = "\n\n".join(context_chunks) if context_chunks else text[:3000]
    except Exception:
        context = text[:3000]

    # Return context for the LLM agent to analyze
    analysis_prompt = f"""Paper: {title}
Authors: {detail.get('authors', '')}
Date: {detail.get('published_date', '')}
ArXiv: {detail.get('arxiv_url', '')}

Content:
{context}

Please provide a structured analysis including:
1. Summary (2-3 sentences)
2. Methodology
3. Key Contributions / Innovations
4. Limitations / Future Work
"""
    await redis.set(cache_key, analysis_prompt, ttl=86400)
    return analysis_prompt


# ── Tool: compare_papers ──────────────────────────────────────────────────────

@tool
@traceable(name="compare_papers")
async def compare_papers(paper_ids: str) -> str:
    """Compare multiple papers side by side.

    Args:
        paper_ids: Comma-separated list of ArXiv paper IDs

    Returns:
        Structured comparison context for all papers
    """
    ids = [pid.strip() for pid in paper_ids.split(",") if pid.strip()]
    if len(ids) < 2:
        return "Error: Please provide at least 2 paper IDs separated by commas."

    papers_data = []
    for pid in ids[:5]:  # cap at 5 papers
        detail_json = await get_paper_detail.ainvoke({"paper_id": pid})
        detail = json.loads(detail_json)
        if "error" not in detail:
            papers_data.append(detail)

    if not papers_data:
        return "Error: Could not retrieve any of the specified papers."

    comparison_context = "Papers for comparison:\n\n"
    for p in papers_data:
        comparison_context += f"--- {p.get('title', p.get('paper_id'))} ---\n"
        comparison_context += f"Authors: {p.get('authors', 'N/A')}\n"
        comparison_context += f"Date: {p.get('published_date', 'N/A')}\n"
        text = p.get("full_text") or p.get("abstract", "")
        comparison_context += f"Content: {text[:1500]}\n\n"

    comparison_context += "\nPlease compare these papers on: approach/methodology, performance/results, novelty, and applicability."
    return comparison_context


# ── Tool: generate_report ─────────────────────────────────────────────────────

@tool
@traceable(name="generate_report")
async def generate_report(topic: str, paper_ids: str = "") -> str:
    """Generate a comprehensive Markdown research report on a topic.

    Retrieves relevant papers and prepares context for report generation.

    Args:
        topic: Research topic or question
        paper_ids: Optional comma-separated paper IDs to include

    Returns:
        Context and instructions for generating the research report
    """
    redis = get_redis_manager()

    # Collect relevant papers
    papers_context = []

    # Include explicitly specified papers
    if paper_ids:
        ids = [pid.strip() for pid in paper_ids.split(",") if pid.strip()]
        for pid in ids[:5]:
            detail_json = await get_paper_detail.ainvoke({"paper_id": pid})
            detail = json.loads(detail_json)
            if "error" not in detail:
                papers_context.append(detail)

    # Search for more relevant papers
    search_json = await search_papers.ainvoke({"query": topic, "max_results": 5})
    search_results = json.loads(search_json)

    existing_ids = {p.get("paper_id") for p in papers_context}
    for paper in search_results:
        if paper.get("paper_id") not in existing_ids:
            papers_context.append(paper)

    # Build context
    context_parts = [f"# Research Report Context: {topic}\n"]
    for p in papers_context[:8]:
        context_parts.append(f"## {p.get('title', 'Unknown')}")
        context_parts.append(f"**Authors**: {p.get('authors', 'N/A')} | **Date**: {p.get('published_date', 'N/A')}")
        context_parts.append(f"**ArXiv**: {p.get('arxiv_url', 'N/A')}")
        text = p.get("full_text") or p.get("abstract", "")
        context_parts.append(f"{text[:1000]}\n")

    context = "\n\n".join(context_parts)
    context += f"\n\nPlease generate a comprehensive Markdown research report on '{topic}' covering: overview, key findings, methodology trends, and future directions. Include citations to the papers above."

    return context


# ── Tool list for Agent ───────────────────────────────────────────────────────

AGENT_TOOLS = [
    search_papers,
    get_paper_detail,
    analyze_paper,
    compare_papers,
    generate_report,
]
