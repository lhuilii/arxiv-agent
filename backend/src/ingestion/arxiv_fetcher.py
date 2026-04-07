"""ArXiv paper fetcher.

Uses the ArXiv Atom feed API directly via httpx so we can:
  - Set a proper User-Agent (required by ArXiv ToS)
  - Enforce ≤1 req/s rate limit
  - Add hard per-request timeout
  - Support OAI-PMH for bulk/incremental metadata harvest

ArXiv API guidelines: https://info.arxiv.org/help/api/user-manual.html
OAI-PMH endpoint:    https://export.arxiv.org/oai2
"""
import asyncio
import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)

# ArXiv asks for a descriptive User-Agent so they can contact abusers
_USER_AGENT = (
    "arxiv-agent/0.1 (academic research tool; "
    "https://github.com/lhuilii/arxiv-agent) httpx/0.28"
)
_ATOM_BASE = "https://export.arxiv.org/api/query"
_OAI_BASE = "https://export.arxiv.org/oai2"

# Global rate-limit state: ≤1 request/second across all instances
_last_request_time: float = 0.0
_rate_lock = asyncio.Lock()


async def _rate_limited_get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """Enforce ≤1 req/s and add User-Agent on every request."""
    global _last_request_time
    async with _rate_lock:
        now = time.monotonic()
        wait = 1.0 - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()

    headers = kwargs.pop("headers", {})
    headers["User-Agent"] = _USER_AGENT
    response = await client.get(url, headers=headers, **kwargs)
    return response


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
        return ", ".join(self.authors[:5])

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


def _entry_to_paper(entry: dict) -> ArxivPaper:
    """Convert a feedparser entry dict to ArxivPaper."""
    raw_id = entry.get("id", "")
    paper_id = raw_id.split("/abs/")[-1].split("v")[0]

    pdf_url = ""
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url:
        pdf_url = raw_id.replace("/abs/", "/pdf/")

    authors = [a.get("name", "") for a in entry.get("authors", [])]
    categories = [t.get("term", "") for t in entry.get("tags", [])]

    published = entry.get("published", "")
    try:
        published_date = datetime.fromisoformat(published.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        published_date = published[:10]

    return ArxivPaper(
        paper_id=paper_id,
        title=entry.get("title", "").strip().replace("\n", " "),
        authors=authors,
        abstract=entry.get("summary", "").strip().replace("\n", " "),
        published_date=published_date,
        arxiv_url=raw_id,
        pdf_url=pdf_url,
        categories=categories,
        doi=entry.get("arxiv_doi"),
    )


class ArxivFetcher:
    """Fetch papers from ArXiv using the Atom feed API.

    Complies with ArXiv usage guidelines:
    - User-Agent header set on every request
    - ≤ 1 request/second enforced globally
    - Per-request timeout to prevent indefinite blocking
    """

    def __init__(self, request_timeout: float = 20.0):
        self.request_timeout = request_timeout

    async def search(
        self,
        query: str,
        max_results: int = 10,
        categories: Optional[list[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sort_by: str = "relevance",  # "relevance" | "lastUpdatedDate" | "submittedDate"
        sort_order: str = "descending",
    ) -> list[ArxivPaper]:
        """Search ArXiv via the Atom feed API.

        Args:
            query: Search query string
            max_results: Number of results (capped at 50)
            categories: Filter by ArXiv categories e.g. ['cs.AI', 'cs.CL']
            date_from: Not directly supported by Atom API; use OAI-PMH instead
            sort_by: "relevance", "lastUpdatedDate", or "submittedDate"
            sort_order: "descending" or "ascending"
        """
        max_results = min(max_results, 50)

        full_query = query
        if categories:
            cat_filter = " OR ".join(f"cat:{c}" for c in categories)
            full_query = f"({query}) AND ({cat_filter})"

        params = {
            "search_query": full_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }

        logger.info(f"ArXiv search: {full_query!r} max={max_results}")

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            try:
                resp = await _rate_limited_get(client, _ATOM_BASE, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"ArXiv API HTTP error: {e.response.status_code} for query {query!r}")
                return []
            except httpx.TimeoutException:
                logger.warning(f"ArXiv API timeout for query {query!r}")
                return []
            except httpx.RequestError as e:
                logger.error(f"ArXiv API request error: {e}")
                return []

        feed = feedparser.parse(resp.text)
        papers = [_entry_to_paper(e) for e in feed.get("entries", [])]
        logger.info(f"ArXiv returned {len(papers)} papers for {query!r}")
        return papers

    async def fetch_by_id(self, paper_id: str) -> Optional[ArxivPaper]:
        """Fetch a single paper by ArXiv ID."""
        params = {"id_list": paper_id, "max_results": 1}
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            try:
                resp = await _rate_limited_get(client, _ATOM_BASE, params=params)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"ArXiv fetch_by_id failed for {paper_id}: {e}")
                return None

        feed = feedparser.parse(resp.text)
        entries = feed.get("entries", [])
        if not entries:
            return None
        return _entry_to_paper(entries[0])

    async def oai_harvest(
        self,
        from_date: Optional[str] = None,
        until_date: Optional[str] = None,
        set_spec: str = "cs",
        max_records: int = 100,
    ) -> list[ArxivPaper]:
        """Harvest paper metadata via OAI-PMH (recommended for bulk access).

        Args:
            from_date: Start date in YYYY-MM-DD format (inclusive)
            until_date: End date in YYYY-MM-DD format (inclusive)
            set_spec: ArXiv set, e.g. "cs", "cs:AI", "physics"
            max_records: Maximum number of records to return

        Returns:
            List of ArxivPaper from OAI-PMH metadata records
        """
        params: dict = {
            "verb": "ListRecords",
            "metadataPrefix": "arXiv",
            "set": set_spec,
        }
        if from_date:
            params["from"] = from_date
        if until_date:
            params["until"] = until_date

        papers: list[ArxivPaper] = []
        resumption_token: Optional[str] = None

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            while len(papers) < max_records:
                if resumption_token:
                    req_params = {"verb": "ListRecords", "resumptionToken": resumption_token}
                else:
                    req_params = params

                try:
                    resp = await _rate_limited_get(client, _OAI_BASE, params=req_params)
                    resp.raise_for_status()
                except Exception as e:
                    logger.error(f"OAI-PMH request failed: {e}")
                    break

                batch, resumption_token = _parse_oai_response(resp.text)
                papers.extend(batch)
                logger.info(f"OAI-PMH harvested {len(batch)} records (total {len(papers)})")

                if not resumption_token or not batch:
                    break

        return papers[:max_records]

    @staticmethod
    def query_hash(query: str, **kwargs) -> str:
        """Generate a stable hash for a query + params combo (for caching)."""
        key_str = query + str(sorted(kwargs.items()))
        return hashlib.md5(key_str.encode()).hexdigest()


# ── OAI-PMH XML parsing ───────────────────────────────────────────────────────

_OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}


def _parse_oai_response(xml_text: str) -> tuple[list[ArxivPaper], Optional[str]]:
    """Parse OAI-PMH ListRecords response. Returns (papers, resumption_token)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"OAI-PMH XML parse error: {e}")
        return [], None

    papers: list[ArxivPaper] = []
    list_records = root.find("oai:ListRecords", _OAI_NS)
    if list_records is None:
        return [], None

    for record in list_records.findall("oai:record", _OAI_NS):
        header = record.find("oai:header", _OAI_NS)
        metadata = record.find("oai:metadata", _OAI_NS)
        if header is None or metadata is None:
            continue
        # Skip deleted records
        if header.get("status") == "deleted":
            continue

        arxiv_meta = metadata.find("arxiv:arXiv", _OAI_NS)
        if arxiv_meta is None:
            continue

        def _text(tag: str) -> str:
            el = arxiv_meta.find(f"arxiv:{tag}", _OAI_NS)
            return el.text.strip() if el is not None and el.text else ""

        paper_id = _text("id")
        title = _text("title").replace("\n", " ")
        abstract = _text("abstract").replace("\n", " ")
        created = _text("created")  # YYYY-MM-DD
        categories_raw = _text("categories")
        categories = categories_raw.split() if categories_raw else []

        authors: list[str] = []
        for author_el in arxiv_meta.findall("arxiv:authors/arxiv:author", _OAI_NS):
            keyname = author_el.findtext("arxiv:keyname", "", _OAI_NS)
            forenames = author_el.findtext("arxiv:forenames", "", _OAI_NS)
            name = f"{forenames} {keyname}".strip()
            if name:
                authors.append(name)

        if not paper_id:
            continue

        papers.append(
            ArxivPaper(
                paper_id=paper_id,
                title=title,
                authors=authors,
                abstract=abstract,
                published_date=created,
                arxiv_url=f"https://arxiv.org/abs/{paper_id}",
                pdf_url=f"https://arxiv.org/pdf/{paper_id}",
                categories=categories,
            )
        )

    # Extract resumption token for pagination
    token_el = list_records.find("oai:resumptionToken", _OAI_NS)
    resumption_token = token_el.text if token_el is not None and token_el.text else None

    return papers, resumption_token
