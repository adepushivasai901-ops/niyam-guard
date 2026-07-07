"""
LLM service.

IMPORTANT: the LLM is used for two things only, both "downstream" of the
structured facts:
  1. Classifying which handler a user message maps to (intent classification).
  2. Turning already-computed structured data into a professional,
     government-officer-style natural language reply.

It is NEVER asked to invent eligibility rules, document lists, process
steps, or numbers - those always come from Postgres/SQLite via the handlers.
This keeps answers consistent and auditable, which matters a lot for a
government compliance tool.

If no ANTHROPIC_API_KEY is set, everything degrades gracefully to simple
keyword-matching + template formatting, so the project still runs end to end
for a demo without any key configured.
"""
import json
from typing import Optional
from .. import config

_client = None
if config.LLM_ENABLED:
    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except Exception as e:
        # Never let an LLM client setup problem (bad key, version mismatch,
        # missing package, etc.) prevent the whole server from starting.
        # The app falls back to keyword classification + template replies.
        print(f"[niyamguard] LLM client unavailable, falling back to templates: {e}")
        _client = None


SYSTEM_PROMPT = """You are NiyamGuard AI, an official government policy compliance and citizen assistance
assistant. You speak the way a well-trained, professional government employee would:
clear, precise, respectful, and neutral - never casual, never speculative.

STRICT RULES:
- You may ONLY use facts given to you in the "STRUCTURED DATA" block below. Never invent
  eligibility criteria, documents, numbers, dates, or steps that are not present in it.
- If the structured data says a scheme/document/circular was not found, say so plainly and
  do not guess an answer.
- Always cite the circular/GO number when referencing a rule, if one is present in the data.
- When asked to compare old vs new rules, clearly separate "Earlier position" and
  "Current position", referencing the circular numbers and effective dates.
- When asked about eligibility, always explain WHY (or why not) using the reasons_met /
  reasons_failed provided - do not restate them mechanically, but do not omit any reason either.
- When listing documents, separate Mandatory and Secondary/Supporting clearly, and state the
  number of copies required for each.
- Keep tone formal and helpful, similar to how a knowledgeable government helpdesk officer
  would explain a rule to a citizen.
"""


def classify_intent(message: str) -> str:
    """Classify a user message into one of the supported intents.
    Falls back to keyword heuristics if no LLM is configured."""
    intents = [
        "fetch_document", "compare_versions", "check_eligibility",
        "list_documents", "get_process", "compare_schemes", "general_query",
    ]

    if _client is None:
        return _keyword_fallback_intent(message)

    prompt = f"""Classify the user's message into exactly ONE of these intents:
- fetch_document: user wants to see/read a circular, GO, or document itself
- compare_versions: user wants to know what changed between the old and new rule/circular
- check_eligibility: user wants to know if they/someone qualifies for a scheme
- list_documents: user wants to know what documents/papers are required
- get_process: user wants step-by-step application process
- compare_schemes: user wants to compare two or more schemes against each other
- general_query: anything else (general info about a scheme, greetings, etc.)

Respond with ONLY the intent string, nothing else.

User message: "{message}" """

    try:
        resp = _client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip().lower()
        for intent in intents:
            if intent in text:
                return intent
    except Exception:
        pass

    return _keyword_fallback_intent(message)


def _keyword_fallback_intent(message: str) -> str:
    m = message.lower()
    if any(k in m for k in ["circular", "go no", "government order", "notification", "show me the document", "give me the document"]):
        return "fetch_document"
    if any(k in m for k in ["old vs new", "old and new", "changed", "compare the circular", "what changed", "difference between old"]):
        return "compare_versions"
    if any(k in m for k in ["eligible", "eligibility", "qualify", "am i eligible", "can i apply"]):
        return "check_eligibility"
    if any(k in m for k in ["document", "documents", "papers required", "copies"]):
        return "list_documents"
    if any(k in m for k in ["process", "procedure", "steps", "how do i apply", "how to apply"]):
        return "get_process"
    if any(k in m for k in ["compare", "better", "which scheme", "vs "]):
        return "compare_schemes"
    return "general_query"


def format_reply(user_message: str, intent: str, structured_data: Optional[dict], history: Optional[list] = None) -> str:
    """Turn structured handler output into a professional natural-language reply."""
    if _client is None:
        return _template_fallback_reply(intent, structured_data)

    history = history or []
    history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])

    prompt = f"""Conversation so far:
{history_text}

Current user message: "{user_message}"
Classified intent: {intent}

STRUCTURED DATA (this is the ONLY source of facts you may use):
{json.dumps(structured_data, indent=2, default=str) if structured_data is not None else "null - nothing was found in the knowledge base for this request."}

Write the assistant's reply now, following all rules in your system prompt."""

    try:
        resp = _client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        return _template_fallback_reply(intent, structured_data) + f"\n\n(Note: LLM formatting unavailable - {e})"


# ---------------------------------------------------------------------------
# Template fallback formatter - used if no API key is set. Keeps the project
# fully runnable/demoable with zero external dependencies.
# ---------------------------------------------------------------------------
def _template_fallback_reply(intent: str, data: Optional[dict]) -> str:
    if data is None:
        return "I could not find verified information on this in the knowledge base. Could you rephrase or specify the scheme/circular name?"

    if intent == "fetch_document":
        if isinstance(data, list):
            if not data:
                return "No matching circulars were found in the verified knowledge base."
            lines = [f"- {c['doc_number']}: {c['title']} (effective {c['effective_date']})" for c in data]
            return "I found the following circular(s):\n" + "\n".join(lines)

    if intent == "check_eligibility":
        status = "ELIGIBLE" if data.get("eligible") else "NOT ELIGIBLE"
        lines = [f"Scheme: {data.get('scheme_name')}", f"Status: {status}"]
        if data.get("reasons_met"):
            lines.append("Criteria met: " + "; ".join(data["reasons_met"]))
        if data.get("reasons_failed"):
            lines.append("Criteria not met: " + "; ".join(data["reasons_failed"]))
        return "\n".join(lines)

    if intent == "list_documents":
        lines = [f"Documents for {data.get('scheme_name')} (as per {data.get('circular')}):", "", "Mandatory:"]
        for d in data.get("mandatory_documents", []):
            lines.append(f"  - {d['name']} ({d['copies_required']} copy/copies)" + (f" - {d['notes']}" if d.get("notes") else ""))
        lines.append("Secondary/Supporting:")
        for d in data.get("secondary_documents", []):
            lines.append(f"  - {d['name']} ({d['copies_required']} copy/copies)" + (f" - {d['notes']}" if d.get("notes") else ""))
        return "\n".join(lines)

    if intent == "get_process":
        lines = [f"Process for {data.get('scheme_name')} (as per {data.get('circular')}):"]
        for s in data.get("steps", []):
            lines.append(f"Step {s['step_number']}: {s['title']} - {s['description']}")
            if s["required_documents"]:
                lines.append(f"    Documents needed: {', '.join(s['required_documents'])}")
        return "\n".join(lines)

    if intent == "compare_versions":
        if not data.get("has_previous_version"):
            return data.get("message", "No previous version found.")
        lines = [
            f"{data['scheme_name']}: comparing {data['old_circular']} (effective {data['old_effective_date']}) "
            f"vs {data['new_circular']} (effective {data['new_effective_date']})",
        ]
        for c in data.get("changes", []):
            lines.append(f"  - {c['field']}: was {c['old_value']}, now {c['new_value']}")
        dc = data.get("document_changes", {})
        if dc.get("added"):
            lines.append(f"  - New documents required: {', '.join(dc['added'])}")
        if dc.get("removed"):
            lines.append(f"  - Documents no longer required: {', '.join(dc['removed'])}")
        return "\n".join(lines)

    if intent == "compare_schemes":
        lines = ["Scheme comparison:"]
        for row in data.get("table", []):
            lines.append(json.dumps(row, default=str))
        return "\n".join(lines)

    return json.dumps(data, default=str)