"""
LLM service (local Ollama).

IMPORTANT: the LLM is used for two things only, both "downstream" of the
structured facts:
  1. Classifying which handler a user message maps to (intent classification).
  2. Turning already-computed structured data into a professional,
     government-officer-style natural language reply.

It is NEVER asked to invent eligibility rules, document lists, process
steps, or numbers - those always come from Postgres/SQLite via the handlers.
This keeps answers consistent and auditable, which matters a lot for a
government compliance tool.

Ollama runs locally (http://localhost:11434 by default), so there is no API
key to expire or rate-limit. If the Ollama service isn't running, or a call
fails for any reason, everything degrades gracefully to keyword-matching +
template formatting, so the project still runs end to end without it.
"""
import json
import requests
from typing import Optional
from .. import config


def _call_ollama(prompt: str, system: Optional[str] = None, max_tokens: int = 1000, temperature: float = 0.3) -> Optional[str]:
    """Low-level call to the local Ollama server. Returns None on any
    failure (server not running, model not pulled, timeout, etc.) so
    callers can fall back cleanly instead of crashing."""
    if not config.LLM_ENABLED:
        return None
    try:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        resp = requests.post(
            f"{config.OLLAMA_HOST}/api/generate",
            json={
                "model": config.OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        return text or None
    except requests.exceptions.ConnectionError:
        print("[niyamguard] Could not reach Ollama - is it running? (falling back to templates)")
        return None
    except Exception as e:
        print(f"[niyamguard] Ollama call failed, falling back to templates: {e}")
        return None


def call_raw(prompt: str, max_tokens: int = 500, temperature: float = 0.0) -> Optional[str]:
    """Public entry point for other modules (e.g. profile_extraction) that
    need a raw LLM call without going through classify_intent/format_reply.
    Returns None on any failure - callers must handle that gracefully."""
    return _call_ollama(prompt, max_tokens=max_tokens, temperature=temperature)


SYSTEM_PROMPT = """You are NiyamGuard AI, an official government policy compliance and citizen assistance
assistant. You speak the way a well-trained, professional government employee would:
clear, precise, respectful, and neutral - never casual, never speculative.

STRICT RULES:
- You may ONLY use facts given to you in the "STRUCTURED DATA" block below. Never invent
  eligibility criteria, documents, numbers, dates, or steps that are not present in it.
- COMPLETENESS IS MANDATORY: if a field, document, step, or rule exists anywhere in the
  STRUCTURED DATA, it MUST appear in your answer. Do not summarize away or skip items to
  keep the answer short - a citizen relying on this answer needs every detail that is
  present, not a shortened preview. Use bullet points or numbered lists to keep a long,
  complete answer readable.
- If the structured data says a scheme/document/circular was not found, say so plainly and
  do not guess an answer.
- Always cite the circular/GO number when referencing a rule, if one is present in the data.
- When asked to compare old vs new rules, clearly separate "Earlier position" and
  "Current position", referencing the circular numbers and effective dates.
- When asked about eligibility, always explain WHY (or why not) using the reasons_met /
  reasons_failed provided, including any stated numeric gap - do not restate them
  mechanically, but do not omit any reason either.
- When listing documents, separate Mandatory and Secondary/Supporting clearly, and state the
  number of copies required for each and any notes present.
- If structured data has a "required_fields" list (missing profile info), ask for exactly
  those fields by name - do not ask vaguely for "more information".
- If the intent is "recommend_schemes", structured data has "eligible_schemes" and
  "not_eligible_schemes" lists - present the eligible ones first with a brief reason each,
  and mention not-eligible ones only briefly if the citizen might want to know why.
- If the intent is "guided_step", structured data has a single "guided_step" with title/
  description/required_documents, plus "total_steps" and whether it "is_last_step". Present
  ONLY that one step, encourage the citizen to say "next" when ready to continue, and if
  is_last_step is true, note this is the final step.
- If the intent is "explain_legal", structured data has "circular_raw_text" - the ACTUAL
  verified text of the circular. For this intent ONLY, you may paraphrase and simplify that
  text into plain, everyday language explaining what it means - but you must not add any
  fact, number, or requirement that isn't present in that text.
- Keep tone formal and helpful, similar to how a knowledgeable government helpdesk officer
  would explain a rule to a citizen.
"""


def classify_intent(message: str) -> str:
    """Classify a user message into one of the supported intents.
    Falls back to keyword heuristics if Ollama is unavailable."""
    intents = [
        "fetch_document", "compare_versions", "check_eligibility",
        "list_documents", "get_process", "compare_schemes", "general_query",
    ]

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

    text = _call_ollama(prompt, max_tokens=20, temperature=0)
    if text:
        text_l = text.lower()
        for intent in intents:
            if intent in text_l:
                return intent

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
    history = history or []
    history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])

    prompt = f"""Conversation so far:
{history_text}

Current user message: "{user_message}"
Classified intent: {intent}

STRUCTURED DATA (this is the ONLY source of facts you may use):
{json.dumps(structured_data, indent=2, default=str) if structured_data is not None else "null - nothing was found in the knowledge base for this request."}

Write the assistant's reply now, following all rules above."""

    text = _call_ollama(prompt, system=SYSTEM_PROMPT, max_tokens=1500, temperature=0.3)
    if text:
        return text
    return _template_fallback_reply(intent, structured_data)


# ---------------------------------------------------------------------------
# Template fallback formatter - used if Ollama is unreachable. Keeps the
# project fully runnable/demoable with zero external dependencies.
# ---------------------------------------------------------------------------
def _template_fallback_reply(intent: str, data: Optional[dict]) -> str:
    if data is None:
        return "I could not find verified information on this in the knowledge base. Could you rephrase or specify the scheme/circular name?"

    if isinstance(data, dict) and data.get("error") == "missing_profile":
        return (f"To check eligibility for {data.get('scheme_name')} precisely, please provide: "
                f"{', '.join(data.get('required_fields', []))}.")

    # Full scheme detail (from scheme_detail.get_full_details) - has a
    # distinctive "key_figures" key that no other handler output has.
    if isinstance(data, dict) and "key_figures" in data:
        lines = [f"{data['scheme_name']} ({data.get('category', 'scheme')}) - {data.get('department', '')}"]
        if data.get("description"):
            lines.append(data["description"])
        lines.append(f"Governing circular: {data['governing_circular']} - {data.get('circular_title','')} "
                      f"(effective {data['effective_date']})")

        kf = data.get("key_figures", {})
        fig_lines = [f"{k.replace('_',' ').title()}: {v}" for k, v in kf.items() if v is not None]
        if fig_lines:
            lines.append("Key figures: " + "; ".join(fig_lines))

        if data.get("eligibility_rules"):
            lines.append("Eligibility criteria:")
            for r in data["eligibility_rules"]:
                lines.append(f"  - {r['explanation']}")

        docs = data.get("documents") or {}
        if docs.get("mandatory_documents"):
            lines.append("Mandatory documents:")
            for d in docs["mandatory_documents"]:
                lines.append(f"  - {d['name']} ({d['copies_required']} copy/copies)" + (f" - {d['notes']}" if d.get("notes") else ""))
        if docs.get("secondary_documents"):
            lines.append("Secondary/Supporting documents:")
            for d in docs["secondary_documents"]:
                lines.append(f"  - {d['name']} ({d['copies_required']} copy/copies)" + (f" - {d['notes']}" if d.get("notes") else ""))

        proc = data.get("process") or {}
        if proc.get("steps"):
            lines.append("Process:")
            for s in proc["steps"]:
                lines.append(f"  Step {s['step_number']}: {s['title']} - {s['description']}")

        rc = data.get("recent_change") or {}
        if rc.get("has_previous_version"):
            lines.append(f"Recent change: under {rc['old_circular']} it was different; "
                          f"as of {rc['new_circular']} (effective {rc['new_effective_date']}), "
                          + "; ".join(f"{c['field']} changed from {c['old_value']} to {c['new_value']}" for c in rc.get("changes", [])))

        return "\n".join(lines)

    if intent == "recommend_schemes" and isinstance(data, dict) and "eligible_schemes" in data:
        lines = []
        if data["eligible_schemes"]:
            lines.append("Based on your profile, you appear eligible for:")
            for s in data["eligible_schemes"]:
                lines.append(f"  - {s['scheme_name']}" + (f" (benefit: {s['benefit_amount']})" if s.get("benefit_amount") else ""))
        else:
            lines.append("Based on your profile, no schemes matched all eligibility criteria.")
        if data["not_eligible_schemes"]:
            lines.append("Not currently eligible for: " + ", ".join(s["scheme_name"] for s in data["not_eligible_schemes"]))
        return "\n".join(lines)

    if intent == "guided_step" and isinstance(data, dict) and "guided_step" in data:
        step = data.get("guided_step")
        if step is None:
            return data.get("message", "The process is complete.")
        lines = [f"{data['scheme_name']} - Step {step['step_number']} of {data.get('total_steps', '?')}: {step['title']}",
                 step["description"]]
        if step.get("required_documents"):
            lines.append("Documents needed for this step: " + ", ".join(step["required_documents"]))
        lines.append("Final step." if data.get("is_last_step") else "Say 'next' when you're ready to continue.")
        return "\n".join(lines)

    if intent == "explain_legal" and isinstance(data, dict) and "circular_raw_text" in data:
        return (f"Here is the verbatim text from {data.get('circular')}:\n\n{data['circular_raw_text']}\n\n"
                f"(Plain-language explanation requires the local LLM to be running - "
                f"start Ollama to get a simplified explanation instead of the raw text.)")

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