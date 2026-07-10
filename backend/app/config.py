"""Central configuration, read from environment variables (.env supported)."""
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./niyamguard.db")

# Ollama runs locally, so there's no key to be "missing" the way there was
# with a cloud API - LLM_ENABLED just means "a model name is configured".
# Actual reachability (is the Ollama service running?) is checked at call
# time in llm_service.py, with a graceful fallback to keyword classification
# and template replies if the local Ollama server isn't reachable.
LLM_ENABLED = bool(OLLAMA_MODEL)