"""
backend/pipeline/rag.py
Hybrid RAG pipeline: FAISS (fast ANN) + ChromaDB (persistent, per-team).
Embedding model: BAAI/bge-base-en-v1.5 via sentence-transformers.
"""
from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

INDEXES_DIR = Path("data/indexes")
CHROMA_DIR = Path("data/chroma")
EMBED_MODEL = "BAAI/bge-base-en-v1.5"


class RAGPipeline:
    """
    Singleton-safe RAG pipeline.  Lazy-loads the embedding model on first use.
    Each team gets its own ChromaDB collection (team_{id}) and a separate FAISS
    index stored under data/indexes/team_{id}.faiss.
    """

    _instance: Optional["RAGPipeline"] = None
    _model = None  # sentence-transformers SentenceTransformer
    _chroma_client = None

    def __new__(cls) -> "RAGPipeline":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_model(self):
        if self._model is None:
            logger.info("RAGPipeline: loading embedding model %s …", EMBED_MODEL)
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMBED_MODEL)
            logger.info("RAGPipeline: model ready")

    def _ensure_chroma(self):
        if self._chroma_client is None:
            import chromadb
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # ── Embedding ─────────────────────────────────────────────────────────────
    def embed(self, texts: List[str]) -> np.ndarray:
        self._ensure_model()
        return self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    # ── Indexing ──────────────────────────────────────────────────────────────
    def index_team(self, team_id: str, text: str, chunk_size: int = 500):
        """
        Chunk text, embed, store in both FAISS and ChromaDB.
        Overwrites any existing index for this team.
        """
        self._ensure_model()
        self._ensure_chroma()
        INDEXES_DIR.mkdir(parents=True, exist_ok=True)

        # Chunk the text
        words = text.split()
        chunks: List[str] = []
        for i in range(0, max(1, len(words)), chunk_size):
            chunk = " ".join(words[i: i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
        if not chunks:
            chunks = [text or "empty submission"]

        embeddings = self.embed(chunks)  # shape (n_chunks, dim)

        # ── FAISS ─────────────────────────────────────────────────────────────
        import faiss
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)  # inner-product on normalized vecs = cosine
        index.add(embeddings.astype("float32"))
        faiss_path = INDEXES_DIR / f"team_{team_id}.faiss"
        meta_path = INDEXES_DIR / f"team_{team_id}.meta"
        faiss.write_index(index, str(faiss_path))
        with open(meta_path, "wb") as f:
            pickle.dump({"chunks": chunks}, f)

        # ── ChromaDB ──────────────────────────────────────────────────────────
        col_name = f"team_{team_id}"
        try:
            self._chroma_client.delete_collection(col_name)
        except Exception:
            pass
        col = self._chroma_client.create_collection(col_name, metadata={"hnsw:space": "cosine"})
        col.add(
            documents=chunks,
            embeddings=embeddings.tolist(),
            ids=[f"{team_id}_chunk_{i}" for i in range(len(chunks))],
            metadatas=[{"team_id": team_id, "chunk_idx": i} for i in range(len(chunks))],
        )
        logger.info("RAGPipeline: indexed %d chunks for team %s", len(chunks), team_id)

    def get_mean_embedding(self, team_id: str) -> Optional[np.ndarray]:
        """Return mean embedding vector for a team (used by similarity engine)."""
        faiss_path = INDEXES_DIR / f"team_{team_id}.faiss"
        meta_path = INDEXES_DIR / f"team_{team_id}.meta"
        if not faiss_path.exists() or not meta_path.exists():
            return None
        with open(meta_path, "rb") as f:
            meta = pickle.load(f)
        chunks = meta.get("chunks", [])
        if not chunks:
            return None
        embeddings = self.embed(chunks)
        return embeddings.mean(axis=0)

    # ── Retrieval ─────────────────────────────────────────────────────────────
    def retrieve(self, query: str, team_id: str, top_k: int = 5) -> List[str]:
        """
        Query both FAISS and ChromaDB, merge with reciprocal rank fusion.
        Returns top_k unique text chunks.
        """
        self._ensure_model()
        self._ensure_chroma()

        faiss_results = self._faiss_query(query, team_id, top_k * 2)
        chroma_results = self._chroma_query(query, team_id, top_k * 2)

        # Reciprocal Rank Fusion
        scores: dict[str, float] = {}
        for rank, doc in enumerate(faiss_results):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (rank + 60)
        for rank, doc in enumerate(chroma_results):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (rank + 60)

        merged = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)
        return merged[:top_k]

    def _faiss_query(self, query: str, team_id: str, k: int) -> List[str]:
        faiss_path = INDEXES_DIR / f"team_{team_id}.faiss"
        meta_path = INDEXES_DIR / f"team_{team_id}.meta"
        if not faiss_path.exists():
            return []
        try:
            import faiss
            index = faiss.read_index(str(faiss_path))
            with open(meta_path, "rb") as f:
                meta = pickle.load(f)
            q_emb = self.embed([query]).astype("float32")
            _, idxs = index.search(q_emb, min(k, index.ntotal))
            chunks = meta["chunks"]
            return [chunks[i] for i in idxs[0] if i < len(chunks)]
        except Exception as exc:
            logger.warning("FAISS query failed for team %s: %s", team_id, exc)
            return []

    def _chroma_query(self, query: str, team_id: str, k: int) -> List[str]:
        try:
            col = self._chroma_client.get_collection(f"team_{team_id}")
            q_emb = self.embed([query]).tolist()
            res = col.query(query_embeddings=q_emb, n_results=min(k, col.count()))
            return res["documents"][0] if res["documents"] else []
        except Exception as exc:
            logger.warning("ChromaDB query failed for team %s: %s", team_id, exc)
            return []


# Module-level singleton
rag_pipeline = RAGPipeline()
