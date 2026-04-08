"""Milvus vector store client for paper chunks."""
import logging
from typing import Optional

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusException,
    connections,
    utility,
)

from src.config import get_settings
from src.ingestion.chunker import TextChunk
from src.vectorstore.embeddings import EMBEDDING_DIM, DashScopeEmbeddings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "arxiv_papers"
INDEX_PARAMS = {
    "metric_type": "COSINE",
    "index_type": "IVF_FLAT",
    "params": {"nlist": 1024},
}
SEARCH_PARAMS = {"metric_type": "COSINE", "params": {"nprobe": 16}}


class MilvusClient:
    """Manage Milvus collection for ArXiv paper embeddings."""

    def __init__(self):
        self._settings = get_settings()
        self._embeddings = DashScopeEmbeddings()
        self._collection: Optional[Collection] = None

    def connect(self) -> None:
        """Connect to Milvus server."""
        connections.connect(
            alias="default",
            host=self._settings.milvus_host,
            port=self._settings.milvus_port,
        )
        logger.info(f"Connected to Milvus at {self._settings.milvus_host}:{self._settings.milvus_port}")
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist, then load it."""
        if not utility.has_collection(COLLECTION_NAME):
            self._create_collection()
        self._collection = Collection(COLLECTION_NAME)
        # Build index if none exists
        if not self._collection.has_index():
            self._collection.create_index(field_name="embedding", index_params=INDEX_PARAMS)
            logger.info("Created COSINE index on 'embedding' field")
        self._collection.load()
        logger.info(f"Collection '{COLLECTION_NAME}' loaded")

    def _create_collection(self) -> None:
        """Define and create the Milvus collection schema."""
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="paper_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="authors", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="published_date", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="chunk_index", dtype=DataType.INT32),
            FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
            FieldSchema(name="arxiv_url", dtype=DataType.VARCHAR, max_length=256),
        ]
        schema = CollectionSchema(
            fields=fields,
            description="ArXiv paper chunks with embeddings",
            enable_dynamic_field=True,
        )
        Collection(name=COLLECTION_NAME, schema=schema)
        logger.info(f"Created collection '{COLLECTION_NAME}'")

    @property
    def collection(self) -> Collection:
        if self._collection is None:
            raise RuntimeError("MilvusClient not connected. Call connect() first.")
        return self._collection

    async def insert_chunks(self, chunks: list[TextChunk]) -> int:
        """Embed and insert chunks into Milvus.

        Returns:
            Number of chunks inserted.
        """
        if not chunks:
            return 0

        # Skip chunks already in Milvus
        new_chunks = await self._filter_existing(chunks)
        if not new_chunks:
            logger.info("All chunks already exist in Milvus")
            return 0

        # Embed all chunk texts
        texts = [c.chunk_text for c in new_chunks]
        embeddings = await self._embeddings.aembed_documents(texts)

        data = {
            "paper_id": [c.paper_id for c in new_chunks],
            "title": [c.title[:512] for c in new_chunks],
            "authors": [c.authors[:256] for c in new_chunks],
            "published_date": [c.published_date for c in new_chunks],
            "chunk_index": [c.chunk_index for c in new_chunks],
            "chunk_text": [c.chunk_text for c in new_chunks],
            "embedding": embeddings,
            "arxiv_url": [c.arxiv_url[:256] for c in new_chunks],
        }

        self.collection.insert(list(data.values()))
        self.collection.flush()
        logger.info(f"Inserted {len(new_chunks)} chunks into Milvus")
        return len(new_chunks)

    async def _filter_existing(self, chunks: list[TextChunk]) -> list[TextChunk]:
        """Return only chunks whose paper_id+chunk_index don't exist yet."""
        # Group by paper_id
        paper_ids = list({c.paper_id for c in chunks})
        id_filter = " || ".join(f'paper_id == "{pid}"' for pid in paper_ids)
        try:
            results = self.collection.query(
                expr=id_filter,
                output_fields=["paper_id", "chunk_index"],
                limit=len(chunks) + 100,
            )
            existing = {(r["paper_id"], r["chunk_index"]) for r in results}
            return [c for c in chunks if (c.paper_id, c.chunk_index) not in existing]
        except MilvusException as e:
            logger.warning(f"Could not check existing chunks: {e}. Inserting all.")
            return chunks

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_expr: Optional[str] = None,
    ) -> list[dict]:
        """Semantic search over paper chunks.

        Returns:
            List of dicts with chunk metadata and similarity score.
        """
        query_embedding = await self._embeddings.aembed_query_for_search(query)

        results = self.collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=SEARCH_PARAMS,
            limit=top_k,
            expr=filter_expr,
            output_fields=["paper_id", "title", "authors", "published_date", "chunk_text", "arxiv_url", "chunk_index"],
        )

        hits: list[dict] = []
        for hit in results[0]:
            hits.append(
                {
                    "paper_id": hit.entity.get("paper_id"),
                    "title": hit.entity.get("title"),
                    "authors": hit.entity.get("authors"),
                    "published_date": hit.entity.get("published_date"),
                    "chunk_text": hit.entity.get("chunk_text"),
                    "arxiv_url": hit.entity.get("arxiv_url"),
                    "chunk_index": hit.entity.get("chunk_index"),
                    "score": hit.score,
                }
            )
        return hits

    async def get_paper_chunks(self, paper_id: str) -> list[dict]:
        """Retrieve all chunks for a specific paper, sorted by chunk_index."""
        results = self.collection.query(
            expr=f'paper_id == "{paper_id}"',
            output_fields=["paper_id", "title", "authors", "published_date", "chunk_text", "arxiv_url", "chunk_index"],
            limit=500,
        )
        return sorted(results, key=lambda x: x.get("chunk_index", 0))

    async def delete_paper(self, paper_id: str) -> int:
        """Delete all chunks for a paper from Milvus.

        Returns:
            Number of chunks deleted.
        """
        expr = f'paper_id == "{paper_id}"'
        result = self.collection.delete(expr)
        self.collection.flush()
        logger.info(f"Deleted chunks for paper {paper_id} (count={result.delete_count})")
        return result.delete_count

    def get_collection_stats(self) -> dict:
        """Return collection statistics."""
        stats = utility.get_query_segment_info(COLLECTION_NAME)
        count = self.collection.num_entities
        return {"collection": COLLECTION_NAME, "num_entities": count}
