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
}


def get_current_version(db: Session, scheme_slug: str) -> models.SchemeVersion | None:
    scheme = db.query(models.Scheme).filter(models.Scheme.slug == scheme_slug).first()
    if not scheme:
        return None
    for v in scheme.versions:
        if v.is_current:
            return v
    return None


def evaluate_rule(rule: models.EligibilityRule, profile: Dict[str, Any]) -> bool:
    user_value = profile.get(rule.field_name)
    op_fn = OPERATORS.get(rule.operator)
    if op_fn is None:
        # Unknown operator - fail safe rather than silently assume eligible.
        return False
    try:
        return bool(op_fn(user_value, rule.value))
    except TypeError:
        return False


def check_eligibility(db: Session, scheme_slug: str, profile: Dict[str, Any]) -> EligibilityResult | None:
    version = get_current_version(db, scheme_slug)
    if not version:
        return None

    reasons_met, reasons_failed = [], []
    for rule in version.eligibility_rules:
        if evaluate_rule(rule, profile):
            reasons_met.append(rule.explanation)
        else:
            reasons_failed.append(rule.explanation)

    return EligibilityResult(
        scheme_name=version.scheme.name,
        version_id=version.id,
        eligible=(len(reasons_failed) == 0),
        reasons_met=reasons_met,
        reasons_failed=reasons_failed,
    )
