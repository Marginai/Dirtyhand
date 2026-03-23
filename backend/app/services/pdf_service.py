from __future__ import annotations

import io
import logging
from typing import Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

logger = logging.getLogger(__name__)


class PDFService:
    """Extract text from PDFs and convert it into chunked LangChain Documents."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def extract_text_pages(
        self,
        pdf_bytes: bytes,
        *,
        max_pages: int = 0,
    ) -> list[str]:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        use_pages = total_pages if max_pages <= 0 else min(total_pages, max_pages)

        pages: list[str] = []
        for i in range(use_pages):
            page = reader.pages[i]
            text = page.extract_text() or ""
            pages.append(text)
        return pages

    def chunk_pages(
        self,
        pages_text: list[str],
        *,
        source: str,
    ) -> list[Document]:
        documents: list[Document] = []
        for idx, text in enumerate(pages_text, start=1):
            t = (text or "").strip()
            if not t:
                continue
            # Create documents from a single page so page-level metadata is preserved.
            docs = self._splitter.create_documents(
                [t],
                metadatas=[{"source": source, "page": idx}],
            )
            documents.extend(docs)
        return documents

