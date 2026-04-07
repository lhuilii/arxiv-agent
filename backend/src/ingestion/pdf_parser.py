"""PDF parser using PyMuPDF (fitz) to extract full text from ArXiv PDFs."""
import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class PDFParser:
    """Download and parse PDF content from ArXiv."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    async def download_and_parse(self, pdf_url: str, paper_id: str) -> Optional[str]:
        """Download PDF and extract text content.

        Returns:
            Extracted text or None if download/parsing fails.
        """
        try:
            content = await self._download_pdf(pdf_url)
            if content is None:
                return None
            return await self._extract_text(content, paper_id)
        except Exception as e:
            logger.warning(f"Failed to parse PDF for {paper_id}: {e}")
            return None

    async def _download_pdf(self, url: str) -> Optional[bytes]:
        """Download PDF bytes from URL."""
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    async def _extract_text(self, pdf_bytes: bytes, paper_id: str) -> str:
        """Extract text from PDF bytes using PyMuPDF (runs in executor)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_extract, pdf_bytes, paper_id)

    @staticmethod
    def _sync_extract(pdf_bytes: bytes, paper_id: str) -> str:
        """Synchronous PDF text extraction."""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages_text: list[str] = []

            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text("text")
                if text.strip():
                    pages_text.append(text)

            doc.close()
            full_text = "\n\n".join(pages_text)
            # Clean up common PDF artifacts
            full_text = PDFParser._clean_text(full_text)
            logger.info(f"Extracted {len(full_text)} chars from {paper_id}")
            return full_text

        except ImportError:
            logger.error("PyMuPDF not installed. Run: pip install pymupdf")
            raise
        except Exception as e:
            logger.error(f"PDF extraction failed for {paper_id}: {e}")
            raise

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean extracted PDF text."""
        # Remove hyphenation at line breaks
        text = re.sub(r"-\n([a-z])", r"\1", text)
        # Normalize multiple whitespace but preserve paragraph breaks
        text = re.sub(r" +", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove page numbers (lines with only digits)
        text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
        return text.strip()
