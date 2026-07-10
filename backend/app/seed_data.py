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
        target_categories=["general"],
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
        target_categories=["student", "sc", "st", "obc", "ews"],
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
        target_categories=["senior_citizen"],
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

    # Expanded catalog: 10 additional schemes across citizen categories
    # (ex-servicemen, disability, farmers, sportspersons, widows, women
    # entrepreneurs, construction workers, unemployed youth, tribal
    # students, senior citizen healthcare). See _add_expanded_schemes()
    # below - illustrative/demo data, not sourced from live gazette text.
    _add_expanded_schemes(db)

    db.close()

    # Generate embeddings for semantic (RAG) search over circular text.
    # Safe to skip - store_embedding() no-ops if Ollama isn't reachable.
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
        print("ℹ️  Ollama not configured/reachable - skipping embeddings (semantic search will fall back to keyword search).")

    print("✅ Seed data loaded: 13 schemes across multiple citizen categories, versioned income-certificate scenario ready.")


def _add_scheme(db, *, name, slug, dept, description, target_categories,
                 go_no, go_title, issued, effective, raw_text, category="scheme",
                 income_limit=None, age_min=None, age_max=None, benefit=None,
                 processing_days=15, eligibility_rules=None, documents=None, steps=None):
    """Compact helper for adding a single-version scheme (no prior version) -
    used for the expanded catalog below to avoid repeating the full
    Scheme/Circular/SchemeVersion boilerplate 10 times over."""
    scheme = models.Scheme(name=name, slug=slug, category=category, department_id=dept.id,
                            short_description=description, target_categories=target_categories)
    db.add(scheme)
    db.commit()

    circular = models.Circular(doc_number=go_no, title=go_title, issued_date=issued,
                                effective_date=effective, department_id=dept.id,
                                raw_text=raw_text, extraction_confidence=1.0)
    db.add(circular)
    db.commit()

    version = models.SchemeVersion(scheme_id=scheme.id, circular_id=circular.id, is_current=True,
                                    income_limit_annual=income_limit, age_min=age_min, age_max=age_max,
                                    benefit_amount=benefit, processing_time_days=processing_days)
    db.add(version)
    db.commit()

    for field_name, op, val, explanation in (eligibility_rules or []):
        db.add(models.EligibilityRule(version_id=version.id, field_name=field_name, operator=op,
                                       value=val, explanation=explanation))
    db.commit()

    doc_objs = []
    for dname, mandatory, copies, notes in (documents or []):
        doc_objs.append(models.Document(version_id=version.id, name=dname, mandatory=mandatory,
                                         copies_required=copies, notes=notes))
    db.add_all(doc_objs)
    db.commit()

    doc_ids_by_name = {d.name: d.id for d in doc_objs}
    step_objs = []
    for i, (title, desc, doc_names, is_start, is_end) in enumerate(steps or [], start=1):
        step_objs.append(models.ProcessStep(
            version_id=version.id, step_number=i, title=title, description=desc,
            required_document_ids=[doc_ids_by_name[n] for n in doc_names if n in doc_ids_by_name],
            is_start=is_start, is_end=is_end,
        ))
    db.add_all(step_objs)
    db.commit()
    return scheme, version


def _add_expanded_schemes(db):
    """
    10 additional schemes across citizen categories not covered by the
    original 3. This is ILLUSTRATIVE/DEMO DATA modeled on the general
    structure of real Indian central/state welfare schemes (eligibility
    shape, document types, process flow) - it is not sourced from live
    gazette notifications and should not be presented as current official
    policy. Marked here explicitly per the requirement to keep sample data
    clearly distinguishable from verified ingested circulars.
    """
    ex_servicemen_dept = models.Department(name="Ex-Servicemen Welfare Department",
                                            description="Welfare of retired defence personnel")
    agriculture_dept = models.Department(name="Agriculture Department", description="Farmer welfare and subsidies")
    labour_dept = models.Department(name="Labour Department", description="Worker welfare and social security")
    sports_dept = models.Department(name="Sports Authority", description="Sports promotion and athlete welfare")
    msme_dept = models.Department(name="MSME & Industries Department", description="Entrepreneurship and small business support")
    db.add_all([ex_servicemen_dept, agriculture_dept, labour_dept, sports_dept, msme_dept])
    db.commit()

    # Reuse existing departments where they fit (welfare_dept, revenue_dept
    # are created earlier in run() and still queryable here).
    welfare_dept = db.query(models.Department).filter(models.Department.name == "Social Welfare Department").first()

    # 1. Ex-Servicemen Pension & Resettlement Scheme
    _add_scheme(
        db, name="Ex-Servicemen Pension & Resettlement Scheme", slug="ex-servicemen-pension",
        dept=ex_servicemen_dept, category="pension",
        description="Monthly pension and resettlement assistance for retired defence personnel and their dependents.",
        target_categories=["ex_serviceman"],
        go_no="GO Ms No. 201", go_title="Ex-Servicemen Pension and Resettlement Scheme guidelines",
        issued=datetime(2024, 8, 1), effective=datetime(2024, 8, 15),
        raw_text="Retired defence personnel (Army, Navy, Air Force) who have completed qualifying service are "
                 "eligible for monthly pension and one-time resettlement assistance of Rs. 50,000.",
        benefit=50000, processing_days=30,
        eligibility_rules=[
            ("citizen_categories", "contains", "ex_serviceman", "Applicant must be a retired defence services (Army/Navy/Air Force) personnel"),
        ],
        documents=[
            ("Discharge Book / Service Certificate", True, 1, "Issued by the respective defence service"),
            ("Aadhaar Card", True, 1, None),
            ("Bank passbook copy", True, 1, "For direct benefit transfer"),
            ("PPO (Pension Payment Order), if previously sanctioned", False, 1, None),
        ],
        steps=[
            ("Submit application at Sainik Welfare Office", "Submit application with discharge documents at the District Sainik Welfare Office.",
             ["Discharge Book / Service Certificate", "Aadhaar Card"], True, False),
            ("Verification", "Records verified against service history.", [], False, False),
            ("Sanction & disbursal", "Pension sanctioned; resettlement assistance credited via DBT.", [], False, True),
        ],
    )

    # 2. Disability Pension & Assistive Devices Scheme
    _add_scheme(
        db, name="Disability Pension & Assistive Devices Scheme", slug="disability-pension",
        dept=welfare_dept, category="pension",
        description="Monthly pension and free assistive devices for persons with 40% or higher disability.",
        target_categories=["disability"],
        go_no="GO Ms No. 88", go_title="Disability Pension and Assistive Devices Scheme guidelines",
        issued=datetime(2023, 11, 10), effective=datetime(2023, 12, 1),
        raw_text="Persons with 40% or higher disability, certified by a competent medical authority, are eligible "
                 "for monthly pension of Rs. 3,500 and free assistive devices as assessed necessary.",
        benefit=3500, processing_days=25,
        eligibility_rules=[
            ("disability_percentage", ">=", 40, "Disability must be certified at 40% or higher"),
        ],
        documents=[
            ("Disability Certificate (UDID or equivalent)", True, 1, "Must state percentage and type of disability"),
            ("Aadhaar Card", True, 1, None),
            ("Bank passbook copy", True, 1, None),
            ("Medical assessment report for assistive device (if applicable)", False, 1, None),
        ],
        steps=[
            ("Submit application with disability certificate", "Submit at the District Disability Welfare Office.",
             ["Disability Certificate (UDID or equivalent)", "Aadhaar Card"], True, False),
            ("Medical board verification", "Assessed by the district medical board where required.", [], False, False),
            ("Sanction & disbursal", "Pension sanctioned; assistive devices issued if assessed necessary.", [], False, True),
        ],
    )

    # 3. National Sportsperson Cash Award Scheme
    _add_scheme(
        db, name="National Sportsperson Cash Award Scheme", slug="sportsperson-cash-award",
        dept=sports_dept, category="award",
        description="One-time cash award and training support for sportspersons who have represented the state/country at national or international level.",
        target_categories=["sportsperson", "student"],
        go_no="GO Ms No. 55", go_title="Sportsperson Cash Award and Training Support Scheme guidelines",
        issued=datetime(2024, 2, 20), effective=datetime(2024, 3, 1),
        raw_text="Sportspersons who have represented the state at national-level competitions, or the country at "
                 "international-level competitions, in a recognized sport are eligible for a one-time cash award "
                 "of Rs. 1,00,000 and continued training support.",
        benefit=100000, processing_days=45,
        eligibility_rules=[
            ("citizen_categories", "contains", "sportsperson", "Applicant must be a sportsperson who has represented at national or international level"),
        ],
        documents=[
            ("Certificate of participation/achievement from the recognized sports federation", True, 1, None),
            ("Aadhaar Card", True, 1, None),
            ("Bank passbook copy", True, 1, None),
        ],
        steps=[
            ("Submit application with achievement certificate", "Submit at the Sports Authority regional office.",
             ["Certificate of participation/achievement from the recognized sports federation", "Aadhaar Card"], True, False),
            ("Federation verification", "Achievement verified with the concerned sports federation.", [], False, False),
            ("Award sanction & disbursal", "Cash award sanctioned and credited via DBT.", [], False, True),
        ],
    )

    # 4. Farmer Crop Insurance Scheme
    _add_scheme(
        db, name="Farmer Crop Insurance Scheme", slug="farmer-crop-insurance",
        dept=agriculture_dept, category="insurance",
        description="Crop insurance covering losses due to natural calamities, pests, and diseases, for farmers cultivating notified crops.",
        target_categories=["farmer"],
        go_no="GO Ms No. 34", go_title="Farmer Crop Insurance Scheme guidelines",
        issued=datetime(2024, 5, 1), effective=datetime(2024, 6, 1),
        raw_text="Farmers, including tenant farmers and sharecroppers, cultivating notified crops in the notified "
                 "area are eligible for crop insurance. Premium is subsidized; claim amount is assessed based on "
                 "yield loss due to natural calamity, pest attack, or disease.",
        processing_days=60,
        eligibility_rules=[
            ("citizen_categories", "contains", "farmer", "Applicant must be a farmer (owner, tenant farmer, or sharecropper) cultivating a notified crop"),
        ],
        documents=[
            ("Land record / tenancy proof", True, 1, "Recent Record of Rights (RoR) or valid tenancy agreement"),
            ("Aadhaar Card", True, 1, None),
            ("Bank passbook copy", True, 1, "For premium debit and claim credit"),
            ("Sowing certificate", True, 1, "Confirms crop and area sown for the season"),
        ],
        steps=[
            ("Enroll before the cut-off date", "Enroll with land and sowing details before the seasonal cut-off date at the local bank/CSC.",
             ["Land record / tenancy proof", "Sowing certificate"], True, False),
            ("Loss assessment (if applicable)", "In case of crop loss, report to the local agriculture office for joint assessment.", [], False, False),
            ("Claim settlement", "Assessed claim amount credited directly to the farmer's bank account.", [], False, True),
        ],
    )

    # 5. Widow Pension Scheme
    _add_scheme(
        db, name="Widow Pension Scheme", slug="widow-pension",
        dept=welfare_dept, category="pension",
        description="Monthly financial assistance for widows from economically weaker sections.",
        target_categories=["widow", "woman"],
        go_no="GO Ms No. 62", go_title="Widow Pension Scheme guidelines",
        issued=datetime(2023, 9, 5), effective=datetime(2023, 10, 1),
        raw_text="Widows aged 18 years and above, with annual family income not exceeding Rs. 1,50,000, are "
                 "eligible for monthly pension of Rs. 2,500.",
        income_limit=150000, age_min=18, benefit=2500, processing_days=20,
        eligibility_rules=[
            ("citizen_categories", "contains", "widow", "Applicant must be a widow"),
            ("annual_income", "<=", 150000, "Annual family income must not exceed Rs. 1,50,000"),
        ],
        documents=[
            ("Husband's Death Certificate", True, 1, None),
            ("Aadhaar Card", True, 1, None),
            ("Income Certificate (valid, current)", True, 1, None),
            ("Bank passbook copy", True, 1, None),
        ],
        steps=[
            ("Submit application at Panchayat/Ward office", "Submit with death certificate and income proof.",
             ["Husband's Death Certificate", "Income Certificate (valid, current)"], True, False),
            ("Verification", "Local officer verifies marital status and income.", [], False, False),
            ("Sanction & monthly disbursal", "Pension sanctioned and credited monthly via DBT.", [], False, True),
        ],
    )

    # 6. Women Entrepreneur Startup Loan Scheme
    _add_scheme(
        db, name="Women Entrepreneur Startup Loan Scheme", slug="women-entrepreneur-loan",
        dept=msme_dept, category="loan",
        description="Collateral-free startup loans and subsidy support for women starting a micro or small enterprise.",
        target_categories=["woman", "entrepreneur"],
        go_no="GO Ms No. 77", go_title="Women Entrepreneur Startup Loan Scheme guidelines",
        issued=datetime(2024, 4, 10), effective=datetime(2024, 5, 1),
        raw_text="Women aged 21 to 55 years proposing to start a micro or small enterprise are eligible for a "
                 "collateral-free loan of up to Rs. 10,00,000 with 25% capital subsidy, subject to a viable "
                 "project report.",
        age_min=21, age_max=55, benefit=1000000, processing_days=40,
        eligibility_rules=[
            ("citizen_categories", "contains", "woman", "Applicant must be a woman"),
            ("age", ">=", 21, "Applicant must be at least 21 years old"),
            ("age", "<=", 55, "Applicant must not be older than 55 years"),
        ],
        documents=[
            ("Detailed Project Report (DPR)", True, 1, None),
            ("Aadhaar Card", True, 1, None),
            ("Bank passbook copy", True, 1, None),
            ("Educational/skill certificate relevant to the business", False, 1, None),
        ],
        steps=[
            ("Submit project report and application", "Submit DPR and application at the District Industries Centre.",
             ["Detailed Project Report (DPR)", "Aadhaar Card"], True, False),
            ("Project appraisal", "Bank/DIC appraises project viability.", [], False, False),
            ("Loan sanction & disbursal", "Loan sanctioned with subsidy adjusted; disbursed to the enterprise account.", [], False, True),
        ],
    )

    # 7. Construction Worker Welfare Scheme
    _add_scheme(
        db, name="Construction Worker Welfare Scheme", slug="construction-worker-welfare",
        dept=labour_dept, category="welfare",
        description="Accident insurance, medical assistance, and education support for registered construction workers and their families.",
        target_categories=["construction_worker", "laborer"],
        go_no="GO Ms No. 41", go_title="Construction Worker Welfare Scheme guidelines",
        issued=datetime(2023, 7, 1), effective=datetime(2023, 8, 1),
        raw_text="Construction workers registered with the Labour Welfare Board, with at least 90 days of work in "
                 "the preceding year, are eligible for accident insurance, medical assistance up to Rs. 25,000, "
                 "and education assistance for their children.",
        benefit=25000, processing_days=20,
        eligibility_rules=[
            ("citizen_categories", "contains", "construction_worker", "Applicant must be a registered construction worker"),
        ],
        documents=[
            ("Labour Welfare Board Registration Card", True, 1, None),
            ("Aadhaar Card", True, 1, None),
            ("Bank passbook copy", True, 1, None),
            ("Proof of 90 days' work (employer certificate)", True, 1, None),
        ],
        steps=[
            ("Register with the Labour Welfare Board (if not already)", "One-time registration at the local Labour office.",
             ["Aadhaar Card"], True, False),
            ("Apply for specific benefit", "Apply for accident/medical/education assistance as needed with supporting documents.",
             ["Labour Welfare Board Registration Card", "Proof of 90 days' work (employer certificate)"], False, False),
            ("Sanction & disbursal", "Benefit amount sanctioned and credited via DBT.", [], False, True),
        ],
    )

    # 8. Unemployed Youth Skill & Stipend Scheme
    _add_scheme(
        db, name="Unemployed Youth Skill & Stipend Scheme", slug="unemployed-youth-stipend",
        dept=labour_dept, category="stipend",
        description="Monthly stipend during skill training, and placement assistance, for unemployed youth.",
        target_categories=["unemployed", "student"],
        go_no="GO Ms No. 29", go_title="Unemployed Youth Skill and Stipend Scheme guidelines",
        issued=datetime(2024, 1, 15), effective=datetime(2024, 2, 1),
        raw_text="Unemployed youth aged 18 to 35 years, registered with the Employment Exchange, are eligible for "
                 "enrollment in a skill training program with a monthly stipend of Rs. 2,000 during training, and "
                 "placement assistance on completion.",
        age_min=18, age_max=35, benefit=2000, processing_days=15,
        eligibility_rules=[
            ("citizen_categories", "contains", "unemployed", "Applicant must be currently unemployed"),
            ("age", ">=", 18, "Applicant must be at least 18 years old"),
            ("age", "<=", 35, "Applicant must not be older than 35 years"),
        ],
        documents=[
            ("Employment Exchange Registration Card", True, 1, None),
            ("Aadhaar Card", True, 1, None),
            ("Educational certificates", True, 1, None),
            ("Bank passbook copy", True, 1, None),
        ],
        steps=[
            ("Register with Employment Exchange", "One-time registration, if not already registered.", ["Aadhaar Card"], True, False),
            ("Enroll in skill training program", "Choose and enroll in an available training track.",
             ["Employment Exchange Registration Card", "Educational certificates"], False, False),
            ("Complete training & placement assistance", "Stipend paid monthly during training; placement support on completion.", [], False, True),
        ],
    )

    # 9. Tribal Student Scholarship Scheme
    _add_scheme(
        db, name="Tribal Student Scholarship Scheme", slug="tribal-student-scholarship",
        dept=welfare_dept, category="scholarship",
        description="Scholarship and hostel assistance for students from Scheduled Tribe communities.",
        target_categories=["tribal", "st", "student"],
        go_no="GO Ms No. 19", go_title="Tribal Student Scholarship Scheme guidelines",
        issued=datetime(2023, 5, 1), effective=datetime(2023, 6, 1),
        raw_text="Students belonging to Scheduled Tribe communities, currently enrolled in a recognized "
                 "educational institution, with annual family income not exceeding Rs. 2,00,000, are eligible for "
                 "scholarship of Rs. 10,000 per annum plus hostel assistance where applicable.",
        income_limit=200000, benefit=10000, processing_days=30,
        eligibility_rules=[
            ("citizen_categories", "contains", "tribal", "Applicant must belong to a Scheduled Tribe community"),
            ("annual_income", "<=", 200000, "Annual family income must not exceed Rs. 2,00,000"),
            ("currently_enrolled", "==", True, "Applicant must be currently enrolled in a recognized educational institution"),
        ],
        documents=[
            ("Tribal/ST Certificate", True, 1, None),
            ("Income Certificate (valid, current)", True, 1, None),
            ("Bonafide certificate from institution", True, 1, None),
            ("Bank passbook copy", False, 1, "For direct benefit transfer"),
        ],
        steps=[
            ("Register on scholarship portal", "Create/login to student account on the scholarship portal.", [], True, False),
            ("Fill application & upload documents", "Upload all mandatory documents.",
             ["Tribal/ST Certificate", "Income Certificate (valid, current)", "Bonafide certificate from institution"], False, False),
            ("Institution verification", "Institution verifies enrollment.", [], False, False),
            ("Approval & disbursal", "Scholarship and hostel assistance disbursed via DBT.", [], False, True),
        ],
    )

    # 10. Senior Citizen Healthcare Assistance Scheme
    _add_scheme(
        db, name="Senior Citizen Healthcare Assistance Scheme", slug="senior-citizen-healthcare",
        dept=welfare_dept, category="healthcare",
        description="Free health check-ups and medical expense assistance for senior citizens, separate from the pension scheme.",
        target_categories=["senior_citizen"],
        go_no="GO Ms No. 95", go_title="Senior Citizen Healthcare Assistance Scheme guidelines",
        issued=datetime(2024, 3, 1), effective=datetime(2024, 4, 1),
        raw_text="Citizens aged 60 years and above are eligible for free annual health check-ups at government "
                 "hospitals and medical expense reimbursement of up to Rs. 20,000 per year for listed conditions.",
        age_min=60, benefit=20000, processing_days=15,
        eligibility_rules=[
            ("age", ">=", 60, "Applicant must be 60 years of age or older"),
        ],
        documents=[
            ("Aadhaar Card", True, 1, None),
            ("Age proof", True, 1, None),
            ("Medical bills/prescriptions (for reimbursement claims)", False, 1, None),
            ("Bank passbook copy", True, 1, None),
        ],
        steps=[
            ("Register at government hospital", "One-time registration for the free annual check-up program.",
             ["Aadhaar Card", "Age proof"], True, False),
            ("Avail check-up or file reimbursement claim", "Attend annual check-up, or submit medical bills for reimbursement.",
             ["Medical bills/prescriptions (for reimbursement claims)"], False, False),
            ("Reimbursement disbursal (if claimed)", "Approved reimbursement credited via DBT.", [], False, True),
        ],
    )


if __name__ == "__main__":
    run()