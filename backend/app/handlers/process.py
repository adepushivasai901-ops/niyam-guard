"""
Process handler.

Returns the stored, ordered ProcessStep rows for a scheme's current version,
each annotated with the documents required at that specific step. This is
retrieval, not generation - the sequence was captured once at ingestion time
and reused every time it's asked for, so the steps never drift or vary
between two citizens asking the same question.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session

from .. import models
from .eligibility import get_current_version


def get_process(db: Session, scheme_slug: str) -> Dict[str, Any] | None:
    version = get_current_version(db, scheme_slug)
    if not version:
        return None

    doc_lookup = {d.id: d.name for d in version.documents}

    steps = []
    for step in version.steps:
        doc_ids = step.required_document_ids or []
        steps.append({
            "step_number": step.step_number,
            "title": step.title,
            "description": step.description,
            "required_documents": [doc_lookup.get(did, "Unknown document") for did in doc_ids],
            "is_start": step.is_start,
            "is_end": step.is_end,
        })

    return {
        "scheme_name": version.scheme.name,
        "circular": version.circular.doc_number,
        "steps": steps,
    }
