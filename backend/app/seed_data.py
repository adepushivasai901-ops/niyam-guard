"""
Seed data.

Hand-crafted (not auto-extracted) so the demo is 100% reliable regardless of
whether the ingestion/extraction pipeline is wired up. Includes the exact
"income certificate validity 12 months -> 6 months" scenario from the
problem statement, plus a scholarship scheme and a pension scheme (each with
two versions) so eligibility, documents, process, comparison, and
scheme-vs-scheme features all have real data to run against.

Run with:  python -m app.seed_data
"""
from datetime import datetime
from .database import SessionLocal, engine, Base
from . import models

Base.metadata.create_all(bind=engine)


def run():
    db = SessionLocal()

    # Wipe existing data for a clean re-seed (fine for a hackathon demo).
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()

    # ---------------- Departments ----------------
    revenue_dept = models.Department(name="Revenue Department", description="Certificates & land records")
    welfare_dept = models.Department(name="Social Welfare Department", description="Scholarships & pensions")
    db.add_all([revenue_dept, welfare_dept])
    db.commit()

    # =====================================================================
    # SCHEME 1: Income Certificate (the exact example from the problem statement)
    # =====================================================================
    income_cert = models.Scheme(
        name="Income Certificate",
        slug="income-certificate",
        category="certificate",
        department_id=revenue_dept.id,
        short_description="A certificate confirming a citizen's/family's annual income, used to avail welfare schemes.",
    )
    db.add(income_cert)
    db.commit()

    # --- Old circular: validity 12 months ---
    old_circular = models.Circular(
        doc_number="GO Ms No. 112",
        title="Revised procedure for issuance of Income Certificates",
        issued_date=datetime(2023, 4, 10),
        effective_date=datetime(2023, 4, 15),
        department_id=revenue_dept.id,
        raw_text=(
            "The Government hereby orders that an Income Certificate issued under this scheme "
            "shall remain valid for a period of TWELVE (12) MONTHS from the date of issue for all "
            "purposes including scholarship and fee reimbursement applications."
        ),
        extraction_confidence=1.0,
    )
    db.add(old_circular)
    db.commit()

    old_version = models.SchemeVersion(
        scheme_id=income_cert.id,
        circular_id=old_circular.id,
        is_current=False,
        validity_period_months=12,
        income_limit_annual=None,
        processing_time_days=7,
        extra_fields={},
    )
    db.add(old_version)
    db.commit()

    db.add_all([
        models.Document(version_id=old_version.id, name="Aadhaar Card", mandatory=True, copies_required=1),
        models.Document(version_id=old_version.id, name="Ration Card", mandatory=True, copies_required=1),
        models.Document(version_id=old_version.id, name="Self-declaration of income (affidavit)", mandatory=True, copies_required=1),
        models.Document(version_id=old_version.id, name="Salary slip / income proof", mandatory=False, copies_required=1,
                         notes="Required only for salaried applicants"),
    ])
    db.commit()

    db.add_all([
        models.ProcessStep(version_id=old_version.id, step_number=1, title="Submit application",
                            description="Submit application at MeeSeva/Citizen Service Center with required documents.",
                            required_document_ids=[d.id for d in old_version.documents if d.mandatory],
                            is_start=True),
        models.ProcessStep(version_id=old_version.id, step_number=2, title="Field verification",
                            description="Village Revenue Officer (VRO) conducts field verification of income details.",
                            required_document_ids=[]),
        models.ProcessStep(version_id=old_version.id, step_number=3, title="Approval",
                            description="Tahsildar reviews and approves/rejects the application.",
                            required_document_ids=[], is_end=True),
    ])
    db.commit()

    # --- New circular: validity reduced to 6 months (supersedes the old one) ---
    new_circular = models.Circular(
        doc_number="GO Ms No. 138",
        title="Amendment to validity period of Income Certificates",
        issued_date=datetime(2026, 5, 20),
        effective_date=datetime(2026, 6, 1),
        department_id=revenue_dept.id,
        supersedes_circular_id=old_circular.id,
        raw_text=(
            "In partial modification of GO Ms No. 112 dated 10-04-2023, the Government hereby orders "
            "that an Income Certificate issued under this scheme shall henceforth remain valid for a "
            "period of SIX (6) MONTHS only from the date of issue, for all purposes including "
            "scholarship and fee reimbursement applications. Additionally, applicants must now submit "
            "a recent passport-size photograph along with the application."
        ),
        extraction_confidence=0.97,
    )
    db.add(new_circular)
    db.commit()

    new_version = models.SchemeVersion(
        scheme_id=income_cert.id,
        circular_id=new_circular.id,
        previous_version_id=old_version.id,
        is_current=True,
        validity_period_months=6,
        income_limit_annual=None,
        processing_time_days=7,
        extra_fields={},
    )
    db.add(new_version)
    db.commit()

    mandatory_docs_new = [
        models.Document(version_id=new_version.id, name="Aadhaar Card", mandatory=True, copies_required=1),
        models.Document(version_id=new_version.id, name="Ration Card", mandatory=True, copies_required=1),
        models.Document(version_id=new_version.id, name="Self-declaration of income (affidavit)", mandatory=True, copies_required=1),
        models.Document(version_id=new_version.id, name="Passport-size photograph", mandatory=True, copies_required=2,
                         notes="New requirement introduced by GO Ms No. 138"),
    ]
    secondary_docs_new = [
        models.Document(version_id=new_version.id, name="Salary slip / income proof", mandatory=False, copies_required=1,
                         notes="Required only for salaried applicants"),
    ]
    db.add_all(mandatory_docs_new + secondary_docs_new)
    db.commit()

    all_new_mandatory_ids = [d.id for d in mandatory_docs_new]
    db.add_all([
        models.ProcessStep(version_id=new_version.id, step_number=1, title="Submit application",
                            description="Submit application at MeeSeva/Citizen Service Center with required documents "
                                         "(now including a passport-size photograph).",
                            required_document_ids=all_new_mandatory_ids, is_start=True),
        models.ProcessStep(version_id=new_version.id, step_number=2, title="Field verification",
                            description="Village Revenue Officer (VRO) conducts field verification of income details.",
                            required_document_ids=[]),
        models.ProcessStep(version_id=new_version.id, step_number=3, title="Approval",
                            description="Tahsildar reviews and approves/rejects the application.",
                            required_document_ids=[], is_end=True),
    ])
    db.commit()

    # =====================================================================
    # SCHEME 2: Post-Matric Scholarship (has an eligibility rule set + 2 versions)
    # =====================================================================
    scholarship = models.Scheme(
        name="Post-Matric Scholarship",
        slug="post-matric-scholarship",
        category="scholarship",
        department_id=welfare_dept.id,
        short_description="Financial assistance for students pursuing education after Class 10, from economically weaker sections.",
    )
    db.add(scholarship)
    db.commit()

    sch_old_circular = models.Circular(
        doc_number="GO Ms No. 58",
        title="Post-Matric Scholarship Scheme guidelines",
        issued_date=datetime(2022, 6, 1),
        effective_date=datetime(2022, 6, 15),
        department_id=welfare_dept.id,
        raw_text="Annual family income limit for eligibility under the Post-Matric Scholarship Scheme is Rs. 2,00,000.",
        extraction_confidence=1.0,
    )
    db.add(sch_old_circular)
    db.commit()

    sch_old_version = models.SchemeVersion(
        scheme_id=scholarship.id, circular_id=sch_old_circular.id, is_current=False,
        income_limit_annual=200000, age_min=15, age_max=25, benefit_amount=12000, processing_time_days=30,
        category_rules={"allowed_categories": ["SC", "ST", "OBC", "General-EWS"]},
    )
    db.add(sch_old_version)
    db.commit()

    sch_new_circular = models.Circular(
        doc_number="GO Ms No. 91",
        title="Revision of income limit for Post-Matric Scholarship Scheme",
        issued_date=datetime(2026, 3, 1),
        effective_date=datetime(2026, 4, 1),
        department_id=welfare_dept.id,
        supersedes_circular_id=sch_old_circular.id,
        raw_text=(
            "In partial modification of GO Ms No. 58, the annual family income limit for eligibility "
            "under the Post-Matric Scholarship Scheme is hereby revised to Rs. 2,50,000. The benefit "
            "amount is enhanced to Rs. 15,000 per annum."
        ),
        extraction_confidence=1.0,
    )
    db.add(sch_new_circular)
    db.commit()

    sch_new_version = models.SchemeVersion(
        scheme_id=scholarship.id, circular_id=sch_new_circular.id,
        previous_version_id=sch_old_version.id, is_current=True,
        income_limit_annual=250000, age_min=15, age_max=25, benefit_amount=15000, processing_time_days=30,
        category_rules={"allowed_categories": ["SC", "ST", "OBC", "General-EWS"]},
    )
    db.add(sch_new_version)
    db.commit()

    db.add_all([
        models.EligibilityRule(version_id=sch_new_version.id, field_name="annual_income", operator="<=", value=250000,
                                explanation="Annual family income must not exceed Rs. 2,50,000"),
        models.EligibilityRule(version_id=sch_new_version.id, field_name="age", operator=">=", value=15,
                                explanation="Applicant must be at least 15 years old"),
        models.EligibilityRule(version_id=sch_new_version.id, field_name="age", operator="<=", value=25,
                                explanation="Applicant must not be older than 25 years"),
        models.EligibilityRule(version_id=sch_new_version.id, field_name="category", operator="in",
                                value=["SC", "ST", "OBC", "General-EWS"],
                                explanation="Applicant must belong to SC / ST / OBC / General-EWS category"),
        models.EligibilityRule(version_id=sch_new_version.id, field_name="currently_enrolled", operator="==", value=True,
                                explanation="Applicant must be currently enrolled in a post-Class-10 course"),
    ])
    db.commit()

    sch_docs = [
        models.Document(version_id=sch_new_version.id, name="Income Certificate (valid, current)", mandatory=True, copies_required=1,
                         notes="Must be within current validity period - see Income Certificate scheme"),
        models.Document(version_id=sch_new_version.id, name="Caste Certificate", mandatory=True, copies_required=1),
        models.Document(version_id=sch_new_version.id, name="Previous year mark sheet", mandatory=True, copies_required=1),
        models.Document(version_id=sch_new_version.id, name="Bonafide certificate from institution", mandatory=True, copies_required=1),
        models.Document(version_id=sch_new_version.id, name="Bank passbook copy", mandatory=False, copies_required=1,
                         notes="For direct benefit transfer"),
    ]
    db.add_all(sch_docs)
    db.commit()

    mandatory_ids = [d.id for d in sch_docs if d.mandatory]
    db.add_all([
        models.ProcessStep(version_id=sch_new_version.id, step_number=1, title="Register on scholarship portal",
                            description="Create/login to student account on the scholarship portal.",
                            required_document_ids=[], is_start=True),
        models.ProcessStep(version_id=sch_new_version.id, step_number=2, title="Fill application & upload documents",
                            description="Fill personal, academic, and bank details; upload all mandatory documents.",
                            required_document_ids=mandatory_ids),
        models.ProcessStep(version_id=sch_new_version.id, step_number=3, title="Institution verification",
                            description="Educational institution verifies enrollment and academic details.",
                            required_document_ids=[]),
        models.ProcessStep(version_id=sch_new_version.id, step_number=4, title="Department approval & disbursal",
                            description="Welfare department approves the application; amount is disbursed via DBT.",
                            required_document_ids=[], is_end=True),
    ])
    db.commit()

    # =====================================================================
    # SCHEME 3: Old-Age Pension (for scheme-vs-scheme comparison demo)
    # =====================================================================
    pension = models.Scheme(
        name="Old-Age Pension Scheme",
        slug="old-age-pension",
        category="pension",
        department_id=welfare_dept.id,
        short_description="Monthly financial assistance for senior citizens from economically weaker sections.",
    )
    db.add(pension)
    db.commit()

    pension_circular = models.Circular(
        doc_number="GO Ms No. 76",
        title="Old-Age Pension Scheme guidelines",
        issued_date=datetime(2024, 1, 5),
        effective_date=datetime(2024, 1, 15),
        department_id=welfare_dept.id,
        raw_text="Citizens aged 60 years and above with annual family income below Rs. 1,50,000 are eligible for monthly pension of Rs. 3,000.",
        extraction_confidence=1.0,
    )
    db.add(pension_circular)
    db.commit()

    pension_version = models.SchemeVersion(
        scheme_id=pension.id, circular_id=pension_circular.id, is_current=True,
        income_limit_annual=150000, age_min=60, age_max=None, benefit_amount=3000, processing_time_days=20,
    )
    db.add(pension_version)
    db.commit()

    db.add_all([
        models.EligibilityRule(version_id=pension_version.id, field_name="age", operator=">=", value=60,
                                explanation="Applicant must be 60 years of age or older"),
        models.EligibilityRule(version_id=pension_version.id, field_name="annual_income", operator="<=", value=150000,
                                explanation="Annual family income must not exceed Rs. 1,50,000"),
    ])
    db.commit()

    pension_docs = [
        models.Document(version_id=pension_version.id, name="Aadhaar Card", mandatory=True, copies_required=1),
        models.Document(version_id=pension_version.id, name="Age proof", mandatory=True, copies_required=1),
        models.Document(version_id=pension_version.id, name="Income Certificate (valid, current)", mandatory=True, copies_required=1),
        models.Document(version_id=pension_version.id, name="Bank passbook copy", mandatory=True, copies_required=1),
    ]
    db.add_all(pension_docs)
    db.commit()

    db.add_all([
        models.ProcessStep(version_id=pension_version.id, step_number=1, title="Submit application at Panchayat/Ward office",
                            description="Submit filled application with documents at the local Panchayat/Ward office.",
                            required_document_ids=[d.id for d in pension_docs], is_start=True),
        models.ProcessStep(version_id=pension_version.id, step_number=2, title="Verification",
                            description="Local officer verifies age and income eligibility.",
                            required_document_ids=[]),
        models.ProcessStep(version_id=pension_version.id, step_number=3, title="Sanction & monthly disbursal",
                            description="Pension sanctioned and credited monthly via DBT.",
                            required_document_ids=[], is_end=True),
    ])
    db.commit()

    db.close()

    # Generate embeddings for semantic (RAG) search over circular text.
    # Safe to skip - store_embedding() no-ops if no LLM key is configured.
    from .config import LLM_ENABLED
    if LLM_ENABLED:
        from .services import embeddings
        db2 = SessionLocal()
        all_circulars = db2.query(models.Circular).all()
        print(f"Generating embeddings for {len(all_circulars)} circulars (RAG search)...")
        for c in all_circulars:
            embeddings.store_embedding(db2, c)
        db2.close()
        print("✅ Embeddings generated.")
    else:
        print("ℹ️  No GOOGLE_API_KEY configured - skipping embeddings (semantic search will fall back to keyword search).")

    print("✅ Seed data loaded: 3 schemes, 5 circulars, versioned income-certificate scenario ready.")


if __name__ == "__main__":
    run()