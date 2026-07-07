"""
NiyamGuard AI - backend entrypoint.

Run with:  uvicorn app.main:app --reload --port 8000
Docs at:   http://localhost:8000/docs
"""
import uuid
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas
from .database import engine, get_db, Base
from .handlers import eligibility, documents, process, comparison, scheme_compare, circulars
from .services import orchestrator

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="NiyamGuard AI",
    description="AI-powered government policy compliance & citizen assistance platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "NiyamGuard AI backend"}


# ---------------------------------------------------------------------------
# Chat endpoint - the single entrypoint the frontend chatbot talks to.
# ---------------------------------------------------------------------------
@app.post("/api/chat", response_model=schemas.ChatResponse)
def chat(req: schemas.ChatRequest, db: Session = Depends(get_db)):
    session_id = req.session_id or str(uuid.uuid4())

    session = db.query(models.ChatSession).get(session_id)
    if not session:
        session = models.ChatSession(id=session_id)
        db.add(session)
        db.commit()

    history = [{"role": m.role, "content": m.content} for m in session.messages]

    intent, reply, data = orchestrator.handle_message(db, req.message, req.user_profile, history)

    db.add(models.ChatMessage(session_id=session_id, role="user", content=req.message, intent=intent))
    db.add(models.ChatMessage(session_id=session_id, role="assistant", content=reply, intent=intent))
    db.commit()

    return schemas.ChatResponse(session_id=session_id, intent=intent, reply=reply, data=data)


# ---------------------------------------------------------------------------
# Direct REST endpoints - useful for the Government Portal / debugging /
# hitting a specific capability without going through the chat classifier.
# ---------------------------------------------------------------------------
@app.get("/api/schemes")
def list_schemes(db: Session = Depends(get_db)):
    schemes = db.query(models.Scheme).all()
    return [{"slug": s.slug, "name": s.name, "category": s.category} for s in schemes]


@app.post("/api/eligibility/check", response_model=schemas.EligibilityResult)
def eligibility_check(req: schemas.EligibilityCheckRequest, db: Session = Depends(get_db)):
    result = eligibility.check_eligibility(db, req.scheme_slug, req.user_profile)
    if not result:
        raise HTTPException(404, "Scheme not found")
    return result


@app.get("/api/schemes/{scheme_slug}/documents")
def scheme_documents(scheme_slug: str, db: Session = Depends(get_db)):
    result = documents.get_documents(db, scheme_slug)
    if not result:
        raise HTTPException(404, "Scheme not found")
    return result


@app.get("/api/schemes/{scheme_slug}/process")
def scheme_process(scheme_slug: str, db: Session = Depends(get_db)):
    result = process.get_process(db, scheme_slug)
    if not result:
        raise HTTPException(404, "Scheme not found")
    return result


@app.get("/api/schemes/{scheme_slug}/compare-versions")
def scheme_compare_versions(scheme_slug: str, db: Session = Depends(get_db)):
    result = comparison.compare_with_previous(db, scheme_slug)
    if not result:
        raise HTTPException(404, "Scheme not found")
    return result


@app.post("/api/schemes/compare", response_model=schemas.SchemeCompareResult)
def compare_multiple_schemes(req: schemas.SchemeCompareRequest, db: Session = Depends(get_db)):
    result = scheme_compare.compare_schemes(db, req.scheme_slugs, req.user_profile)
    return schemas.SchemeCompareResult(table=result["table"])


@app.get("/api/circulars/search")
def search_circulars(q: str, db: Session = Depends(get_db)):
    return circulars.find_circulars(db, q)


@app.get("/api/circulars/{circular_id}/text")
def circular_text(circular_id: int, db: Session = Depends(get_db)):
    text = circulars.get_circular_text(db, circular_id)
    if text is None:
        raise HTTPException(404, "Circular not found")
    return {"circular_id": circular_id, "text": text}
