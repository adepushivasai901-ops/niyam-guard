"""Central configuration, read from environment variables (.env supported)."""
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./niyamguard.db")

# If no API key is configured, the app still runs: intent classification
# falls back to keyword rules and responses fall back to a template
# formatter, so the demo never hard-fails just because a key isn't set.
LLM_ENABLED = bool(GOOGLE_API_KEY)