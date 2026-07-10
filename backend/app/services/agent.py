"""
Agentic chat loop - combines three of the four pillars:

  1. FUNCTION CALLING: the LLM is given tools (tools.py) and decides which
     to call, with what arguments - it does not answer directly if a tool
     is needed for the question.
  2. GROUNDED GENERATION: tool results are fed back to the model, which may
     call further tools, then writes a final answer citing the retrieved
     data (circular numbers, exact figures) rather than free-associating.
  3. VERIFICATION: a separate pass re-checks the drafted answer against
     every tool result collected during the loop, and corrects any claim
     that isn't actually supported - a safety net beyond prompting alone.

(RAG - semantic search - lives in embeddings.py and is exposed as the
search_circular_content tool, so it's pillar-4 by way of pillar-1.)

If the LLM is unavailable, callers should use orchestrator.handle_message
instead (the deterministic keyword-routed path) - this module has a hard
dependency on a working Gemini connection.
"""
import json
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.orm import Session

from .. import config, models
from . import tools as tools_module

MAX_TOOL_ITERATIONS = 4

AGENT_SYSTEM_PROMPT = """You are NiyamGuard AI, an official government policy compliance and citizen
assistance assistant. You speak the way a well-trained, professional government employee would:
clear, precise, respectful, and neutral - never casual, never speculative.

You have tools that query a verified government database. For ANY question involving a specific
scheme's eligibility, documents, process, comparisons, or circular content, you MUST call the
appropriate tool rather than answering from memory - you do not know current rules on your own,
only the tools do.

STRICT RULES:
- Never state an eligibility result, document, number, date, or process step that did not come
  from a tool result. If a tool returns an error or empty result, say so plainly.
- COMPLETENESS IS MANDATORY: include every relevant field/document/step/reason from tool
  results - do not shorten or skip items to save space.
- Always cite the circular/GO number when referencing a rule.
- When comparing old vs new rules, separate "Earlier position" and "Current position" clearly.
- When explaining eligibility, state numeric gaps precisely if present in the tool result.
- If a tool result has "error": "missing_profile", ask for exactly the listed required_fields.
- Use tools across multiple turns if the question needs more than one lookup.
"""

_genai = None
if config.LLM_ENABLED:
    try:
        import google.generativeai as genai
        _genai = genai
    except Exception:
        _genai = None


def _get_valid_slugs(db: Session) -> List[str]:
    return [s.slug for s in db.query(models.Scheme).all()]


def run_agentic_chat(
    db: Session,
    message: str,
    user_profile: Optional[Dict[str, Any]],
    history: List[Dict[str, str]],
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """Returns (intent_label, reply_text, last_tool_data) - same shape as
    orchestrator.handle_message so main.py can call either interchangeably."""
    if _genai is None:
        raise RuntimeError("Agentic chat requires a configured LLM - caller should use the fallback orchestrator instead.")

    valid_slugs = _get_valid_slugs(db)
    tool = tools_module.build_tools(valid_slugs)

    gen_model = _genai.GenerativeModel(
        config.LLM_MODEL,
        system_instruction=AGENT_SYSTEM_PROMPT,
        tools=[tool] if tool else None,
    )

    past_turns = [{"role": ("user" if h["role"] == "user" else "model"), "parts": [h["content"]]} for h in history[-6:]]
    chat = gen_model.start_chat(history=past_turns)

    all_tool_results: List[Dict[str, Any]] = []
    last_data: Optional[Dict[str, Any]] = None
    tool_names_called: List[str] = []

    response = chat.send_message(message)

    for _ in range(MAX_TOOL_ITERATIONS):
        function_calls = _extract_function_calls(response)
        if not function_calls:
            break

        function_response_parts = []
        for fc in function_calls:
            result = tools_module.dispatch(db, fc["name"], fc["args"], user_profile or {})
            last_data = result
            tool_names_called.append(fc["name"])
            all_tool_results.append({"tool": fc["name"], "args": fc["args"], "result": result})
            function_response_parts.append(
                _genai.protos.Part(function_response=_genai.protos.FunctionResponse(
                    name=fc["name"],
                    response={"result": json.dumps(result, default=str)},
                ))
            )

        response = chat.send_message(function_response_parts)

    draft_text = _extract_text(response) or "I could not generate a response - please rephrase your question."

    final_text = _verify_and_correct(draft_text, all_tool_results)

    intent_label = "+".join(dict.fromkeys(tool_names_called)) if tool_names_called else "general_query"
    return intent_label, final_text, last_data


def _extract_function_calls(response) -> List[Dict[str, Any]]:
    calls = []
    try:
        for part in response.candidates[0].content.parts:
            fc = getattr(part, "function_call", None)
            if fc and fc.name:
                calls.append({"name": fc.name, "args": dict(fc.args)})
    except Exception:
        pass
    return calls


def _extract_text(response) -> str:
    try:
        return response.text.strip()
    except Exception:
        try:
            parts = response.candidates[0].content.parts
            return "".join(getattr(p, "text", "") for p in parts).strip()
        except Exception:
            return ""


VERIFIER_PROMPT_TEMPLATE = """You are a strict fact-checker for a government assistant. Below is a DRAFT
ANSWER and the TOOL RESULTS it was supposed to be based on.

Check every factual claim in the draft (numbers, document names, dates, eligibility results,
circular numbers, steps). If a claim is NOT supported by the tool results, remove or correct it.
If the draft omits something present in the tool results that seems relevant to the question,
add it back in. Do not add any new information not present in the tool results.

If the draft is already fully accurate and complete, return it unchanged.

TOOL RESULTS:
{tool_results}

DRAFT ANSWER:
{draft}

Return ONLY the corrected final answer text - no preamble, no explanation of what you changed."""


def _verify_and_correct(draft: str, tool_results: List[Dict[str, Any]]) -> str:
    if not tool_results or _genai is None:
        return draft  # nothing to verify against (e.g. a pure greeting) - or no LLM available
    try:
        verifier_model = _genai.GenerativeModel(config.LLM_MODEL)
        prompt = VERIFIER_PROMPT_TEMPLATE.format(
            tool_results=json.dumps(tool_results, indent=2, default=str),
            draft=draft,
        )
        resp = verifier_model.generate_content(prompt, generation_config={"max_output_tokens": 2000, "temperature": 0})
        corrected = resp.text.strip()
        return corrected or draft
    except Exception:
        return draft  # if the verifier itself fails, serve the unverified draft rather than erroring out