"""ArXiv API fetcher with rate limiting and retry logic."""
import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import arxiv
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class ArxivPaper:
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    published_date: str
    arxiv_url: str
    pdf_url: str
    categories: list[str]
    doi: Optional[str] = None

    @property
    def authors_str(self) -> str:
        return ", ".join(self.authors[:5])  # cap at 5 authors

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": self.authors_str,
            "abstract": self.abstract,
            "published_date": self.published_date,
            "arxiv_url": self.arxiv_url,
            "pdf_url": self.pdf_url,
            "categories": self.categories,
        }


class ArxivFetcher:
    """Fetch papers from ArXiv API with caching support."""

    def __init__(self, max_results_per_query: int = 20):
        self.max_results_per_query = max_results_per_query
        self._client = arxiv.Client(
            page_size=100,
            delay_seconds=3.0,
            num_retries=3,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        max_results: int = 10,
        categories: Optional[list[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sort_by: arxiv.SortCriterion = arxiv.SortCriterion.Relevance,
    ) -> list[ArxivPaper]:
        """Search ArXiv papers by keyword query.

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            categories: Optional list of ArXiv categories (e.g. ['cs.AI', 'cs.CL'])
            date_from: Start date filter in YYYYMMDD format
            date_to: End date filter in YYYYMMDD format
            sort_by: Sort criterion

        Returns:
            List of ArxivPaper dataclasses
        """
        # Build query with optional category filter
        full_query = query
        if categories:
            cat_filter = " OR ".join(f"cat:{c}" for c in categories)
            full_query = f"({query}) AND ({cat_filter})"
        if date_from or date_to:
            date_part = f"[{date_from or '19000101'} TO {date_to or '99991231'}]"
            full_query = f"{full_query} AND submittedDate:{date_part}"

        logger.info(f"Searching ArXiv: {full_query!r}, max_results={max_results}")

        search = arxiv.Search(
            query=full_query,
            max_results=min(max_results, self.max_results_per_query),
            sort_by=sort_by,
        )

        papers: list[ArxivPaper] = []
        # Run synchronous client in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: list(self._client.results(search)))

        for result in results:
            paper_id = result.entry_id.split("/")[-1]  # e.g. "2401.12345v1"
            paper_id = paper_id.split("v")[0]  # strip version: "2401.12345"

            papers.append(
                ArxivPaper(
                    paper_id=paper_id,
                    title=result.title.strip().replace("\n", " "),
                    authors=[str(a) for a in result.authors],
                    abstract=result.summary.strip().replace("\n", " "),
                    published_date=result.published.strftime("%Y-%m-%d"),
                    arxiv_url=result.entry_id,
                    pdf_url=result.pdf_url,
                    categories=[str(c) for c in result.categories],
                    doi=result.doi,
                )
            )

        logger.info(f"Found {len(papers)} papers for query {query!r}")
        return papers

    async def fetch_by_id(self, paper_id: str) -> Optional[ArxivPaper]:
        """Fetch a single paper by ArXiv ID."""
        search = arxiv.Search(id_list=[paper_id])
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: list(self._client.results(search)))
        if not results:
            return None
        result = results[0]
        pid = result.entry_id.split("/")[-1].split("v")[0]
        return ArxivPaper(
            paper_id=pid,
            title=result.title.strip().replace("\n", " "),
            authors=[str(a) for a in result.authors],
            abstract=result.summary.strip().replace("\n", " "),
            published_date=result.published.strftime("%Y-%m-%d"),
            arxiv_url=result.entry_id,
            pdf_url=result.pdf_url,
            categories=[str(c) for c in result.categories],
            doi=result.doi,
        )

    @staticmethod
    def query_hash(query: str, **kwargs) -> str:
        """Generate a stable hash for a query + params combo (for caching)."""
        key_str = query + str(sorted(kwargs.items()))
        return hashlib.md5(key_str.encode()).hexdigest()
