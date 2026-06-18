"""
Doctor Profiles Ingestion Pipeline (FAISS)

Loads structured doctor profile JSON, converts to LangChain Documents with rich metadata,
applies SemanticChunker to create coherent RAG-friendly chunks, embeds, and stores in a local
FAISS vector index for quick RAG testing without Weaviate.

Usage (PowerShell):
  # Ensure env has required packages installed (requirements.txt) and faiss-cpu is available
  # python ingest_doctors_Faiss.py --input docs/doctors_by_specialty.json --faiss-dir .faiss_index

Notes:
- This script uses langchain_community.vectorstores.FAISS. Install with: pip install faiss-cpu
- Embeddings use the OpenAIEmbeddingWrapper, relying on OpenAI's hosted embedding APIs.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import load_config

# LangChain core
try:
    from langchain_core.documents import Document
except Exception:  # langchain<0.2 fallback
    from langchain.schema import Document  # type: ignore

# Vector store: FAISS
try:
    from langchain_community.vectorstores import FAISS
except Exception as e:  # Pragmatic message if dependency missing
    raise ImportError(
        "FAISS vector store not available. Please install 'faiss-cpu' and 'langchain-community'."
    ) from e

# Text splitter (SemanticChunker)
try:
    from langchain_text_splitters import SemanticChunker
except Exception:
    from langchain_experimental.text_splitter import SemanticChunker  # type: ignore

# Embeddings adapter for our OpenAI embedding wrapper
from embedding import OpenAIEmbeddingWrapper


class LCEmbeddingAdapter:
    """Adapts OpenAIEmbeddingWrapper to the LangChain Embeddings interface."""

    def __init__(
        self,
        base: Optional[OpenAIEmbeddingWrapper] = None,
        *,
        model_name: Optional[str] = None,
        dimensions: Optional[int] = None,
        **kwargs: object,
    ) -> None:
        if base is not None:
            self.base = base
        else:
            self.base = OpenAIEmbeddingWrapper(model_name=model_name, dimensions=dimensions, **kwargs)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.base.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.base.embed_query(text)

    # Some vector stores (FAISS community implementation) may treat the embedding_function
    # as a callable. Implement __call__ to be robust across versions.
    def __call__(self, text: str) -> List[float]:
        return self.embed_query(text)


@dataclass
class DoctorSection:
    doctor_name: str
    specialty: Optional[str]
    section: str
    content: str
    extra_meta: Dict[str, Any]

    def to_document(self) -> Document:
        meta = {
            "full_name": self.doctor_name,
            "specialty": self.specialty,
            "section": self.section,
        }
        meta.update(self.extra_meta)
        text = self.content.strip()
        return Document(page_content=text, metadata=meta)


def load_doctors_json(input_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Expected top-level JSON object mapping specialties to lists of doctors.")
    return data


def sections_from_profile(specialty_key: str, profile: Dict[str, Any]) -> List[DoctorSection]:
    name = profile.get("full_name") or profile.get("name") or "Unknown"
    specialty = profile.get("specialty") or specialty_key

    brief = profile.get("brief_profile") or profile.get("biography") or ""
    quals = profile.get("qualifications") or []
    comps = profile.get("core_competencies") or []
    experience = profile.get("experience") or ""
    languages = profile.get("languages") or ""
    tagline = profile.get("tagline") or ""
    specialties = profile.get("specialties") or []

    chunks: List[DoctorSection] = []

    if tagline:
        chunks.append(DoctorSection(name, specialty, "tagline", str(tagline), {}))
    if brief:
        chunks.append(DoctorSection(name, specialty, "biography", str(brief), {}))
    if quals:
        content = "Qualifications:\n- " + "\n- ".join(map(str, quals))
        chunks.append(DoctorSection(name, specialty, "qualifications", content, {}))
    if comps:
        content = "Core Competencies:\n- " + "\n- ".join(map(str, comps))
        chunks.append(DoctorSection(name, specialty, "core_competencies", content, {}))
    if experience:
        chunks.append(DoctorSection(name, specialty, "experience", str(experience), {}))
    if languages:
        chunks.append(DoctorSection(name, specialty, "languages", str(languages), {}))
    if specialties:
        content = "Specialties: " + ", ".join(map(str, specialties))
        chunks.append(DoctorSection(name, specialty, "specialties", content, {}))

    # Synthesize compact facts
    facts_parts = []
    if tagline:
        facts_parts.append(tagline)
    if experience:
        facts_parts.append(f"Experience: {experience}")
    if languages:
        facts_parts.append(f"Languages: {languages}")
    if specialties:
        facts_parts.append("Specialties: " + ", ".join(map(str, specialties)))
    if quals:
        facts_parts.append("Top qualification: " + str(quals[0]))
    if facts_parts:
        chunks.append(DoctorSection(name, specialty, "facts", " | ".join(facts_parts), {"synthesized": True}))

    return chunks


def to_documents(raw: Dict[str, List[Dict[str, Any]]]) -> List[Document]:
    docs: List[Document] = []
    for specialty_key, profiles in raw.items():
        if not isinstance(profiles, list):
            continue
        for profile in profiles:
            for sec in sections_from_profile(specialty_key, profile):
                docs.append(sec.to_document())
    return docs


def semantically_split(docs: List[Document]) -> List[Document]:
    """Apply semantic chunking per document with guardrails on size."""
    if not docs:
        return []

    embeddings = LCEmbeddingAdapter()
    splitter = SemanticChunker(
        embeddings,
        breakpoint_threshold_type="percentile",
        breakpoint_threshold_amount=95,
        min_chunk_size=200,
    )

    out: List[Document] = []
    for d in docs:
        parts = splitter.split_documents([d])
        for p in parts:
            p.metadata.setdefault("full_name", d.metadata.get("full_name"))
            p.metadata.setdefault("specialty", d.metadata.get("specialty"))
            p.metadata.setdefault("section", d.metadata.get("section"))
            out.append(p)
    return out


def ingest(input_path: Path, faiss_dir: Path) -> int:
    print("[DEBUG] Loading doctors JSON...")
    raw = load_doctors_json(input_path)
    print(f"[DEBUG] Loaded JSON with {len(raw)} specialties.")

    print("[DEBUG] Converting to LangChain documents...")
    base_docs = to_documents(raw)
    print(f"[DEBUG] Created {len(base_docs)} base documents.")

    print("[DEBUG] Running semantic chunking...")
    chunked = semantically_split(base_docs)
    print(f"[DEBUG] Semantic chunking produced {len(chunked)} chunks.")

    print("[DEBUG] Initializing embeddings and building FAISS index...")
    embed = LCEmbeddingAdapter()
    vectorstore = FAISS.from_documents(chunked, embed)

    faiss_dir.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(faiss_dir))
    print(f"[DEBUG] FAISS index saved to: {faiss_dir}")
    return len(chunked)


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Ingest doctor profiles JSON into a local FAISS index with semantic chunks.")
    parser.add_argument("--input", type=str, default=str(Path("docs") / "doctors_by_specialty.json"))
    parser.add_argument("--faiss-dir", type=str, default=str(Path(".faiss_index")), help="Directory to store the FAISS index")
    parser.add_argument("--recreate", action="store_true", help="Delete any existing index directory before ingesting")

    args = parser.parse_args(argv)

    input_path = Path(args.input)
    faiss_dir = Path(args.faiss_dir)

    if args.recreate and faiss_dir.exists():
        print(f"[DEBUG] Recreating index directory: {faiss_dir}")
        shutil.rmtree(faiss_dir)

    count = ingest(input_path, faiss_dir)
    print(f"✅ Ingestion complete. Total chunks stored in FAISS: {count}")


if __name__ == "__main__":
    main()
