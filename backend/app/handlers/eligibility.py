"""
Eligibility handler.

This is a deterministic rules engine. Given a user profile (age, income,
category, occupation, district, etc.) and a scheme's CURRENT version, it
evaluates every stored EligibilityRule and returns which were met and which
were not - with the human-readable explanation that was captured at
ingestion time. The LLM downstream only phrases this into a sentence; it
never decides eligibility itself.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session

from .. import models
from ..schemas import EligibilityResult

OPERATORS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    # user_value is a LIST (e.g. citizen_categories); rule.value is a single
    # tag that must appear in it - e.g. field="citizen_categories",
    # operator="contains", value="ex_serviceman".
    "contains": lambda a, b: isinstance(a, (list, tuple, set)) and b in a,
}


def get_current_version(db: Session, scheme_slug: str) -> models.SchemeVersion | None:
    scheme = db.query(models.Scheme).filter(models.Scheme.slug == scheme_slug).first()
    if not scheme:
        return None
    for v in scheme.versions:
        if v.is_current:
            return v
    return None


def evaluate_rule(rule: models.EligibilityRule, profile: Dict[str, Any]) -> tuple[bool, str]:
    """Returns (passed, explanation). For failed numeric rules, the explanation
    is enriched with the exact gap (e.g. 'exceeds the limit by Rs. 15,000') so
    the citizen knows precisely what would need to change - not just that
    something failed."""
    user_value = profile.get(rule.field_name)
    op_fn = OPERATORS.get(rule.operator)
    if op_fn is None:
        return False, rule.explanation  # unknown operator - fail safe

    try:
        passed = bool(op_fn(user_value, rule.value))
    except TypeError:
        return False, rule.explanation + " (value not provided)"

    if passed:
        return True, rule.explanation

    # Build a precise gap description for numeric comparisons.
    explanation = rule.explanation
    if user_value is not None and isinstance(rule.value, (int, float)) and isinstance(user_value, (int, float)):
        if rule.operator in ("<=", "<"):
            gap = user_value - rule.value
            if gap > 0:
                explanation += f" - your provided value ({user_value:,.0f}) exceeds this by {gap:,.0f}"
        elif rule.operator in (">=", ">"):
            gap = rule.value - user_value
            if gap > 0:
                explanation += f" - your provided value ({user_value:,.0f}) is short of this by {gap:,.0f}"
    elif rule.operator == "in" and user_value is not None:
        explanation += f" - your provided value was '{user_value}', which is not in the allowed list"
    elif rule.operator == "contains":
        explanation += " - this scheme requires belonging to a specific citizen category that wasn't indicated"
    elif user_value is None:
        explanation += " - this could not be verified because the value was not provided"

    return False, explanation


def check_eligibility(db: Session, scheme_slug: str, profile: Dict[str, Any]) -> EligibilityResult | None:
    version = get_current_version(db, scheme_slug)
    if not version:
        return None

    reasons_met, reasons_failed = [], []
    for rule in version.eligibility_rules:
        passed, explanation = evaluate_rule(rule, profile)
        if passed:
            reasons_met.append(explanation)
        else:
            reasons_failed.append(explanation)

    return EligibilityResult(
        scheme_name=version.scheme.name,
        version_id=version.id,
        eligible=(len(reasons_failed) == 0),
        reasons_met=reasons_met,
        reasons_failed=reasons_failed,
    )