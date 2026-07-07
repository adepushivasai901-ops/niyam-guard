"""
Circular retrieval handler.

Handles requests like "show me the circular about income certificates" or
"give me GO Ms No. 45". Does simple keyword search over doc_number / title
/ scheme name first (fast, exact); falls back to a semantic search over
raw_text if you wire in a vector DB (see services/llm_service.py notes).
"""
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .. import models


def find_circulars(db: Session, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    like = f"%{query}%"
    results = (
        db.query(models.Circular)
        .filter(or_(models.Circular.doc_number.ilike(like), models.Circular.title.ilike(like)))
        .limit(limit)
        .all()
    )

    # Fallback: search by related scheme name if nothing matched directly.
    if not results:
        schemes = db.query(models.Scheme).filter(models.Scheme.name.ilike(like)).all()
        circular_ids = set()
        for s in schemes:
            for v in s.versions:
                circular_ids.add(v.circular_id)
        if circular_ids:
            results = db.query(models.Circular).filter(models.Circular.id.in_(circular_ids)).all()

    return [
        {
            "id": c.id,
            "doc_number": c.doc_number,
            "title": c.title,
            "issued_date": c.issued_date.strftime("%d-%b-%Y"),
            "effective_date": c.effective_date.strftime("%d-%b-%Y"),
            "file_path": c.file_path,
            "needs_human_review": c.needs_human_review,
        }
        for c in results
    ]


def get_circular_text(db: Session, circular_id: int) -> str | None:
    c = db.query(models.Circular).get(circular_id)
    return c.raw_text if c else None
