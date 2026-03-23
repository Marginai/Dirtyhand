"""Persistent Chroma RAG — replaces conversational MemorySaver for document context."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.exceptions import ConfigurationError, RAGError
from app.settings import Settings, get_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        if not self._settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is not set in environment")
        self._embeddings = OpenAIEmbeddings(
            api_key=self._settings.openai_api_key,
            model=self._settings.embedding_model,
        )
        self._persist = self._settings.chroma_persist_dir
        self._persist.mkdir(parents=True, exist_ok=True)
        self._collection = self._settings.rag_collection_name
        self._vectorstore: Chroma | None = None
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)

    @property
    def vectorstore(self) -> Chroma:
        if self._vectorstore is None:
            self._vectorstore = Chroma(
                collection_name=self._collection,
                embedding_function=self._embeddings,
                persist_directory=str(self._persist),
            )
        return self._vectorstore

    def add_text(self, text: str, metadata: dict | None = None) -> int:
        """Chunk and ingest plain text."""
        if not text.strip():
            raise RAGError("Empty text cannot be ingested")
        docs = self._splitter.create_documents([text], metadatas=[metadata or {}])
        return self.add_documents(docs)

    def add_documents(self, documents: list[Document]) -> int:
        try:
            self.vectorstore.add_documents(documents)
            if hasattr(self.vectorstore, "persist"):
                self.vectorstore.persist()
        except Exception as e:
            logger.exception("RAG ingest failed")
            raise RAGError(str(e)) from e
        return len(documents)

    def similarity_search(self, query: str, k: int | None = None) -> list[Document]:
        k = k if k is not None else self._settings.rag_retrieval_k
        try:
            return self.vectorstore.similarity_search(query, k=k)
        except Exception as e:
            logger.exception("RAG search failed")
            raise RAGError(str(e)) from e

    def format_context(self, query: str, k: int | None = None) -> str:
        # Phase 2 guardrails:
        # - filter by similarity threshold (when Chroma provides relevance scores)
        # - cap max docs injected into the LLM context
        k = k if k is not None else self._settings.rag_retrieval_k
        max_docs = min(k, self._settings.rag_max_docs_in_context)
        min_relevance = self._settings.rag_min_relevance

        docs_with_scores: list[tuple[Document, float]]
        try:
            # Many LangChain vectorstores implement this; scores are higher-is-better.
            docs_with_scores = self.vectorstore.similarity_search_with_relevance_scores(query, k=k)
        except Exception:
            # Fallback: if relevance scores aren't available, preserve existing behavior.
            docs = self.similarity_search(query, k=k)
            docs_with_scores = [(d, 1.0) for d in docs]

        # Filter by threshold (default 0.0 preserves current behavior).
        filtered = [(d, s) for (d, s) in docs_with_scores if s >= min_relevance]
        if not filtered:
            return ""

        parts: list[str] = []
        for i, (d, _) in enumerate(filtered[:max_docs], 1):
            src = d.metadata.get("source", "document")
            parts.append(f"[{i}] (source: {src})\n{d.page_content}")
        return "\n\n---\n\n".join(parts)
