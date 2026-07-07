"""
Scheme comparison handler.

Builds a structured comparison table across multiple schemes (current
versions), optionally alongside the user's eligibility for each. This table
is what gets passed to the LLM to justify "why scheme A is better than
scheme B for this citizen" - the LLM is grounded in real numbers and cannot
invent figures, because every number in the table came from the database.
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from .eligibility import get_current_version, check_eligibility


def compare_schemes(db: Session, scheme_slugs: List[str], user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    table = []
    for slug in scheme_slugs:
        version = get_current_version(db, slug)
        if not version:
            table.append({"slug": slug, "error": "Scheme not found"})
            continue

        row = {
            "scheme_name": version.scheme.name,
            "circular": version.circular.doc_number,
            "income_limit_annual": version.income_limit_annual,
            "age_min": version.age_min,
            "age_max": version.age_max,
            "benefit_amount": version.benefit_amount,
            "processing_time_days": version.processing_time_days,
            "mandatory_document_count": len([d for d in version.documents if d.mandatory]),
        }

        if user_profile:
            elig = check_eligibility(db, slug, user_profile)
            if elig:
                row["eligible_for_user"] = elig.eligible
                row["reasons_failed"] = elig.reasons_failed

        table.append(row)

    return {"table": table}
