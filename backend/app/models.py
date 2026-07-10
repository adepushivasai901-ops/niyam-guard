"""
Core data model for NiyamGuard AI.

DESIGN PRINCIPLE (read this before touching the schema):
The chatbot must NEVER invent eligibility rules, document lists, or process
steps at answer-time. Every fact it states has to already exist as a row here,
extracted once during ingestion and verified. The LLM's only job downstream
is to explain / phrase / compare these rows in natural language - never to
be the source of the facts themselves.

Versioning principle:
A circular that changes a rule does NOT overwrite the old SchemeVersion row.
It creates a NEW SchemeVersion row, linked via previous_version_id to the old
one, and marks itself as is_current=True while the old row flips to False.
This is what makes "compare old vs new circular" a plain data diff instead of
an LLM re-reading two PDFs and hoping it notices the difference.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from .database import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, nullable=True)

    schemes = relationship("Scheme", back_populates="department")


class Circular(Base):
    """A single uploaded source document (circular / GO / notification)."""
    __tablename__ = "circulars"

    id = Column(Integer, primary_key=True)
    doc_number = Column(String(100), nullable=False)       # e.g. "GO Ms No. 45"
    title = Column(String(300), nullable=False)
    issued_date = Column(DateTime, nullable=False)
    effective_date = Column(DateTime, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"))
    raw_text = Column(Text, nullable=True)                 # full extracted text
    file_path = Column(String(500), nullable=True)         # where the original file lives
    supersedes_circular_id = Column(Integer, ForeignKey("circulars.id"), nullable=True)
    extraction_confidence = Column(Float, default=1.0)     # 0-1, set during ingestion
    needs_human_review = Column(Boolean, default=False)     # low-confidence extractions get routed here
    embedding = Column(Text, nullable=True)                 # JSON-encoded vector, for semantic (RAG) search

    department = relationship("Department")


class Scheme(Base):
    """A logical scheme/service, e.g. 'Income Certificate', 'Post-Matric Scholarship'.
    Stays constant across time; SchemeVersion rows underneath it change over time."""
    __tablename__ = "schemes"

    id = Column(Integer, primary_key=True)
    name = Column(String(300), nullable=False)
    slug = Column(String(300), nullable=False, unique=True)   # for fast lookup, e.g. "income-certificate"
    category = Column(String(100), nullable=True)             # e.g. "certificate", "scholarship", "pension"
    department_id = Column(Integer, ForeignKey("departments.id"))
    short_description = Column(Text, nullable=True)

    department = relationship("Department", back_populates="schemes")
    versions = relationship("SchemeVersion", back_populates="scheme", order_by="SchemeVersion.id")


class SchemeVersion(Base):
    """One version-in-time of a scheme's rules. This is the row that gets diffed
    when comparing 'old circular vs new circular'."""
    __tablename__ = "scheme_versions"

    id = Column(Integer, primary_key=True)
    scheme_id = Column(Integer, ForeignKey("schemes.id"), nullable=False)
    circular_id = Column(Integer, ForeignKey("circulars.id"), nullable=False)
    previous_version_id = Column(Integer, ForeignKey("scheme_versions.id"), nullable=True)

    is_current = Column(Boolean, default=True)

    # Structured, comparable fields - extend freely per scheme type.
    validity_period_months = Column(Integer, nullable=True)
    income_limit_annual = Column(Float, nullable=True)
    age_min = Column(Integer, nullable=True)
    age_max = Column(Integer, nullable=True)
    benefit_amount = Column(Float, nullable=True)
    processing_time_days = Column(Integer, nullable=True)
    category_rules = Column(JSON, nullable=True)     # e.g. {"allowed_categories": ["SC","ST","OBC","General"]}
    extra_fields = Column(JSON, nullable=True)        # catch-all for scheme-specific structured data

    scheme = relationship("Scheme", back_populates="versions")
    circular = relationship("Circular")
    eligibility_rules = relationship("EligibilityRule", back_populates="version", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="version", cascade="all, delete-orphan")
    steps = relationship("ProcessStep", back_populates="version",
                          order_by="ProcessStep.step_number", cascade="all, delete-orphan")

    COMPARABLE_FIELDS = [
        "validity_period_months", "income_limit_annual", "age_min",
        "age_max", "benefit_amount", "processing_time_days",
    ]


class EligibilityRule(Base):
    """A single, structured, evaluable eligibility condition.
    field/operator/value is deliberately simple (no free-text) so it can be
    evaluated in plain Python with zero ambiguity."""
    __tablename__ = "eligibility_rules"

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("scheme_versions.id"), nullable=False)
    field_name = Column(String(100), nullable=False)     # e.g. "age", "annual_income", "category"
    operator = Column(String(20), nullable=False)        # "==", "!=", "<", "<=", ">", ">=", "in"
    value = Column(JSON, nullable=False)                 # number, string, or list
    explanation = Column(Text, nullable=False)           # human-readable reason, shown when rule is met/not met

    version = relationship("SchemeVersion", back_populates="eligibility_rules")


class Document(Base):
    """A document required for a scheme version."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("scheme_versions.id"), nullable=False)
    name = Column(String(300), nullable=False)
    mandatory = Column(Boolean, default=True)          # True = mandatory, False = secondary/supporting
    copies_required = Column(Integer, default=1)
    notes = Column(Text, nullable=True)                # e.g. "must be self-attested"

    version = relationship("SchemeVersion", back_populates="documents")


class ProcessStep(Base):
    """One ordered step in the application process, start to finish."""
    __tablename__ = "process_steps"

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("scheme_versions.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    required_document_ids = Column(JSON, nullable=True)   # list of Document.id needed at this step
    is_start = Column(Boolean, default=False)
    is_end = Column(Boolean, default=False)

    version = relationship("SchemeVersion", back_populates="steps")


# ---------------------------------------------------------------------------
# Lightweight chat memory, so multi-turn conversations ("what about for OBC?"
# following an eligibility question) can resolve pronouns/context.
# ---------------------------------------------------------------------------
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(64), primary_key=True)   # client-generated session id (e.g. uuid4)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("ChatMessage", back_populates="session", order_by="ChatMessage.id")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)     # "user" | "assistant"
    content = Column(Text, nullable=False)
    intent = Column(String(50), nullable=True)    # classified intent, useful for demo/debug logs
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")