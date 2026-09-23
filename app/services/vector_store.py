"""本地向量库：hash embedding + JSON 持久化（Milvus 的轻量替代）。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

EMBED_DIM = 384
EMBED_MODEL = "hash-v0"


def embed_text(text: str, *, dim: int = EMBED_DIM) -> list[float]:
    """确定性字符 n-gram 哈希向量，无需外部 Embedding API。"""
    raw = (text or "").strip().lower()
    vec = [0.0] * dim
    if not raw:
        return vec
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]{2,}", raw)
    grams: list[str] = []
    for i, tok in enumerate(tokens):
        grams.append(tok)
        if i + 1 < len(tokens):
            grams.append(tok + tokens[i + 1])
        if i + 2 < len(tokens):
            grams.append(tok + tokens[i + 1] + tokens[i + 2])
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
        vec[(h // dim) % dim] += 0.5
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


class LocalVectorStore:
    """文件级向量索引：key=vector_id。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._items = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            self._items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._items, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def upsert(
        self,
        *,
        vector_id: str,
        embedding: list[float],
        chunk_id: int,
        document_id: int,
        category: str | None = None,
    ) -> None:
        self._items[vector_id] = {
            "embedding": embedding,
            "chunkId": chunk_id,
            "documentId": document_id,
            "category": category or "",
        }
        self._save()

    def delete_by_document(self, document_id: int) -> int:
        to_del = [
            vid
            for vid, meta in self._items.items()
            if int(meta.get("documentId") or 0) == document_id
        ]
        for vid in to_del:
            self._items.pop(vid, None)
        if to_del:
            self._save()
        return len(to_del)

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for vid, meta in self._items.items():
            if category and (meta.get("category") or "") != category:
                continue
            emb = meta.get("embedding") or []
            if not isinstance(emb, list):
                continue
            score = cosine_similarity(query_embedding, emb)
            if score <= 0:
                continue
            scored.append(
                {
                    "vectorId": vid,
                    "chunkId": int(meta["chunkId"]),
                    "documentId": int(meta.get("documentId") or 0),
                    "category": meta.get("category") or "",
                    "score": round(float(score), 4),
                }
            )
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[: max(1, top_k)]


@lru_cache
def get_vector_store() -> LocalVectorStore:
    root = Path(settings.KB_VECTOR_DIR or "data/kb_vectors")
    return LocalVectorStore(root / "index.json")
