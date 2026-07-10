# NiyamGuard AI — Citizen Assistant Chatbot (Backend)

A working FastAPI backend for the NiyamGuard AI problem statement: a government
policy compliance & citizen assistance platform. This delivers the **citizen
chatbot** side end-to-end, built on a design principle that matters a lot for
a compliance tool:

> **The LLM never invents facts.** Eligibility results, document lists,
> process steps, and old-vs-new comparisons all come from a structured
> database and a deterministic rules engine. The LLM's only job is to
> classify what the citizen is asking and phrase the already-computed
> answer in professional, government-officer-style language. This is what
> makes answers consistent, auditable, and safe to demo live — and it holds
> even when there is no LLM key configured at all, since every handler also
> has a template-based fallback formatter.

---

## 1. What's included

```
niyamguard/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app + all routes
│   │   ├── models.py            SQLAlchemy schema (the source of truth)
│   │   ├── schemas.py           Pydantic request/response contracts
│   │   ├── database.py          DB engine/session setup (SQLite by default)
│   │   ├── config.py            Env-based configuration (Google Gemini)
│   │   ├── seed_data.py         Realistic sample data (see below)
│   │   ├── handlers/            Deterministic logic — no LLM involved
│   │   │   ├── eligibility.py       rules engine, with quantified gap explanations
│   │   │   ├── documents.py         mandatory/secondary docs + copies
│   │   │   ├── process.py           step-by-step procedure
│   │   │   ├── comparison.py        old vs new circular diff
│   │   │   ├── scheme_compare.py    scheme vs scheme comparison
│   │   │   ├── circulars.py         document/circular retrieval
│   │   │   └── scheme_detail.py     full-detail aggregator for broad questions
│   │   └── services/
│   │       ├── llm_service.py       Google Gemini calls + graceful fallback
│   │       └── orchestrator.py      routes intent -> handler -> LLM formatter
│   ├── requirements.txt
│   ├── .env.example
│   └── run.sh
└── frontend/
    └── index.html            Minimal chat UI to demo the whole system
```

## 2. Seed data (already built in)

Running the seed script loads **3 schemes**, each with a **current version**
linked to its **previous version** so comparisons work immediately:

1. **Income Certificate** — the exact scenario from the problem statement:
   validity period 12 months (GO Ms No. 112) → amended to 6 months (GO Ms No.
   138), which also adds a new mandatory document (photograph). This proves
   the "old vs new" comparison and cascading-document-change features.
2. **Post-Matric Scholarship** — income limit raised Rs. 2,00,000 → Rs.
   2,50,000, benefit amount raised, with a full eligibility rule set
   (age, income, category, enrollment), documents, and a 4-step process.
3. **Old-Age Pension Scheme** — a second scheme with different eligibility
   rules, used to demonstrate scheme-vs-scheme comparison against the
   scholarship.

## 3. Setup (Windows / PowerShell)

These are the exact steps for Windows PowerShell, which is what this project
has been set up and tested on.

```powershell
cd backend

# Create and activate a virtual environment (use Python 3.12 specifically -
# very new Python releases like 3.14 can break compiled dependencies such
# as pydantic-core; if you don't have 3.12, install it from python.org first)
py -3.12 -m venv venv
venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script with an error about "running
scripts is disabled on this system," run this once (only needed once per
machine), then retry the `Activate.ps1` line above:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Once activated, your prompt shows `(venv)` at the start. Then:

```powershell
pip install -r requirements.txt

copy .env.example .env
# Edit .env and set GOOGLE_API_KEY for natural-language responses.
# Get a free key (no billing card required) at https://aistudio.google.com/apikey
# The app still runs and answers correctly WITHOUT a key - it falls back to
# keyword-based intent classification and template-formatted replies.

.\run.ps1
```

`run.ps1` seeds the database on first run (if `niyamguard.db` doesn't exist
yet) and starts the API server. If you'd rather run those two steps
yourself instead of using the script:

```powershell
python -m app.seed_data
uvicorn app.main:app --reload --port 8000
```

Either way, the server starts at `http://localhost:8000` (interactive
Swagger docs at `http://localhost:8000/docs`). Leave this terminal running.

Then open `frontend/index.html` directly in a browser (double-click it in
File Explorer, or right-click → Open with → your browser) — no build step,
it's a single static file that calls `http://localhost:8000`.

**Restarting later:** every new session, just re-activate the venv
(`venv\Scripts\Activate.ps1` from inside `backend`) and run `.\run.ps1`
again — no need to reinstall anything unless `requirements.txt` changed.

> **macOS / Linux users:** the equivalent commands are
> `python3 -m venv venv`, `source venv/bin/activate`,
> `cp .env.example .env`, and `./run.sh` in place of the Windows commands
> above. This project's primary/tested instructions are the Windows ones
> above; Mac/Linux users may need to adjust minor path syntax.

## 4. Answering precisely and completely

Two upgrades specifically target answer quality:

- **Eligibility gaps are quantified, not just pass/fail.** If a numeric rule
  fails (income, age, etc.), the explanation states exactly how far off the
  citizen is — e.g. *"exceeds the limit by 15,000"* — instead of a flat
  "criteria not met". If eligibility is asked about with no profile filled
  in, the response names the **exact fields** that scheme's rules require,
  rather than a generic "need more info".
- **Broad questions get everything, not a preview.** Asking *"tell me about
  the scholarship"* or *"give me full details of the income certificate"*
  routes to `scheme_detail.get_full_details()`, which aggregates eligibility
  rules, documents, process steps, key figures, and the most recent circular
  change into a single answer — regardless of which single-purpose intent
  the message would otherwise classify as. The system prompt also
  explicitly instructs the LLM never to drop a field that exists in the
  structured data, and the template fallback (used when no LLM key is
  configured) mirrors the same completeness so answer quality doesn't
  depend on having a working API key.

## 5. Try it — sample questions that exercise every requirement

| What you type | What happens under the hood |
|---|---|
| "Show me the income certificate circular" | `fetch_document` → keyword search over `Circular` table |
| "What changed between the old and new income certificate rule?" | `compare_versions` → structured diff between the two `SchemeVersion` rows (12→6 months, + new photo requirement) |
| "What documents are required for post-matric scholarship?" | `list_documents` → mandatory vs secondary docs, with copies required |
| "Am I eligible for post-matric scholarship?" *(fill in the profile bar first)* | `check_eligibility` → every `EligibilityRule` evaluated against the profile, with a quantified reason for/against each |
| "What is the process for old-age pension?" | `get_process` → ordered steps, each with its required documents |
| "Compare post-matric scholarship and old-age pension" | `compare_schemes` → structured comparison table, LLM justifies which fits the citizen better *grounded in that table* |
| "Tell me everything about the post-matric scholarship" | `scheme_detail` full aggregator → eligibility + documents + process + recent circular change, in one answer |

## 6. Extending toward the full platform

This backend is deliberately structured so the remaining problem-statement
pieces slot in without rearchitecting:

- **Ingestion pipeline (Module 2, auto-extraction from raw circular PDFs):**
  add a `/api/circulars/ingest` endpoint that runs a PDF → text → structured
  JSON extraction (Gemini with a strict extraction prompt), writes a new
  `Circular` + `SchemeVersion` row, and sets `extraction_confidence` /
  `needs_human_review` — the fields already exist on the model for this.
- **Compliance Verification (Module 3) / Cascade Tracing (Module 4):**
  add a `ConnectedSystem` model (portal, manual, FAQ, form) with its own
  "what it currently reflects" snapshot, diff it against the current
  `SchemeVersion`, and reuse `comparison.py`'s diff logic. **This is the
  single biggest gap between this repo and the full problem statement** —
  the doc calls it the platform's "core innovation," and none of it is built
  yet. Prioritize this if time allows.
- **Priority Dashboard (Module 5):** rank open mismatches by a simple
  weighted score (systems affected × citizens affected × days stale).
- **Voice Access (Citizen Module 4):** add speech-to-text on the way into
  `/api/chat` and text-to-speech on the way out — the endpoint itself
  doesn't need to change.
- **Vector search for fuzzy circular lookup:** swap `circulars.find_circulars`'s
  keyword `ILIKE` search for a vector DB (e.g. Chroma/pgvector) over
  `Circular.raw_text` embeddings, for when citizens don't know the exact
  circular number or scheme name.
- **Swap SQLite → Postgres:** just change `DATABASE_URL` in `.env` — no code
  changes needed since everything goes through SQLAlchemy's ORM.

## 7. Why this architecture (for your hackathon pitch)

Judges will probe whether your chatbot can be trusted with government data.
The strongest thing you can say is: *the chatbot cannot hallucinate an
eligibility result or a document list, because it never generates those —
it only retrieves and phrases rows from a structured database that a human
verified during ingestion.* That is the entire thesis of the problem
statement (a *coordination and propagation* problem, not a knowledge
problem) applied to the chatbot itself.