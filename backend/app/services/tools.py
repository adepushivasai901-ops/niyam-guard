"""
Tool (function) declarations for the LLM router, and the dispatcher that
executes them against the deterministic handlers.

This is the 'function calling' pillar: the LLM only ever chooses WHICH of
these functions to call and WITH WHAT ARGUMENTS - it never generates the
underlying facts itself. Every function here is backed by the exact same
deterministic handlers used throughout this project (eligibility.py,
documents.py, etc.) - nothing about the trust model changes, only how the
LLM is allowed to reach it.
"""
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from ..handlers import eligibility, documents, process, comparison, scheme_compare, circulars, scheme_detail
from . import embeddings

try:
    from google.generativeai.types import FunctionDeclaration, Tool
except Exception:
    FunctionDeclaration = None
    Tool = None


def build_tools(valid_slugs: List[str]):
    """Builds the Gemini Tool object. valid_slugs is injected into each
    parameter description so the model is steered toward real scheme slugs
    instead of guessing/inventing one."""
    if FunctionDeclaration is None:
        return None

    slug_hint = f"Must be one of: {', '.join(valid_slugs)}" if valid_slugs else "a known scheme slug"

    declarations = [
        FunctionDeclaration(
            name="check_eligibility",
            description="Check whether the citizen (using their already-known profile) is eligible for a specific scheme, with reasons.",
            parameters={"type": "object", "properties": {
                "scheme_slug": {"type": "string", "description": slug_hint},
            }, "required": ["scheme_slug"]},
        ),
        FunctionDeclaration(
            name="list_documents",
            description="Get the mandatory and secondary documents (with copies required) for a scheme.",
            parameters={"type": "object", "properties": {
                "scheme_slug": {"type": "string", "description": slug_hint},
            }, "required": ["scheme_slug"]},
        ),
        FunctionDeclaration(
            name="get_process",
            description="Get the ordered, step-by-step application process for a scheme.",
            parameters={"type": "object", "properties": {
                "scheme_slug": {"type": "string", "description": slug_hint},
            }, "required": ["scheme_slug"]},
        ),
        FunctionDeclaration(
            name="compare_versions",
            description="Compare a scheme's current rules against its immediately previous version - what changed, and under which circular.",
            parameters={"type": "object", "properties": {
                "scheme_slug": {"type": "string", "description": slug_hint},
            }, "required": ["scheme_slug"]},
        ),
        FunctionDeclaration(
            name="compare_schemes",
            description="Compare two or more schemes side by side (income limits, age limits, benefit amounts, eligibility for this citizen).",
            parameters={"type": "object", "properties": {
                "scheme_slugs": {"type": "array", "items": {"type": "string"}, "description": f"List of scheme slugs. {slug_hint}"},
            }, "required": ["scheme_slugs"]},
        ),
        FunctionDeclaration(
            name="get_full_details",
            description="Get everything about a scheme in one call: description, key figures, eligibility rules, documents, process, and the most recent rule change. Use this for broad 'tell me about X' questions.",
            parameters={"type": "object", "properties": {
                "scheme_slug": {"type": "string", "description": slug_hint},
            }, "required": ["scheme_slug"]},
        ),
        FunctionDeclaration(
            name="fetch_circular",
            description="Find and return specific circulars/government orders by scheme name, title keywords, or GO number.",
            parameters={"type": "object", "properties": {
                "query": {"type": "string", "description": "Scheme name, title keywords, or GO/doc number to search for."},
            }, "required": ["query"]},
        ),
        FunctionDeclaration(
            name="search_circular_content",
            description="Semantic search over the full text of all circulars, for open-ended policy questions not tied to one specific scheme field (e.g. 'what does the rule say about verification'). Use this when no other tool clearly fits.",
            parameters={"type": "object", "properties": {
                "query": {"type": "string", "description": "The citizen's question, in natural language."},
            }, "required": ["query"]},
        ),
    ]
    return Tool(function_declarations=declarations)


def dispatch(db: Session, name: str, args: Dict[str, Any], user_profile: Dict[str, Any]) -> Any:
    """Executes a tool call against the deterministic handlers. Returns
    JSON-serializable structured data, or an error dict - never raises,
    since the agent loop needs something to feed back to the model either way."""
    try:
        if name == "check_eligibility":
            slug = args.get("scheme_slug")
            if not user_profile or not any(v not in (None, "", False) for v in user_profile.values()):
                version = eligibility.get_current_version(db, slug)
                required = sorted({r.field_name for r in version.eligibility_rules}) if version else []
                return {"error": "missing_profile", "required_fields": required}
            result = eligibility.check_eligibility(db, slug, user_profile)
            return result.dict() if result else {"error": "scheme_not_found"}

        if name == "list_documents":
            result = documents.get_documents(db, args.get("scheme_slug"))
            return result or {"error": "scheme_not_found"}

        if name == "get_process":
            result = process.get_process(db, args.get("scheme_slug"))
            return result or {"error": "scheme_not_found"}

        if name == "compare_versions":
            result = comparison.compare_with_previous(db, args.get("scheme_slug"))
            return result or {"error": "scheme_not_found"}

        if name == "compare_schemes":
            slugs = list(args.get("scheme_slugs", []))
            return scheme_compare.compare_schemes(db, slugs, user_profile)

        if name == "get_full_details":
            result = scheme_detail.get_full_details(db, args.get("scheme_slug"))
            return result or {"error": "scheme_not_found"}

        if name == "fetch_circular":
            return {"results": circulars.find_circulars(db, args.get("query", ""))}

        if name == "search_circular_content":
            query = args.get("query", "")
            semantic_results = embeddings.semantic_search(db, query)
            if semantic_results:
                return {"method": "semantic", "results": semantic_results}
            # graceful fallback to keyword search if embeddings unavailable
            keyword_results = circulars.find_circulars(db, query)
            return {"method": "keyword_fallback", "results": keyword_results}

        return {"error": f"unknown_tool:{name}"}
    except Exception as e:
        return {"error": str(e)}