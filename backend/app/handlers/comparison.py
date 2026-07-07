"""
Version comparison handler.

Compares a scheme's CURRENT SchemeVersion against its immediate
previous_version_id, field by field. Because both versions are structured
rows (not prose), this is a deterministic diff - the LLM downstream is only
ever asked to phrase an already-computed diff into a sentence, never to
spot the difference itself.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session

from .. import models
from ..schemas import FieldChange
from .eligibility import get_current_version

FIELD_LABELS = {
    "validity_period_months": "Validity period (months)",
    "income_limit_annual": "Annual income limit",
    "age_min": "Minimum age",
    "age_max": "Maximum age",
    "benefit_amount": "Benefit amount",
    "processing_time_days": "Processing time (days)",
}


def compare_with_previous(db: Session, scheme_slug: str) -> Dict[str, Any] | None:
    current = get_current_version(db, scheme_slug)
    if not current:
        return None
    if not current.previous_version_id:
        return {
            "scheme_name": current.scheme.name,
            "has_previous_version": False,
            "message": f"'{current.scheme.name}' has no earlier version on record - "
                       f"the version in force under {current.circular.doc_number} is the first recorded rule.",
        }

    old = db.query(models.SchemeVersion).get(current.previous_version_id)

    changes = []
    for field in models.SchemeVersion.COMPARABLE_FIELDS:
        old_val, new_val = getattr(old, field), getattr(current, field)
        if old_val != new_val:
            changes.append(FieldChange(field=FIELD_LABELS.get(field, field), old_value=old_val, new_value=new_val))

    old_doc_names = {d.name for d in old.documents}
    new_doc_names = {d.name for d in current.documents}
    doc_changes = {
        "added": sorted(new_doc_names - old_doc_names),
        "removed": sorted(old_doc_names - new_doc_names),
    }

    return {
        "scheme_name": current.scheme.name,
        "has_previous_version": True,
        "old_circular": old.circular.doc_number,
        "new_circular": current.circular.doc_number,
        "old_effective_date": old.circular.effective_date.strftime("%d-%b-%Y"),
        "new_effective_date": current.circular.effective_date.strftime("%d-%b-%Y"),
        "changes": [c.dict() for c in changes],
        "document_changes": doc_changes,
    }
