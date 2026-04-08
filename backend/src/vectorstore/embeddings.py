"""Aliyun text-embedding-v3 wrapper compatible with LangChain."""
import asyncio
import logging
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024  # text-embedding-v3 default output dimension


class DashScopeEmbeddings:
    """Aliyun DashScope text-embedding-v3 embedding client.

    Compatible drop-in for LangChain Embeddings interface.
    """

    def __init__(self, model: str = "text-embedding-v3", batch_size: int = 25):
        self.model = model
        self.batch_size = batch_size
        self._settings = get_settings()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents asynchronously."""
        all_embeddings: list[list[float]] = []

        # Process in batches to respect API limits
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            embeddings = await self._embed_batch(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def aembed_query(self, text: str) -> list[float]:
        """Embed a single query string asynchronously."""
        results = await self.aembed_documents([text])
        return results[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Synchronous wrapper for embed_documents."""
        return asyncio.get_event_loop().run_until_complete(self.aembed_documents(texts))

    def embed_query(self, text: str) -> list[float]:
        """Synchronous wrapper for embed_query."""
        return asyncio.get_event_loop().run_until_complete(self.aembed_query(text))

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Call DashScope embedding API for a batch of texts."""
        try:
            import dashscope
            from dashscope import TextEmbedding

            dashscope.api_key = self._settings.dashscope_api_key

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: TextEmbedding.call(
                    model=self.model,
                    input=texts,
                    text_type="document",
                ),
            )

            if resp.status_code != 200:
                raise RuntimeError(f"DashScope embedding error: {resp.code} - {resp.message}")

            # Sort by index to maintain order
            embeddings_data = sorted(resp.output["embeddings"], key=lambda x: x["text_index"])
            return [item["embedding"] for item in embeddings_data]

        except ImportError:
            logger.error("dashscope not installed. Run: pip install dashscope")
            raise

    async def aembed_query_for_search(self, text: str) -> list[float]:
        """Embed a query with query-optimized text_type."""
        try:
            import dashscope
            from dashscope import TextEmbedding

            dashscope.api_key = self._settings.dashscope_api_key

            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: TextEmbedding.call(
                    model=self.model,
                    input=[text],
                    text_type="query",
                ),
            )

            if resp.status_code != 200:
                raise RuntimeError(f"DashScope embedding error: {resp.code} - {resp.message}")

            return resp.output["embeddings"][0]["embedding"]

        except ImportError:
            logger.error("dashscope not installed.")
            raise
