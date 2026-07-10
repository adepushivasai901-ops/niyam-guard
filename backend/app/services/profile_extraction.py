"""
Citizen profile extraction (information extraction module).

Turns free text like "I am a first-year B.Tech student from the BC category
with an annual family income of Rs 2,30,000" into structured fields:

    {
      "occupation": "Student", "category": "BC", "annual_income": 230000,
      "currently_enrolled": true, "citizen_categories": ["student"]
    }

"citizen_categories" is the important part for the citizen-centric workflow:
it's a list of tags (from CITIZEN_CATEGORY_TAGS below) used to narrow which
schemes are even considered, BEFORE the deterministic eligibility engine
runs - e.g. mentioning "ex-serviceman" tags ["ex_serviceman"], so only
ex-servicemen schemes are checked, not all fifteen schemes in the database.

This is the one place in the codebase where the LLM is allowed to produce
values that feed into logic (which schemes get checked) rather than just
phrasing an answer - but note it still never decides ELIGIBILITY itself;
it only decides which schemes are worth checking, and the deterministic
rules engine in eligibility.py makes the actual pass/fail call. If
extraction fails or Ollama is unavailable, this simply returns an empty
result and the system falls back to asking the citizen directly (via the
existing missing_profile flow), rather than guessing.
"""
import json
import re
from typing import Dict, Any
from . import llm_service

CITIZEN_CATEGORY_TAGS = [
    "student", "farmer", "senior_citizen", "woman", "widow", "disability",
    "ex_serviceman", "sportsperson", "entrepreneur", "construction_worker",
    "laborer", "minority", "sc", "st", "obc", "ews", "tribal",
    "transgender", "orphan_student", "unemployed", "general",
]

EXTRACTION_PROMPT_TEMPLATE = """Extract structured information from this citizen's message. Return ONLY a
JSON object, no other text, no markdown code fences.

Fields to extract (omit any field that isn't mentioned - do not guess or default):
- "occupation": string, e.g. "Student", "Farmer", "Ex-serviceman", "Construction Worker"
- "category": string, one of SC/ST/OBC/EWS/General/BC if mentioned
- "annual_income": number (rupees, no commas/symbols)
- "age": number
- "gender": string
- "disability_percentage": number, if a disability percentage is mentioned
- "currently_enrolled": true/false, if the person mentions being a current student
- "citizen_categories": array of zero or more tags from this exact list that apply to this
  person, based on what they said: {tags}

Message: "{message}"

JSON:"""


def extract_profile(message: str) -> Dict[str, Any]:
    """Returns a dict of extracted fields (possibly empty). Never raises -
    on any failure (Ollama unavailable, malformed JSON, etc.) returns {}."""
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(tags=", ".join(CITIZEN_CATEGORY_TAGS), message=message)
    text = llm_service.call_raw(prompt, max_tokens=300, temperature=0)
    if not text:
        return {}

    # Strip markdown code fences if the model added them despite instructions.
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        data = json.loads(cleaned)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    # Sanity-filter citizen_categories to only known tags, in case the model invents one.
    if "citizen_categories" in data and isinstance(data["citizen_categories"], list):
        data["citizen_categories"] = [c for c in data["citizen_categories"] if c in CITIZEN_CATEGORY_TAGS]

    return data