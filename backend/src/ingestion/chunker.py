"""Text chunking for paper content."""
import logging
from dataclasses import dataclass
from typing import Optional

from langchain.text_splitter import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    paper_id: str
    chunk_index: int
    chunk_text: str
    # Metadata carried from parent paper
    title: str
    authors: str
    published_date: str
    arxiv_url: str


class PaperChunker:
    """Split paper text into overlapping chunks for embedding."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_length: int = 50,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_length = min_chunk_length

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def chunk_paper(
        self,
        paper_id: str,
        text: str,
        title: str,
        authors: str,
        published_date: str,
        arxiv_url: str,
        prepend_metadata: bool = True,
    ) -> list[TextChunk]:
        """Split a paper's text into chunks.

        Args:
            paper_id: ArXiv paper ID
            text: Full text (or abstract if PDF not available)
            title: Paper title
            authors: Authors string
            published_date: Publication date
            arxiv_url: ArXiv URL
            prepend_metadata: If True, prepend title+authors to first chunk

        Returns:
            List of TextChunk objects
        """
        if not text or len(text.strip()) < self.min_chunk_length:
            logger.warning(f"Text too short for paper {paper_id}, skipping")
            return []

        # Prepend metadata to provide context for retrieval
        if prepend_metadata:
            header = f"Title: {title}\nAuthors: {authors}\nDate: {published_date}\n\n"
            text = header + text

        raw_chunks = self._splitter.split_text(text)

        chunks: list[TextChunk] = []
        for idx, chunk_text in enumerate(raw_chunks):
            stripped = chunk_text.strip()
            if len(stripped) < self.min_chunk_length:
                continue
            chunks.append(
                TextChunk(
                    paper_id=paper_id,
                    chunk_index=idx,
                    chunk_text=stripped[:2048],  # hard cap for Milvus VARCHAR
                    title=title,
                    authors=authors,
                    published_date=published_date,
                    arxiv_url=arxiv_url,
                )
            )

        logger.debug(f"Created {len(chunks)} chunks for paper {paper_id}")
        return chunks

    def chunk_abstract_only(
        self,
        paper_id: str,
        title: str,
        abstract: str,
        authors: str,
        published_date: str,
        arxiv_url: str,
    ) -> list[TextChunk]:
        """Create chunks from abstract only (fallback when PDF unavailable)."""
        text = f"Title: {title}\nAuthors: {authors}\nDate: {published_date}\n\nAbstract: {abstract}"
        return self.chunk_paper(
            paper_id=paper_id,
            text=text,
            title=title,
            authors=authors,
            published_date=published_date,
            arxiv_url=arxiv_url,
            prepend_metadata=False,
        )
