"""本地向量库与 hash embedding 单测。"""

from __future__ import annotations

from pathlib import Path

from app.services.vector_store import LocalVectorStore, cosine_similarity, embed_text


def test_embed_text_deterministic_and_normalized():
    a = embed_text("擎天学智成立于2018年")
    b = embed_text("擎天学智成立于2018年")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_local_vector_store_search(tmp_path: Path):
    store = LocalVectorStore(tmp_path / "index.json")
    store.upsert(
        vector_id="c1",
        embedding=embed_text("集团成立于2018年，专注K12"),
        chunk_id=1,
        document_id=10,
        category="group_overview",
    )
    store.upsert(
        vector_id="c2",
        embedding=embed_text("初二数学暑假班价格六千八百"),
        chunk_id=2,
        document_id=11,
        category="course_plan",
    )
    hits = store.search(embed_text("成立多少年了"), top_k=2)
    assert hits
    assert hits[0]["chunkId"] == 1
    assert hits[0]["score"] > 0

    filtered = store.search(
        embed_text("暑假班价格"), top_k=2, category="course_plan"
    )
    assert filtered
    assert filtered[0]["chunkId"] == 2


def test_cosine_similarity_bounds():
    v = embed_text("hello world")
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6
    assert cosine_similarity(v, [0.0] * len(v)) == 0.0
