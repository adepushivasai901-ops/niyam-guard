"""
Orchestrator: the glue between "what did the user ask" and "which
deterministic handler answers it".

UPDATED: Contains an AI Semantic Gatekeeper to prevent context leakage,
now with aggressive history-wiping on explicit topic shifts.
"""
import re
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from .. import models
from ..handlers import (
    eligibility, documents, process, comparison, scheme_compare,
    circulars, scheme_detail, scheme_finder,
)
from . import llm_service, profile_extraction

FULL_DETAIL_PATTERNS = re.compile(
    r"\b(everything|full detail|full details|all detail|all details|complete detail|complete information|"
    r"tell me about|give me details|full information|entire information)\b",
    re.I,
)

GREETING_PATTERNS = re.compile(
    r"^\s*(hi|hello|hey|namaste|good morning|good afternoon|good evening|thanks|thank you|bye|goodbye)\b\s*[!.,]*\s*$",
    re.I,
)

GREETING_REPLY = (
    "Namaste. I am the NiyamGuard AI citizen assistant. I can share circulars, check scheme "
    "eligibility, list required documents, explain application processes, and compare schemes - "
    "all from verified government records. How may I help you today?"
)

RECOMMEND_PATTERNS = re.compile(
    r"\b(recommend|which schemes?|what schemes?|suggest a scheme|find (a )?scheme|"
    r"what am i eligible for|am i eligible for any|qualify)\b",
    re.I,
)

SELF_DESCRIPTION_PATTERNS = re.compile(
    r"\bi\s?(a|')?m\s+(a|an)\b|\bi am\s+(a|an)\b",
    re.I,
)

EXPLAIN_PATTERNS = re.compile(
    r"\b(explain|simple terms|plain language|what does (it|this) mean|simplify|in simple words|"
    r"legal language|layman)\b",
    re.I,
)

GUIDE_START_PATTERNS = re.compile(
    r"\b(guide me|walk me through|step by step|help me apply|take me through)\b",
    re.I,
)

GUIDE_NEXT_PATTERNS = re.compile(
    r"^\s*(next|next step|continue|go on|what'?s next|then what|ok next|okay next)\s*[!.,]*\s*$",
    re.I,
)


def _is_context_dependent(message: str, last_slug: str) -> bool:
    """
    Semantic Intent Gatekeeper:
    Prevents context contamination by asking the LLM if the new message 
    is a continuation of the previous topic, or a completely new topic.
    """
    prompt = f"""You are a routing assistant. 
Previous topic discussed: '{last_slug}'
New User Message: "{message}"

Does the new message directly refer to, or act as a follow-up to the previous topic?
If the new message explicitly names a different scheme, asks about a completely different topic, or is a standalone question, answer "INDEPENDENT".
If it relies on the previous topic to make sense (e.g. "what are the documents?", "am I eligible?", "how do I apply"), answer "DEPENDENT".

Respond with exactly one word: DEPENDENT or INDEPENDENT."""
    
    result = llm_service.call_raw(prompt, max_tokens=10, temperature=0.0)
    
    # If the LLM explicitly determines a context shift, or fails safely
    if result and "INDEPENDENT" in result.upper():
        return False
    return True


def _extract_scheme_slug(db: Session, message: str) -> Optional[str]:
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


def _resolve_scheme_slug(db: Session, message: str, session: Optional[models.ChatSession]) -> Optional[str]:
    # 1. Try to find explicit mention in current message
    slug = _extract_scheme_slug(db, message)
    if slug:
        if session is not None:
            session.last_scheme_slug = slug
        return slug
        
    # 2. Check if we should inherit the session context (Gatekeeper)
    if session is not None and session.last_scheme_slug:
        if _is_context_dependent(message, session.last_scheme_slug):
            return session.last_scheme_slug
        else:
            # Prevent Context Leakage by clearing the old topic
            session.last_scheme_slug = None
            
    return None


def _missing_profile_message(db: Session, slug: str) -> Dict[str, Any]:
    version = eligibility.get_current_version(db, slug)
    required_fields = sorted({r.field_name for r in version.eligibility_rules}) if version else []
    return {
        "error": "missing_profile",
        "scheme_name": version.scheme.name if version else slug,
        "required_fields": required_fields,
        "message": f"To check eligibility precisely, please provide: {', '.join(required_fields)}.",
    }


def _handle_guided_next(db: Session, session: models.ChatSession) -> Dict[str, Any]:
    slug = session.guided_scheme_slug
    step_idx = session.guided_process_step or 0
    proc = process.get_process(db, slug)
    if not proc or step_idx >= len(proc["steps"]):
        session.guided_process_step = None
        session.guided_scheme_slug = None
        return {"guided_step": None, "scheme_name": proc["scheme_name"] if proc else slug,
                "message": "That was the final step - the process is complete."}

    step = proc["steps"][step_idx]
    session.guided_process_step = step_idx + 1
    return {
        "guided_step": step,
        "scheme_name": proc["scheme_name"],
        "circular": proc["circular"],
        "total_steps": len(proc["steps"]),
        "is_last_step": (step_idx + 1) >= len(proc["steps"]),
    }


def _handle_guided_start(db: Session, session: models.ChatSession, slug: str) -> Dict[str, Any]:
    session.guided_scheme_slug = slug
    session.guided_process_step = 0
    session.last_scheme_slug = slug
    return _handle_guided_next(db, session)


def handle_message(
    db: Session,
    message: str,
    user_profile: Optional[Dict[str, Any]],
    history: list,
    session: Optional[models.ChatSession] = None,
) -> tuple[str, str, Optional[dict]]:
    """Returns (intent, reply_text, structured_data)."""
    stripped = message.strip()
    
    # Track the active topic BEFORE processing the new message
    old_slug = session.last_scheme_slug if session else None

    if GREETING_PATTERNS.match(stripped):
        return "greeting", GREETING_REPLY, None

    if session is not None and session.guided_process_step is not None and GUIDE_NEXT_PATTERNS.match(stripped):
        data = _handle_guided_next(db, session)
        reply = llm_service.format_reply(message, "guided_step", data, history)
        return "guided_step", reply, data

    if GUIDE_START_PATTERNS.search(message):
        slug = _resolve_scheme_slug(db, message, session)
        if slug and session is not None:
            data = _handle_guided_start(db, session, slug)
            
            # Wipe history if the topic was explicitly changed
            if old_slug and session.last_scheme_slug != old_slug and len(history) > 0:
                history = []
                
            reply = llm_service.format_reply(message, "guided_step", data, history)
            return "guided_step", reply, data
        return "guided_step", "Which scheme would you like me to walk you through?", None

    if RECOMMEND_PATTERNS.search(message) or SELF_DESCRIPTION_PATTERNS.search(message):
        extracted = profile_extraction.extract_profile(message)
        citizen_categories = extracted.get("citizen_categories", [])
        merged_profile = {**extracted, **{k: v for k, v in (user_profile or {}).items() if v not in (None, "", False)}}

        if not merged_profile or not any(v not in (None, "", False) for v in merged_profile.values()):
            data = {"error": "missing_profile", "required_fields": ["age", "annual_income", "category"],
                     "scheme_name": "a scheme recommendation"}
        else:
            data = scheme_finder.recommend_schemes(db, merged_profile, citizen_categories or None)
            
        if session:
            session.last_scheme_slug = None # Clear context for future questions
        if old_slug and len(history) > 0:
            history = [] # Wipe history to prevent LLM confusion
            
        reply = llm_service.format_reply(message, "recommend_schemes", data, history)
        return "recommend_schemes", reply, data

    if EXPLAIN_PATTERNS.search(message):
        slug = _resolve_scheme_slug(db, message, session)
        circular_text, circular_label = None, None
        if slug:
            version = eligibility.get_current_version(db, slug)
            if version:
                circular_text = version.circular.raw_text
                circular_label = version.circular.doc_number
        if not circular_text:
            found = circulars.find_circulars(db, message)
            if found:
                circular_text = circulars.get_circular_text(db, found[0]["id"])
                circular_label = found[0]["doc_number"]
        data = {"circular": circular_label, "circular_raw_text": circular_text} if circular_text else None
        
        if session and old_slug and session.last_scheme_slug != old_slug and len(history) > 0:
            history = []
            
        reply = llm_service.format_reply(message, "explain_legal", data, history)
        return "explain_legal", reply, data

    intent = llm_service.classify_intent(message)
    data: Optional[Dict[str, Any]] = None
    wants_full_detail = bool(FULL_DETAIL_PATTERNS.search(message))

    if intent == "fetch_document":
        slug = _resolve_scheme_slug(db, message, session)
        if slug:
            scheme = db.query(models.Scheme).filter(models.Scheme.slug == slug).first()
            data = circulars.find_circulars(db, scheme.name)
        else:
            query = re.sub(
                r"\b(show|give|fetch|find|me|the|a|an|please|circular|document|go|about|for)\b",
                "", message, flags=re.I
            )
            query = re.sub(r"\s+", " ", query).strip()
            data = circulars.find_circulars(db, query or message)

    elif intent == "check_eligibility":
        slug = _resolve_scheme_slug(db, message, session)
        extracted = profile_extraction.extract_profile(message)
        merged_profile = {**extracted, **{k: v for k, v in (user_profile or {}).items() if v not in (None, "", False)}}
        if not slug:
            data = None
        elif not merged_profile or not any(v not in (None, "", False) for v in merged_profile.values()):
            data = _missing_profile_message(db, slug)
        else:
            result = eligibility.check_eligibility(db, slug, merged_profile)
            data = result.dict() if result else None

    elif intent == "list_documents":
        slug = _resolve_scheme_slug(db, message, session)
        data = documents.get_documents(db, slug) if slug else None

    elif intent == "get_process":
        slug = _resolve_scheme_slug(db, message, session)
        data = process.get_process(db, slug) if slug else None

    elif intent == "compare_versions":
        slug = _resolve_scheme_slug(db, message, session)
        data = comparison.compare_with_previous(db, slug) if slug else None

    elif intent == "compare_schemes":
        slugs = _extract_all_scheme_slugs(db, message)
        if len(slugs) >= 2:
            data = scheme_compare.compare_schemes(db, slugs, user_profile)
        else:
            data = None
        # Comparing clears the primary active topic
        if session:
            session.last_scheme_slug = None

    else:  # general_query
        slug = _resolve_scheme_slug(db, message, session)
        if slug:
            data = scheme_detail.get_full_details(db, slug)

    if wants_full_detail:
        slug = _resolve_scheme_slug(db, message, session)
        if slug:
            full = scheme_detail.get_full_details(db, slug)
            if full:
                data = full

    # FINAL CHECK: Filter history strictly if we switched topics. 
    # (Either the gatekeeper wiped it, or the user explicitly mentioned a NEW scheme)
    if session and len(history) > 0:
        new_slug = session.last_scheme_slug
        if old_slug and new_slug != old_slug:
            # We switched from one topic to a different one. Clear history so the LLM doesn't get confused!
            history = [] 

    reply = llm_service.format_reply(message, intent, data, history)
    return intent, reply, data