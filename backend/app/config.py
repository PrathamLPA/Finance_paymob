"""Application configuration from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.url import resolve_supabase_url

# backend/app/config.py → repo root (Finance Project LPA)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(_REPO_ROOT / ".env"),
            str(_BACKEND_ROOT / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Finance Automation"
    app_env: str = "development"
    # Set automatically by Railway; lets logs prove which commit is running.
    railway_git_commit_sha: str = ""
    log_level: str = "INFO"
    # Public URL of this API service (webhooks, Paymob notification_url)
    public_base_url: str = "http://localhost:8001"
    # Customer payment pages (Railway frontend service)
    payment_frontend_base_url: str = "http://localhost:3000"
    # Allowed browser origin for CORS (frontend)
    frontend_origin: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://finance:finance@localhost:5432/finance_automation"

    # Default off so missing Railway env never silently uses mocks.
    # Local/tests: set USE_MOCK_INTEGRATIONS=true (see .env.example / conftest).
    use_mock_integrations: bool = False

    # Bitrix24
    bitrix24_webhook_url: str = ""
    bitrix_webhook_secret: str = ""
    # Bitrix "Track inbound webhook" URL. Must contain {{ID}} for the lead id.
    # Called only after the first invoice is published and emailed successfully.
    bitrix_invoice_sent_trigger_url: str = ""
    bitrix_lead_payment_stage_id: str = "LEAD_PAYMENT"
    bitrix_finance_generate_link_stage_id: str = "FINANCE_GENERATE_LINK"
    # Bitrix deal CATEGORY_ID for "Sales" (the convert-to-deal picker)
    bitrix_sales_pipeline_id: str = "16"
    bitrix_finance_pipeline_id: str = ""
    # B2C Ops pipeline Category ID — one Ops card per Sales course unit after convert.
    bitrix_b2c_pipeline_id: str = ""
    # true = backend converts Lead→Sales after first payment.
    # false = leave convert to Bitrix "Create using source" / Deal Won robots;
    #         backend still autofills Complete-lead and fires the invoice-sent trigger.
    bitrix_backend_convert_lead_to_sales: bool = True
    # true = after Sales deal exists, create one B2C Ops card per course unit.
    # Requires bitrix_b2c_pipeline_id. false = skip (Bitrix tunnel/copy can own B2C).
    bitrix_backend_b2c_ops_split: bool = True
    # Department used to resolve B2C Ops assignees (exact Bitrix department NAME).
    bitrix_b2c_ops_department_name: str = "B2C - Student Support"
    # Bitrix department ID(s) for Ops assignees (comma-separated).
    # SPOCs currently live under 286; UI label "B2C - Student Support" is 108.
    # Include both until all SPOCs are only in 108.
    bitrix_b2c_ops_department_id: str = "108,286"
    # When true, new B2C Ops cards are assigned round-robin to that department.
    # Ignored when bitrix_b2c_ops_assign_by_course_handling_dept is true.
    bitrix_b2c_ops_assign_from_department: bool = True
    # true = for each Ops card, pick from configured Ops dept users whose
    # Handiling Department (UF_USR_…) matches the course. Discovers SPOCs live
    # from Bitrix (no hardcoded names). Falls back to department RR if unset.
    bitrix_b2c_ops_assign_by_course_handling_dept: bool = True
    # Bitrix user field "Handiling Department" (enum on employee card).
    bitrix_field_user_handling_department: str = "UF_USR_1790154777183"
    # Enum ID for "Human Resources & People Development" (CIPD / Melona = 19722).
    bitrix_handling_dept_hr_people_development_enum: str = "19722"
    # crm.product — Product Type (Course / Lab / Study Material) + Associated course.
    # Used to group Sales products onto one B2C Ops card (replaces name-suffix logic).
    bitrix_product_property_type: str = "PROPERTY_400"
    bitrix_product_property_associated_course: str = "PROPERTY_414"
    bitrix_product_type_course_enum: str = "494"
    bitrix_product_type_lab_enum: str = "496"
    bitrix_product_type_study_material_enum: str = "498"
    # When true: also create Finance from the API (usually leave false).
    # Finance normally comes from Bitrix tunnel/copy.
    bitrix_create_extra_deals_on_payment: bool = False
    bitrix_field_invoice_reference: str = "UF_CRM_INVOICE_REFERENCE"
    bitrix_field_invoice_url: str = "UF_CRM_INVOICE_URL"
    bitrix_field_amount_paid: str = "UF_CRM_AMOUNT_PAID"
    bitrix_field_remaining_balance: str = "UF_CRM_REMAINING_BALANCE"
    # Deal payment-summary total (may differ from lead Payment Section total)
    bitrix_field_total_amount: str = "UF_CRM_TOTAL_AMOUNT"
    # Lead Payment Section / Complete-lead "Total Amount_" money field
    bitrix_field_lead_total_amount: str = "UF_CRM_1684374599490"
    # Deal Payment Info — different UF codes than lead (Bitrix entity-specific fields)
    bitrix_field_deal_total_amount: str = "UF_CRM_1684376291062"
    bitrix_field_deal_amount_paid: str = "UF_CRM_1648473806515"
    bitrix_field_deal_remaining_balance: str = "UF_CRM_1649495611849"
    bitrix_field_deal_installment_count: str = "UF_CRM_6465989F6E0EB"
    bitrix_field_deal_installment_1: str = "UF_CRM_1684376313437"
    bitrix_field_deal_installment_2: str = "UF_CRM_1684376450460"
    bitrix_field_deal_installment_3: str = "UF_CRM_1684379232"
    bitrix_field_deal_installment_4: str = "UF_CRM_1684376820955"
    bitrix_field_deal_installment_1_date: str = "UF_CRM_1684376335077"
    bitrix_field_deal_installment_2_due_date: str = "UF_CRM_1684376591204"
    bitrix_field_deal_installment_3_due_date: str = "UF_CRM_1684376475940"
    bitrix_field_deal_installment_4_due_date: str = "UF_CRM_1684376877789"
    bitrix_field_deal_payment_1_mode: str = "UF_CRM_1684376413205"
    bitrix_field_deal_payment_2_mode: str = "UF_CRM_1684376704268"
    bitrix_field_deal_payment_3_mode: str = "UF_CRM_1684376551228"
    bitrix_field_deal_payment_4_mode: str = "UF_CRM_1684376963627"
    bitrix_field_deal_payment_link: str = "UF_CRM_1783502165006"
    bitrix_field_deal_lead_id: str = "UF_CRM_1789218342102"
    # Deal Complete / Ops / identity fields (separate UF codes from lead)
    bitrix_field_deal_student_name: str = "UF_CRM_6997027A88DD2"
    bitrix_field_deal_student_mail: str = "UF_CRM_6AAD1A163697E"
    bitrix_field_deal_student_contact: str = "UF_CRM_6AAD1A168101E"
    bitrix_field_deal_enrollment_date: str = "UF_CRM_699706DDD23F9"
    bitrix_field_deal_ops_notes: str = "UF_CRM_6996F9E7155EE"
    bitrix_field_deal_comment: str = "UF_CRM_6465989D87575"
    bitrix_field_deal_schedule_finalized: str = "UF_CRM_6996F9D3B4024"
    bitrix_field_deal_trainer_shared: str = "UF_CRM_6996F9DD75A95"
    bitrix_field_deal_student_type: str = "UF_CRM_69A587F843B6B"
    bitrix_field_deal_batch_type: str = "UF_CRM_69A5880225A00"
    bitrix_field_deal_training_mode: str = "UF_CRM_6465989E12E11"
    bitrix_field_deal_course_duration: str = "UF_CRM_6992F5AE7DBBD"
    bitrix_field_deal_class_timing: str = "UF_CRM_6992F5B7D10ED"
    bitrix_field_deal_study_materials: str = "UF_CRM_699304CBA481B"
    bitrix_field_deal_certificates_promised: str = "UF_CRM_699304D4C53F6"
    bitrix_field_deal_company_website: str = "UF_CRM_6465C2AB0E1CC"
    bitrix_field_deal_designation: str = "UF_CRM_664F1583D7579"
    bitrix_field_deal_industry_domain: str = "UF_CRM_6846B9D4E1528"
    bitrix_field_deal_department_training: str = "UF_CRM_6846B9D5047AA"
    bitrix_field_deal_payment_proof: str = "UF_CRM_69D39E301706D"
    bitrix_field_deal_invoice_file: str = "UF_CRM_6AA53B07592D7"
    # Lead enum ID → Deal enum ID (same labels, different list IDs per entity)
    bitrix_deal_installment_count_enum_map: str = "5826:6002,5828:6004,5830:6006,5832:6008"
    bitrix_deal_payment_1_mode_enum_map: str = (
        "5774:5856,5776:5858,13178:13184,13156:13166,5778:5860,"
        "5780:5862,5782:5864,5784:5866,13234:13152,13146:13168"
    )
    bitrix_deal_payment_2_mode_enum_map: str = (
        "5786:5882,5788:5884,5790:5886,5792:5888,5794:5890,5796:5892"
    )
    bitrix_deal_payment_3_mode_enum_map: str = (
        "5798:5868,5800:5870,5802:5872,5804:5874,5806:5876,5808:5878,5810:5880"
    )
    bitrix_deal_payment_4_mode_enum_map: str = (
        "5812:5894,5814:5896,5816:5898,5818:5900,5820:5902,5822:5904,5824:5906"
    )
    bitrix_deal_paid_status_enum_map: str = "19692:19696,19700:19698"
    bitrix_deal_schedule_finalized_enum_map: str = "12910:12938,12912:12940"
    bitrix_deal_trainer_shared_enum_map: str = "12914:12942,12916:12944"
    bitrix_deal_student_type_enum_map: str = "13196:13212,13198:13214"
    bitrix_deal_batch_type_enum_map: str = "13200:13216,13202:13218"
    bitrix_deal_training_mode_enum_map: str = "5768:5996,5770:5998,5772:6000,14500:14506"
    bitrix_deal_department_training_enum_map: str = (
        "11754:11782,11756:11784,11758:11786,11760:11788,11762:11790,11764:11792,"
        "11920:11944,11922:11946,11924:11948,11926:11950,11928:11952,12724:12730,"
        "11930:11954,12732:12744,12734:12746"
    )
    bitrix_deal_industry_domain_enum_map: str = (
        "11752:11780,11824:11888,11826:11890,11828:11892,11830:11894,11832:11896,"
        "11834:11898,11836:11900,11838:11902,11840:11904,11842:11906,11844:11908,"
        "11846:11910,11848:11912,11850:11914,11852:11916,11854:11918"
    )
    bitrix_field_payment_link: str = "UF_CRM_PAYMENT_LINK"
    # Finance deal UF "Original Deal ID" → Sales deal id (Copy deal bridge)
    bitrix_field_original_deal_id: str = "UF_CRM_64461C4D5CF41"
    bitrix_field_customer_email: str = "UF_CRM_CUSTOMER_EMAIL"
    # Client "Email domains" UF — used only when Contact card has no email
    bitrix_field_client_email: str = "UF_CRM_1740610735352"
    bitrix_field_payment_percentage: str = "UF_CRM_PAYMENT_PERCENTAGE"
    bitrix_field_payment_status: str = "UF_CRM_PAYMENT_STATUS"
    bitrix_field_transaction_id: str = "UF_CRM_TRANSACTION_ID"
    # Stage to move finance deal to once required payment % is met
    bitrix_finance_threshold_met_stage_id: str = "FINANCE_THRESHOLD_MET"
    bitrix_field_customer_phone: str = "UF_CRM_CUSTOMER_PHONE"
    bitrix_field_customer_name: str = "UF_CRM_CUSTOMER_NAME"
    # Optional custom field holding the amount when OPPORTUNITY is empty
    bitrix_field_lead_amount: str = ""
    # Lead Payment Section — first payment link uses Installment 1 when set
    bitrix_field_installment_count: str = "UF_CRM_1684374566210"
    # Number Of Installments is a Bitrix list field — API returns enum IDs, not 1–4.
    bitrix_installment_count_enum_map: str = "5826:1,5828:2,5830:3,5832:4"
    # Payment Installment 1 amount (money). Do NOT use Payment 1 Mode here.
    bitrix_field_installment_1: str = "UF_CRM_1684373846380"
    bitrix_field_installment_2: str = "UF_CRM_1684380172"
    bitrix_field_installment_3: str = "UF_CRM_1684380201"
    bitrix_field_installment_4: str = "UF_CRM_1684380220"
    bitrix_field_installment_1_date: str = "UF_CRM_1684373986749"
    # TEMP: 2nd payment due date reads/writes Installment 3 Due Date until Ops remaps.
    bitrix_field_installment_2_due_date: str = "UF_CRM_1684374296635"
    bitrix_field_installment_3_due_date: str = "UF_CRM_1684374296635"
    bitrix_field_installment_4_due_date: str = "UF_CRM_1684374497754"
    # Previous Installment 2 Due Date — used to migrate values into the TEMP field above
    bitrix_field_installment_2_due_date_legacy: str = "UF_CRM_1684374142163"
    # Complete lead (CONVERTED) required-form fields — Learners Point portal
    bitrix_field_complete_schedule_finalized: str = "UF_CRM_1771500430277"
    bitrix_field_complete_paid_amount: str = "UF_CRM_1771500781458"
    bitrix_field_complete_trainer_shared: str = "UF_CRM_1771501047627"
    bitrix_field_complete_ops_notes: str = "UF_CRM_1771501226065"
    bitrix_field_complete_student_name: str = "UF_CRM_1771503330575"
    # Lead card student identity (Learners Point — filled from terms acceptance)
    bitrix_field_student_mail: str = "UF_CRM_1789714405705"
    bitrix_field_student_contact: str = "UF_CRM_1789714441645"
    # Lead enrollment type: Batch → catalog/inventory path; One-One → manager approval
    bitrix_field_enrollment_type: str = "UF_CRM_1789736997226"
    bitrix_enrollment_batch_enum_ids: str = "19702"
    bitrix_enrollment_one_one_enum_ids: str = "19704"
    bitrix_field_complete_enrollment_date: str = "UF_CRM_1771503410009"
    bitrix_field_complete_credit_card: str = "UF_CRM_1772016277089"
    bitrix_field_complete_tenure: str = "UF_CRM_1772019664771"
    bitrix_field_complete_student_type: str = "UF_CRM_1772454738552"
    bitrix_field_complete_batch_type: str = "UF_CRM_1772455024093"
    bitrix_field_complete_payment_proof: str = "UF_CRM_1775466638710"
    # Complete-lead "Paid Status" enumeration
    bitrix_field_complete_paid_status: str = "UF_CRM_1789557091401"
    bitrix_complete_paid_status_fully_paid_enum: str = "19692"
    bitrix_complete_paid_status_partially_paid_enum: str = "19700"
    # Deal-card "Paid Status" enumeration
    bitrix_field_deal_paid_status: str = "UF_CRM_1789629158792"
    bitrix_deal_paid_status_fully_paid_enum: str = "19696"
    bitrix_deal_paid_status_partially_paid_enum: str = "19698"
    # Finance deal "Proof of Next payment" — installment 2+ invoice PDF
    bitrix_field_next_payment_proof: str = "UF_CRM_1789378609379"
    # Lead card "Invoice" multi-file UF (tile uploader under Payment Section)
    bitrix_field_lead_invoice_file: str = "UF_CRM_1789204266156"
    # Complete-lead / lead-card ops & training fields (from Learners Point form data-cid)
    bitrix_field_complete_comment_uf: str = "UF_CRM_1684372587728"
    bitrix_field_training_mode: str = "UF_CRM_1684372786609"
    bitrix_field_company_website: str = "UF_CRM_1684388099787"
    bitrix_field_designation: str = "UF_CRM_1716456659309"
    bitrix_field_industry_domain: str = "UF_CRM_1749464475095"
    bitrix_field_department_training: str = "UF_CRM_1749464873149"
    bitrix_field_course_duration: str = "UF_CRM_1771238558828"
    bitrix_field_training_start_date: str = "UF_CRM_1771238612202"
    bitrix_field_class_timing: str = "UF_CRM_1771238691110"
    bitrix_field_study_materials: str = "UF_CRM_1771240157159"
    bitrix_field_certificates_promised: str = "UF_CRM_1771240323579"
    bitrix_field_mode_of_training: str = "UF_CRM_1771499914629"
    # Extra Complete-lead required string UFs filled with placeholder when empty.
    bitrix_complete_required_string_fields: str = (
        "UF_CRM_1684372587728,UF_CRM_1684388099787,UF_CRM_1716456659309,"
        "UF_CRM_1771238558828,UF_CRM_1771238691110,UF_CRM_1771240157159,"
        "UF_CRM_1771240323579"
    )
    bitrix_complete_required_placeholder: str = "To be confirmed by Ops"
    # Extra Complete-lead required select UFs — only filled when empty and a default enum is set.
    bitrix_complete_required_select_fields: str = (
        "UF_CRM_1684372786609,UF_CRM_1749464475095,UF_CRM_1749464873149,UF_CRM_1771499914629"
    )
    # Optional default enum IDs for those selects (leave empty to skip inventing values)
    bitrix_complete_training_mode_enum: str = ""
    bitrix_complete_industry_domain_enum: str = ""
    bitrix_complete_department_enum: str = ""
    bitrix_complete_mode_of_training_enum: str = ""
    # Enum defaults when auto-filling Complete lead (Yes/No / B2C / Public Batch)
    bitrix_complete_schedule_finalized_enum: str = "12912"  # No
    bitrix_complete_trainer_shared_enum: str = "12916"  # No
    bitrix_complete_student_type_enum: str = "13198"  # B2C
    bitrix_complete_batch_type_enum: str = "13200"  # Public Batch
    bitrix_complete_lead_autofill_enabled: bool = True
    bitrix_complete_copy_products_to_deal: bool = True
    # Payment mode fields (enumeration — not amounts)
    bitrix_field_payment_1_mode: str = "UF_CRM_1684373954405"
    bitrix_field_payment_2_mode: str = "UF_CRM_1684374103659"
    bitrix_field_payment_3_mode: str = "UF_CRM_1684374256836"
    bitrix_field_payment_4_mode: str = "UF_CRM_1684374451274"
    # Payment mode list enum IDs → labels (Cash / Online / …)
    # Learners Point live enums (from crm.lead.userfield.list / payment mode field).
    bitrix_payment_mode_enum_map: str = (
        "5774:cash,5786:cash,"
        "5776:website_payment,13234:website_payment,"
        "13156:card,5788:online,"
        "5778:bank_transfer,5790:bank_transfer,"
        "5782:tabby,5784:tamara,"
        "5780:purchase_order,13146:others,"
        "13178:bank_installment"
    )
    # Comma-separated Bitrix enum IDs treated as Cash (skip Paymob, enqueue cash desk)
    # 5774 is the Cash ID currently returned by Learners Point Bitrix for Payment 1 Mode.
    cash_mode_enum_ids: str = "5774,5786"
    # Comma-separated Bitrix enum IDs treated as Bank Transfer (payment link + receipt upload)
    bank_transfer_mode_enum_ids: str = "5778,5790"
    # Shown on the candidate receipt-upload page after Terms
    bank_transfer_instructions: str = (
        "Please transfer the amount to the Learners Point bank account, "
        "then upload a clear photo or PDF of the transfer receipt."
    )
    # Cash Desk staff JWT + bootstrap manager
    staff_jwt_secret: str = ""
    staff_jwt_ttl_hours: int = 12
    staff_bootstrap_manager_email: str = ""
    staff_bootstrap_manager_password: str = ""
    staff_bootstrap_manager_name: str = "Cash Desk Manager"
    # Cash Desk Next.js origin (CORS) — comma-separated with frontend_origin if needed
    cashdesk_origin: str = "http://localhost:3001"
    # When true: payment link is only sent after catalog price check + Estimate create
    bitrix_price_gate_enabled: bool = True
    # Catalog price type used as the floor (not retail/BASE). Match xmlId and/or name.
    bitrix_catalog_min_price_type_xml_ids: str = "MIN_PRICE"
    bitrix_catalog_min_price_type_names: str = (
        "MIN_PRICE,Minimum,Min price,Minimum price,Min. price"
    )
    # Sender address for Bitrix mail.message.send (must exist in mail.mailbox.senders)
    bitrix_mail_from: str = ""
    # Used when the lead owner has no department manager email
    bitrix_approval_fallback_email: str = ""
    # How long a manager approval link stays valid
    price_approval_ttl_hours: int = 72
    # Temporary diagnostics: logs fetched lead/deal fields (may contain customer PII).
    log_bitrix_payloads: bool = False

    # Paymob
    # Temporary diagnostics: dumps the transaction object when HMAC verification fails.
    log_paymob_payloads: bool = False
    # Temporary: if HMAC fails (UAE Intention body hmac undocumented), confirm via
    # Paymob Transaction Inquiry using the API key. Turn off once Paymob documents
    # the Intention HMAC formula and verification matches again.
    paymob_hmac_fallback_to_inquiry: bool = True
    paymob_api_key: str = ""
    paymob_secret_key: str = ""
    paymob_public_key: str = ""
    # Default / card integration (Learners Point UAE Paymob)
    paymob_integration_id: int = 49586
    paymob_integration_id_card: int = 49586
    paymob_integration_id_tabby: int = 52169
    paymob_integration_id_tamara: int = 52266
    paymob_hmac_secret: str = ""
    paymob_base_url: str = "https://accept.paymob.com"
    paymob_checkout_base_url: str = "https://accept.paymob.com/unifiedcheckout/"

    # Tabby direct API (UAE). Used when Bitrix Payment Mode is Tabby (not via Paymob).
    # Docs: https://docs.tabby.ai/pay-in-4-custom-integration/quick-start
    tabby_secret_key: str = ""
    tabby_public_key: str = ""
    tabby_merchant_code: str = ""
    tabby_base_url: str = "https://api.tabby.ai"
    # Custom header registered with Tabby webhooks (title + shared secret value).
    tabby_webhook_auth_header: str = "X-Tabby-Auth"
    tabby_webhook_auth_value: str = ""

    # Tamara direct API (UAE). Used when Bitrix Payment Mode is Tamara (not via Paymob).
    # Docs: https://docs.tamara.co/docs/direct-online-checkout
    tamara_api_token: str = ""
    tamara_notification_token: str = ""
    tamara_public_key: str = ""
    # Live by default; set api-sandbox.tamara.co only for staging/sandbox keys.
    tamara_base_url: str = "https://api.tamara.co"
    tamara_country_code: str = "AE"
    tamara_payment_type: str = "PAY_BY_INSTALMENTS"
    tamara_instalments: int = 3

    # Zoho Books (https://www.zoho.com/books/api/v3/oauth/)
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_organization_id: str = ""
    # Data center: .com / .ae / .eu / .in — must match the Zoho Books org region
    zoho_accounts_url: str = "https://accounts.zoho.com"
    zoho_books_api_url: str = "https://www.zohoapis.com/books/v3"
    # Must match the redirect URI registered on the Zoho API Console client
    zoho_oauth_redirect_uri: str = ""
    zoho_oauth_scopes: str = (
        "ZohoBooks.contacts.CREATE,ZohoBooks.contacts.READ,"
        "ZohoBooks.invoices.CREATE,ZohoBooks.invoices.READ,ZohoBooks.invoices.UPDATE,"
        "ZohoBooks.customerpayments.CREATE,ZohoBooks.settings.READ"
    )
    # Optional catalog item; if empty, invoices use ad-hoc line items
    zoho_default_item_id: str = ""
    # Bitrix/workflow totals are final payable (VAT already in the price). Zoho must
    # treat line rates as tax-inclusive or it adds another 5% (e.g. 4.20 → 4.41).
    zoho_invoice_is_inclusive_tax: bool = True
    # Optional UAE VAT (etc.) tax_id from Zoho Settings → Taxes. When set, applied
    # on each line with inclusive rates so the PDF still shows VAT breakdown.
    zoho_default_tax_id: str = ""

    # Email
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "finance@example.com"
    sendgrid_from_name: str = "Finance Team"

    # Workflow
    terms_version: str = "1.0"
    refund_policy_url: str = (
        "https://financepaymob-frontend-production.up.railway.app/terms-and-conditions"
    )
    # After a successful "for myself" payment, thank-you page links here
    lms_login_url: str = (
        "https://learn.learnerspoint.org/auth/login"
        "?redirect=https%3A%2F%2Flearn.learnerspoint.org%2Fmy-classroom"
    )
    payment_session_ttl_hours: int = 72
    default_currency: str = "AED"
    storage_path: str = "storage"
    # Minimum paid % of total before customer may proceed (e.g. 50)
    payment_required_percent: float = 50.0
    # Automated payment reminders
    reminder_enabled: bool = True
    reminder_interval_hours: int = 24
    reminder_scheduler_enabled: bool = True
    reminder_scheduler_poll_seconds: int = 300
    # Poller-based installment due emails. Prefer Bitrix BP Outbound webhook
    # → POST /webhooks/bitrix24/installment-due instead of scanning every N minutes.
    installment_due_notices_enabled: bool = False

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def resolve_supabase_database_url(self) -> "Settings":
        self.database_url = resolve_supabase_url(self.database_url)
        return self

    @model_validator(mode="after")
    def enforce_production_integration_safety(self) -> "Settings":
        """Never silently mock gateways in production, even if env is mis-set."""
        env = (self.app_env or "").strip().lower()
        if env in {"production", "prod"} and self.use_mock_integrations:
            import logging

            logging.getLogger(__name__).warning(
                "APP_ENV=%s but USE_MOCK_INTEGRATIONS=true — forcing mocks off",
                self.app_env,
            )
            self.use_mock_integrations = False
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
