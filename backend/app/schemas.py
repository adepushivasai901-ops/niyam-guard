"""Pydantic schemas - the API's request/response contracts."""
from typing import Optional, List, Any, Dict
from pydantic import BaseModel


# ---------- Chat ----------
class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    # Optional structured profile, so the frontend can pass this once and
    # the bot won't need to re-ask age/income/category every message.
    user_profile: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    session_id: str
    intent: str
    reply: str
    data: Optional[Any] = None   # raw structured data behind the reply, for transparency/debugging


# ---------- Documents ----------
class DocumentOut(BaseModel):
    id: int
    name: str
    mandatory: bool
    copies_required: int
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Eligibility ----------
class EligibilityCheckRequest(BaseModel):
    scheme_slug: str
    user_profile: Dict[str, Any]


class EligibilityResult(BaseModel):
    scheme_name: str
    version_id: int
    eligible: bool
    reasons_met: List[str]
    reasons_failed: List[str]


# ---------- Process ----------
class ProcessStepOut(BaseModel):
    step_number: int
    title: str
    description: str
    required_documents: List[str]
    is_start: bool
    is_end: bool

    class Config:
        from_attributes = True


# ---------- Version comparison ----------
class FieldChange(BaseModel):
    field: str
    old_value: Any
    new_value: Any


class VersionComparisonResult(BaseModel):
    scheme_name: str
    old_circular: str
    new_circular: str
    old_effective_date: str
    new_effective_date: str
    changes: List[FieldChange]
    document_changes: Dict[str, List[str]]   # {"added": [...], "removed": [...]}


# ---------- Scheme comparison ----------
class SchemeCompareRequest(BaseModel):
    scheme_slugs: List[str]
    user_profile: Optional[Dict[str, Any]] = None


class SchemeCompareResult(BaseModel):
    table: List[Dict[str, Any]]
    recommendation: Optional[str] = None