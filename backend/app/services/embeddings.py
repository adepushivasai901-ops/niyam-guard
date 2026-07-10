"""
Embedding-based semantic search over circular full text (RAG retrieval layer).

Uses Gemini's embedding model to convert each circular's raw text into a
vector at ingestion time, stored directly on the Circular row (JSON-encoded
list of floats - fine at this small demo scale; swap for a real vector DB
like Chroma/pgvector if the corpus grows into the thousands).

This is what lets a citizen ask something in their own words ("what does
the rule say about verification steps") and get matched to the right
circular by MEANING, not exact keyword overlap - unlike the plain ILIKE
search in handlers/circulars.py.

Falls back cleanly: if no GOOGLE_API_KEY is configured, or an embedding
call fails, semantic_search() simply returns [], and callers (tools.py)
fall back to the exact-match keyword search instead.
"""
import json
import math
from typing import List, Optional
from sqlalchemy.orm import Session

from .. import config, models

EMBEDDING_MODEL = "models/text-embedding-004"

_genai = None
if config.LLM_ENABLED:
    try:
        import google.generativeai as genai
        _genai = genai
    except Exception:
        _genai = None


def embed_text(text: str, task_type: str = "retrieval_document") -> Optional[List[float]]:
    if _genai is None or not text:
        return None
    try:
        result = _genai.embed_content(model=EMBEDDING_MODEL, content=text, task_type=task_type)
        return result["embedding"]
    except Exception as e:
        print(f"[niyamguard] embedding failed: {e}")
        return None


def store_embedding(db: Session, circular: models.Circular) -> None:
    """Compute and persist an embedding for a circular's raw_text. Safe to
    call repeatedly (e.g. during seeding) - silently does nothing if
    embeddings are unavailable, so seeding never breaks over this."""
    if not circular.raw_text:
        return
    vec = embed_text(circular.raw_text, task_type="retrieval_document")
    if vec is not None:
        circular.embedding = json.dumps(vec)
        db.add(circular)
        db.commit()


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def semantic_search(db: Session, query: str, top_k: int = 3, min_score: float = 0.55) -> List[dict]:
    """Semantic search over circular raw_text. Returns [] if embeddings are
    unavailable or nothing scores above the threshold - caller should treat
    an empty result as 'fall back to keyword search', not 'nothing exists'."""
    if _genai is None:
        return []

    query_vec = embed_text(query, task_type="retrieval_query")
    if query_vec is None:
        return []

    circulars = db.query(models.Circular).filter(models.Circular.embedding.isnot(None)).all()
    scored = []
    for c in circulars:
        try:
            c_vec = json.loads(c.embedding)
        except Exception:
            continue
        score = _cosine(query_vec, c_vec)
        if score >= min_score:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, c in scored[:top_k]:
        results.append({
            "circular_id": c.id,
            "doc_number": c.doc_number,
            "title": c.title,
            "effective_date": c.effective_date.strftime("%d-%b-%Y"),
            "relevance_score": round(score, 3),
            "excerpt": c.raw_text[:600],
        })
    return results