"""
Documents handler.

Pure lookup against stored Document rows for a scheme's current version.
Splits into mandatory vs secondary (supporting) documents and reports the
number of copies required for each - straight from structured data, never
generated on the fly.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session

from .. import models
from .eligibility import get_current_version


def get_documents(db: Session, scheme_slug: str) -> Dict[str, Any] | None:
    version = get_current_version(db, scheme_slug)
    if not version:
        return None

    mandatory = [d for d in version.documents if d.mandatory]
    secondary = [d for d in version.documents if not d.mandatory]

    def _fmt(d: models.Document):
        return {
            "name": d.name,
            "copies_required": d.copies_required,
            "notes": d.notes,
        }

    return {
        "scheme_name": version.scheme.name,
        "circular": version.circular.doc_number,
        "mandatory_documents": [_fmt(d) for d in mandatory],
        "secondary_documents": [_fmt(d) for d in secondary],
    }
