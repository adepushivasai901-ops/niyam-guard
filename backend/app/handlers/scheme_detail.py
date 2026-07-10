"""
Scheme detail handler.

For broad questions like "tell me about the scholarship" or "give me full
details of the income certificate", a citizen wants everything at once -
not just the description. This handler aggregates eligibility rules,
documents, process steps, and version/circular info into a single
structured payload, still 100% pulled from the database (no generation).
"""
from typing import Dict, Any
from sqlalchemy.orm import Session

from .. import models
from .eligibility import get_current_version
from . import documents as documents_handler
from . import process as process_handler
from . import comparison as comparison_handler


def get_full_details(db: Session, scheme_slug: str) -> Dict[str, Any] | None:
    version = get_current_version(db, scheme_slug)
    if not version:
        return None

    eligibility_rules = [
        {"field": r.field_name, "operator": r.operator, "value": r.value, "explanation": r.explanation}
        for r in version.eligibility_rules
    ]

    return {
        "scheme_name": version.scheme.name,
        "category": version.scheme.category,
        "description": version.scheme.short_description,
        "department": version.scheme.department.name if version.scheme.department else None,
        "governing_circular": version.circular.doc_number,
        "circular_title": version.circular.title,
        "effective_date": version.circular.effective_date.strftime("%d-%b-%Y"),
        "key_figures": {
            "validity_period_months": version.validity_period_months,
            "income_limit_annual": version.income_limit_annual,
            "age_min": version.age_min,
            "age_max": version.age_max,
            "benefit_amount": version.benefit_amount,
            "processing_time_days": version.processing_time_days,
        },
        "eligibility_rules": eligibility_rules,
        "documents": documents_handler.get_documents(db, scheme_slug),
        "process": process_handler.get_process(db, scheme_slug),
        "recent_change": comparison_handler.compare_with_previous(db, scheme_slug),
    }