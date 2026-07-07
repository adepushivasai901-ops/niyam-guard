"""
Orchestrator: the glue between "what did the user ask" and "which deterministic
handler answers it". This is deliberately simple and explicit rather than
letting an LLM freeform decide what data to fetch - predictability matters
more than cleverness in a compliance tool.
"""
import re
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from .. import models
from ..handlers import eligibility, documents, process, comparison, scheme_compare, circulars
from . import llm_service


def _extract_scheme_slug(db: Session, message: str) -> Optional[str]:
    """Best-effort match of a scheme mentioned in free text against known schemes.
    Exact/substring match on scheme name; extend with fuzzy matching if needed."""
    message_l = message.lower()
    schemes = db.query(models.Scheme).all()
    best = None
    for s in schemes:
        if s.name.lower() in message_l or s.slug.replace("-", " ") in message_l:
            if best is None or len(s.name) > len(best.name):
                best = s
    return best.slug if best else None


def _extract_all_scheme_slugs(db: Session, message: str) -> list[str]:
    message_l = message.lower()
    schemes = db.query(models.Scheme).all()
    return [s.slug for s in schemes if s.name.lower() in message_l or s.slug.replace("-", " ") in message_l]


def handle_message(db: Session, message: str, user_profile: Optional[Dict[str, Any]], history: list) -> tuple[str, str, Optional[dict]]:
    """Returns (intent, reply_text, structured_data)."""
    intent = llm_service.classify_intent(message)

    data: Optional[Dict[str, Any]] = None

    if intent == "fetch_document":
        # Prefer matching a known scheme name first (reliable), then fall
        # back to a stripped free-text search over circular title/number.
        slug = _extract_scheme_slug(db, message)
        if slug:
            scheme = db.query(models.Scheme).filter(models.Scheme.slug == slug).first()
            data = circulars.find_circulars(db, scheme.name)
        else:
            # \b...\b word boundaries are essential here - without them, a word
            # like "show" would also strip the "me" inside "income", corrupting
            # the query into something that matches nothing.
            query = re.sub(
                r"\b(show|give|fetch|find|me|the|a|an|please|circular|document|go|about|for)\b",
                "", message, flags=re.I
            )
            query = re.sub(r"\s+", " ", query).strip()
            data = circulars.find_circulars(db, query or message)

    elif intent == "check_eligibility":
        slug = _extract_scheme_slug(db, message)
        if not slug:
            data = None
        elif not user_profile:
            data = {"error": "missing_profile", "message": "need age/income/category to evaluate eligibility"}
        else:
            result = eligibility.check_eligibility(db, slug, user_profile)
            data = result.dict() if result else None

    elif intent == "list_documents":
        slug = _extract_scheme_slug(db, message)
        data = documents.get_documents(db, slug) if slug else None

    elif intent == "get_process":
        slug = _extract_scheme_slug(db, message)
        data = process.get_process(db, slug) if slug else None

    elif intent == "compare_versions":
        slug = _extract_scheme_slug(db, message)
        data = comparison.compare_with_previous(db, slug) if slug else None

    elif intent == "compare_schemes":
        slugs = _extract_all_scheme_slugs(db, message)
        if len(slugs) >= 2:
            data = scheme_compare.compare_schemes(db, slugs, user_profile)
        else:
            data = None

    else:  # general_query
        slug = _extract_scheme_slug(db, message)
        if slug:
            version = eligibility.get_current_version(db, slug)
            if version:
                data = {
                    "scheme_name": version.scheme.name,
                    "description": version.scheme.short_description,
                    "circular": version.circular.doc_number,
                    "effective_date": version.circular.effective_date.strftime("%d-%b-%Y"),
                }

    reply = llm_service.format_reply(message, intent, data, history)
    return intent, reply, data