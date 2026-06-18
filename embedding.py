"""Utility helpers for working with embedding models."""

from __future__ import annotations

import os
from typing import List, Optional
from dotenv import load_dotenv

from langchain_openai import OpenAIEmbeddings

# Load environment variables
load_dotenv()

DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"


class OpenAIEmbeddingWrapper:
    """Thin wrapper around LangChain's OpenAIEmbeddings with sensible defaults."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        *,
        dimensions: Optional[int] = None,
        client: Optional[OpenAIEmbeddings] = None,
        **kwargs: object,
    ) -> None:
        self.model_name = model_name or os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBEDDING_MODEL)
        if client is not None:
            self._client = client
        else:
            init_kwargs = dict(kwargs)
            if dimensions is None:
                dim_override = os.getenv("OPENAI_EMBEDDING_DIM")
                if dim_override:
                    try:
                        dimensions = int(dim_override)
                    except ValueError:
                        print(f"⚠️ Invalid OPENAI_EMBEDDING_DIM value '{dim_override}', ignoring override.")
            if dimensions is not None:
                init_kwargs["dimensions"] = dimensions
            init_kwargs.setdefault("model", self.model_name)
            print(f"🧠 Using OpenAI embedding model '{init_kwargs['model']}'.")
            self._client = OpenAIEmbeddings(**init_kwargs)

    @property
    def client(self) -> OpenAIEmbeddings:
        return self._client

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.client.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.client.embed_query(text)

    def __call__(self, text: str) -> List[float]:
        return self.embed_query(text)