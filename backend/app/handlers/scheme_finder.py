"""
Scheme Finder handler - the citizen-centric recommendation engine.

Implements: Retrieve Candidate Schemes -> Evaluate Eligibility -> Rank.
("Extract Profile" and "Identify Category" happen upstream, in
services/profile_extraction.py, before this is called.)

If citizen_categories is provided (from profile extraction), candidate
schemes are narrowed to ones tagged with an overlapping category FIRST -
this is what stops "I am an ex-serviceman" from being checked against
every scheme in the database, including totally irrelevant ones. If no
categories were extracted (or none match), it falls back to checking every
scheme with defined eligibility rules, same as before.

Still 100% deterministic in the actual eligibility decision - narrowing
candidates is the only place category tags are used; check_eligibility()
itself is untouched.
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from .. import models
from . import eligibility


def recommend_schemes(
    db: Session,
    user_profile: Dict[str, Any],
    citizen_categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    all_schemes = db.query(models.Scheme).all()

    if citizen_categories:
        candidates = [
            s for s in all_schemes
            if s.target_categories and set(s.target_categories) & set(citizen_categories)
        ]
        # If tagging didn't match anything (e.g. a category with no schemes
        # yet), fall back to the full list rather than returning nothing.
        if not candidates:
            candidates = all_schemes
    else:
        candidates = all_schemes

    eligible, not_eligible = [], []

    for s in candidates:
        version = eligibility.get_current_version(db, s.slug)
        if not version or not version.eligibility_rules:
            continue  # skip schemes with no defined eligibility rules (e.g. Income Certificate - not a benefit scheme)

        result = eligibility.check_eligibility(db, s.slug, user_profile)
        if not result:
            continue

        entry = {
            "scheme_name": result.scheme_name,
            "scheme_slug": s.slug,
            "benefit_amount": version.benefit_amount,
            "target_categories": s.target_categories,
        }
        if result.eligible:
            entry["reasons_met"] = result.reasons_met
            eligible.append(entry)
        else:
            entry["reasons_failed"] = result.reasons_failed
            not_eligible.append(entry)

    # Rank: highest benefit amount first (None sorts last).
    eligible.sort(key=lambda e: (e["benefit_amount"] is None, -(e["benefit_amount"] or 0)))

    return {
        "matched_categories": citizen_categories or [],
        "eligible_schemes": eligible,
        "not_eligible_schemes": not_eligible,
    }