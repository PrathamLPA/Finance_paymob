# Finance Paymob Project Documentation

**Learners Point — Internal Technical and Operations Handbook**

Version 1.0  
Prepared: 17 September 2026  
Implementation baseline: Git revision `39c2462` on branch `v5`  
Classification: Internal use

---

## Document control

This handbook describes the implemented Finance Paymob platform, the Bitrix24
configuration it depends on, and the operating procedures required to support
payments. The codebase is the source of truth where this document and older
proposals differ.

The historical document `Bitrix-Led Payment Workflow Proposal.docx` was used as
background only. Its statement that the backend creates Sales, Finance, and B2C
deals is obsolete. In the current production flow, Bitrix automation owns lead
conversion and deal creation.

No API key, webhook credential, payment token, customer record, password, or
other secret is included in this document.

Regenerate the PDF after editing this source:

```text
python scripts/generate_project_documentation_pdf.py
```

## 1. Executive summary

Finance Paymob is an internal payment-orchestration platform connecting:

- Bitrix24 CRM for leads, deals, pipelines, automation, responsible people, and
  operational records.
- Paymob for online card and supported buy-now-pay-later checkout.
- Zoho Books for customer records, invoices, invoice PDFs, and payment ledger.
- SendGrid for transactional email.
- PostgreSQL, hosted through Supabase in production, for the authoritative
  workflow, session, acceptance, transaction, approval, and cash-desk records.
- A customer payment website for identity confirmation, terms acceptance,
  payment-method selection, and receipt upload.
- A Cash Desk application for employee cash/POS collection and manager review.

The backend records money and communicates with external systems. Bitrix owns
the visible CRM journey: conversion, Sales deal creation, Sales-to-Finance
copying/tunneling, and due-date automation.

The main operational principle is:

> Never infer payment success from a Bitrix stage. Payment success originates
> from Paymob verification, an approved bank transfer, or an authorized Cash
> Desk collection and is then written back to Bitrix.

<!-- DIAGRAM:architecture -->

## 2. Scope and audiences

### 2.1 Intended readers

- Sales and Account Management staff who create and maintain CRM records.
- Finance and Cash Desk employees who verify and collect payments.
- Bitrix administrators who maintain stages, triggers, tunnels, and workflows.
- Developers and operators who deploy, monitor, reconcile, and troubleshoot.
- Management reviewers who approve pricing or installment exceptions.

### 2.2 Included

- System architecture and ownership boundaries.
- Initial and subsequent payment journeys.
- Online, cash, POS, and bank-transfer processing.
- Price and installment approval.
- Zoho invoice and payment behavior.
- Bitrix entity mapping, custom fields, automation, and due-date workflows.
- Database, APIs, deployment, configuration, testing, troubleshooting, and
  production risks.

### 2.3 Excluded

- Actual secrets and customer information.
- Paymob or Zoho commercial agreements.
- Bitrix user permission administration outside the required scopes.
- LMS suspension/restoration, which remains a proposal and is not implemented
  in the reviewed source.

## 3. Terminology

- **Lead** — pre-sale CRM entity in Bitrix.
- **Sales deal** — deal created by Bitrix when the lead is converted.
- **Finance deal** — copied/tunneled deal used for payment operations.
- **B2C deal** — optional additional deal created by Bitrix automation.
- **Workflow** — one backend `CustomerWorkflow` associated with a Bitrix Lead ID.
- **Payment session** — expiring, tokenized request for a specific amount.
- **Transaction** — immutable payment result in the backend ledger.
- **Estimate** — Bitrix estimate created from lead product rows.
- **Threshold** — required paid percentage, 50% by default.
- **Track inbound webhook** — Bitrix automation trigger called by the backend
  after the first invoice is delivered.
- **Original Deal ID** — Finance custom field containing the Sales deal ID.
- **Installment notice** — request generated when a later installment becomes due.

## 4. System architecture

### 4.1 Deployable services

**Backend API — `backend/`**

- FastAPI application.
- SQLAlchemy ORM and Alembic migrations.
- Bitrix, Paymob, Zoho, SendGrid, cash, bank-transfer, and reminder services.
- Production entry point: `backend/start.sh`.
- Applies migrations before starting Uvicorn.

**Customer frontend — `frontend/`**

- FastAPI and Jinja server-rendered pages.
- Proxies all business operations to the backend API.
- Hosts payment, approval, receipt, policy, and thank-you pages.

**Cash Desk — `cashdesk/`**

- Next.js 14, TypeScript, Tailwind.
- Exported as static files and served below `/cashdesk` by the frontend image.
- Employee and manager views use authenticated backend staff APIs.

**Database**

- PostgreSQL in production.
- Supabase transaction-pooler compatibility is implemented by disabling
  prepared statements.
- SQLite is used by automated tests.

### 4.2 Integration responsibilities

**Bitrix24**

- CRM source records and products.
- Pipeline stages and responsible-user ownership.
- Lead conversion and deal creation.
- Finance workflow scheduling and operational automation.

**Paymob**

- Online checkout intention and hosted payment page.
- Signed callbacks and transaction inquiry fallback.
- Card, website-payment, Tabby, and Tamara integration selection.

**Zoho Books**

- Customer creation/reuse.
- One invoice per customer workflow.
- Customer-payment records applied to that invoice.
- Current invoice PDF retrieval.

**SendGrid**

- Payment links.
- Terms acceptance.
- Approval requests and decisions.
- Invoice delivery.
- Staff notifications.

## 5. Ownership boundary

### 5.1 Backend-owned actions

- Create and expire secure payment sessions.
- Freeze charge and installment information.
- Validate catalog price and installment policy.
- Route exceptions to manager approval.
- Capture terms acceptance and participant information.
- Verify Paymob callbacks and deduplicate transactions.
- Record cash/POS and approved bank-transfer transactions.
- Maintain cumulative paid and remaining amounts.
- Create/update Zoho invoice and attach invoice PDFs.
- Update Bitrix fields, timeline comments, and payment summaries.
- Trigger Bitrix after the first invoice.
- Resolve incoming Finance deals back to the originating workflow.

### 5.2 Bitrix-owned actions

- Start initial payment generation when a lead enters the payment stage.
- Convert the lead after the backend invoice trigger.
- Create the Sales deal.
- Copy or tunnel Sales to Finance and optional B2C pipelines.
- Copy products and required custom fields.
- Populate Original Deal ID on the Finance copy.
- Start Finance installment workflows.
- Pause until configured due date/time.
- Call the installment-due backend webhook.
- Send any CRM-native email or internal automation configured by Operations.

### 5.3 Explicit non-ownership

The active backend first-payment path does not call `crm.lead.convert` and does
not create production Sales, Finance, or B2C deals. Conversion helper methods
remain in the integration layer but are not used by the normal production flow.

## 6. End-to-end payment lifecycle

<!-- DIAGRAM:payment-flow -->

### 6.1 Lead preparation

Before moving a lead into Generate Payment Link:

1. Confirm customer email and phone.
2. Add one or more course product rows.
3. Enter the correct selling amount.
4. If using installments, enter installment count, amounts, and due dates.
5. Confirm installment amounts sum exactly to the total.
6. Confirm payment modes if a specific installment must be Cash or Bank Transfer.
7. Move the lead into the configured payment stage.

### 6.2 Initial webhook

Bitrix sends `POST /webhooks/bitrix24`. The backend:

1. Authenticates the callback when `BITRIX_WEBHOOK_SECRET` is configured.
2. Extracts `LEAD_n` or `DEAL_n` from the robot/event payload.
3. Refetches the live Bitrix entity instead of trusting partial webhook fields.
4. Verifies the current stage.
5. Creates or refreshes the backend workflow.
6. Loads product rows and evaluates price policy.
7. Evaluates installment policy.
8. Creates/reuses a payment session or routes an exception for approval.
9. Writes and sends the customer payment URL.

Repeated Bitrix updates reuse an active session and do not intentionally create
duplicate links.

### 6.3 Charge selection

For the initial link:

- If Installment 1 is positive, charge `min(Installment 1, remaining balance)`.
- If Installment 1 is empty or zero, charge the full remaining balance.
- Installment Count being blank does not override an explicit Installment 1.
- The selected amount is locked on the customer page.

For later links, the persisted installment schedule is authoritative after
payment has started.

### 6.4 Customer page — first payment

The first-payment page collects:

- Whether the course is for the payer or someone else.
- Payer name, email, and phone.
- Candidate details when required by course seat count.
- Payment method.
- Terms and refund-policy acceptance.

The accepted identity becomes the invoice identity and is stored in
`TermsAcceptance`.

### 6.5 Customer page — installment two and later

Later payment pages do not ask “For me / someone else” again. They show:

- Invoice name from the first accepted payment details.
- Selected course name.
- Email ID and phone from the first accepted payment details.
- Course total, amount already paid, outstanding balance, pay-now amount, and
  balance after payment.
- Current installment schedule.
- Payment-method choice.
- Current Terms and Conditions acceptance.

The backend also enforces reuse of the first accepted identity. Editing hidden
form values cannot replace the invoice identity.

### 6.6 Payment methods

**Card / Website payment / Tabby / Tamara**

- Backend creates or refreshes a Paymob intention.
- Customer is redirected to hosted Paymob checkout.
- Paymob posts a signed callback.
- Backend records success once using provider transaction ID.

**Cash**

- No online Paymob charge is created.
- Customer completes details and terms.
- Case appears in Cash Desk.
- Employee claims, uploads proof, and records collection.
- Cash increases employee cash on hand; POS does not.

**Bank transfer**

- Customer accepts terms and uploads JPG, PNG, WEBP, or PDF proof.
- Finance manager approves an amount up to the due amount or rejects for re-upload.
- Approval creates a synthetic bank-transfer transaction and runs the shared
  post-payment pipeline.

### 6.7 Shared successful-payment actions

After a verified payment:

1. Create an idempotent transaction.
2. Increase cumulative `amount_paid`.
3. Recalculate remaining balance and payment percentage.
4. Derive backend status: pending, partial, threshold met, or paid.
5. Stamp Installment 1 paid date when applicable.
6. Prepare Complete Lead fields.
7. Notify the assigned agent.
8. Create or update the Zoho invoice.
9. Attach invoice PDF and post timeline comments.
10. Email the updated invoice.
11. On first payment, call the Bitrix invoice-sent trigger.
12. Update known Sales, Finance, and B2C payment summaries.

## 7. Price and inventory approval

### 7.1 Catalog-linked course

The selling price is compared with the Bitrix catalog minimum using the final
VAT-inclusive unit amount. At or above minimum proceeds automatically. Below
minimum creates a manager approval.

### 7.2 Course missing from inventory/catalog

An unlisted or custom product row is no longer hard-blocked. It uses the same
approval process:

- Manager sees course name and sold amount.
- Approve accepts the sold amount and continues the existing payment-link flow.
- Reject allows the manager to enter a proposed amount and note.
- No payment link is sent on rejection.
- Bitrix timeline, responsible-user notification, and email state that the
  manager rejected and show the proposed amount.
- Custom rows with Bitrix `product_id=0` are identified by line number.

A completely empty product list remains blocked because there is no course or
sold amount to approve.

### 7.3 Installment policy approval

Manager approval is requested when:

- Installment 1 is below the required percentage.
- More than two installments are selected.
- Installment 2 is more than 30 days after Installment 1.
- A dated installment has no amount.

The manager can approve as-is or reject with suggested amounts/dates.

## 8. Zoho invoice lifecycle

### 8.1 First successful payment

- Create or reuse a Zoho customer by workflow/customer identity.
- Create one invoice for the complete course total.
- Mark the invoice sent.
- Record the first customer payment.
- Download the current invoice PDF.
- Store Zoho customer and invoice IDs on the workflow.

### 8.2 Subsequent successful payment

- Reuse the stored Zoho invoice.
- Record the additional customer payment against that invoice.
- Do not create a separate installment invoice.
- Download the updated invoice PDF showing cumulative paid and balance.
- Attach the updated PDF to Finance “Proof of Next payment.”

### 8.3 Identity rule

The Zoho invoice customer name is the name accepted during the first payment,
not a later Bitrix title/name refresh. Later payment pages deliberately display
the same original identity.

### 8.4 Recovery

Managers can use the Cash Desk invoice retrigger endpoint to create a missing
invoice or redeliver an existing invoice without reapplying the payment.

## 9. Bitrix entity and ID mapping

<!-- DIAGRAM:id-mapping -->

### 9.1 Normal relationship

- Lead ID is the immutable backend correlation key.
- Converted Sales deal retains native `LEAD_ID`.
- Finance deal stores Sales deal ID in Original Deal ID.
- Backend stores discovered Sales, Finance, and B2C IDs for future direct lookup.

### 9.2 Incoming deal resolution order

1. Match stored Finance deal ID.
2. Match stored Sales deal ID.
3. Match stored B2C deal ID.
4. Read native or custom lead references from the incoming deal.
5. Read Finance Original Deal ID.
6. Fetch that Sales deal and read its `LEAD_ID`.
7. Search sibling deals by Contact ID.
8. Search known leads by Contact ID as a last-resort heuristic.

Original Deal ID is preferred over Contact fallback because one contact may
have several unrelated purchases.

### 9.3 Required tunnel mapping

When Bitrix copies Sales to Finance, map:

- Sales deal ID → Finance Original Deal ID.
- Lead ID / native source relationship.
- Contact.
- Products.
- Total and paid amount.
- Installment count, amounts, dates, and payment modes.
- Paid Status.

## 10. Bitrix field reference

### 10.1 Lead payment fields

- Total Amount_: `UF_CRM_1684374599490`
- Number of Installments: `UF_CRM_1684374566210`
- Installment 1: `UF_CRM_1684373846380`
- Installment 2: `UF_CRM_1684380172`
- Installment 3: `UF_CRM_1684380201`
- Installment 4: `UF_CRM_1684380220`
- Installment 1 Date: `UF_CRM_1684373986749`
- Installment 2 Due legacy: `UF_CRM_1684374142163`
- Current temporary Installment 2 Due: `UF_CRM_1684374296635`
- Installment 3 Due: `UF_CRM_1684374296635`
- Installment 4 Due: `UF_CRM_1684374497754`
- Payment 1 Mode: `UF_CRM_1684373954405`
- Payment 2 Mode: `UF_CRM_1684374103659`
- Payment 3 Mode: `UF_CRM_1684374256836`
- Payment 4 Mode: `UF_CRM_1684374451274`

Important: current defaults map Installment 2 and Installment 3 due dates to the
same field. Operations must create/confirm separate fields before using three or
four installments.

### 10.2 Installment count enums

- `5826` — 1 installment
- `5828` — 2 installments
- `5830` — 3 installments
- `5832` — 4 installments

### 10.3 Payment-mode enums

- Cash: `5774` or legacy `5786`
- Website payment: `5776` or `13234`
- Card: `13156`
- Online: `5788`
- Bank transfer: `5778` or legacy `5790`
- Tabby: `5782`
- Tamara: `5784`
- Purchase order: `5780`
- Others: `13146`
- Bank installment: `13178`

### 10.4 Invoice and proof fields

- Complete Lead Payment Proof: `UF_CRM_1775466638710`
- Lead Invoice file: `UF_CRM_1789204266156`
- Finance Proof of Next payment: `UF_CRM_1789378609379`
- Original Deal ID: `UF_CRM_64461C4D5CF41`

### 10.5 Paid Status

**Lead field:** `UF_CRM_1789557091401`

- Fully Paid: `19692`
- Partially paid: `19700`

**Deal field:** `UF_CRM_1789629158792`

- Fully Paid: `19696`
- Partially paid: `19698`

When remaining balance becomes zero, all known deals receive Fully Paid. If
money has been received and a balance remains, they receive Partially paid.

### 10.6 Complete Lead fields

- Comment: `UF_CRM_1684372587728`
- Training mode: `UF_CRM_1684372786609`
- Company website: `UF_CRM_1684388099787`
- Designation: `UF_CRM_1716456659309`
- Industry/domain: `UF_CRM_1749464475095`
- Department/training: `UF_CRM_1749464873149`
- Course duration: `UF_CRM_1771238558828`
- Training start date: `UF_CRM_1771238612202`
- Class timing: `UF_CRM_1771238691110`
- Study materials: `UF_CRM_1771240157159`
- Certificates promised: `UF_CRM_1771240323579`
- Mode of training: `UF_CRM_1771499914629`
- Schedule finalized: `UF_CRM_1771500430277`
- Paid amount: `UF_CRM_1771500781458`
- Trainer shared: `UF_CRM_1771501047627`
- Operations notes: `UF_CRM_1771501226065`
- Student name: `UF_CRM_1771503330575`
- Enrollment date: `UF_CRM_1771503410009`
- Credit card: `UF_CRM_1772016277089`
- Tenure: `UF_CRM_1772019664771`
- Student type: `UF_CRM_1772454738552`
- Batch type: `UF_CRM_1772455024093`

Defaults used where configured:

- Schedule Finalized No: `12912`
- Trainer Shared No: `12916`
- Student Type B2C: `13198`
- Batch Type Public Batch: `13200`

Autofill preserves existing non-empty values. Installment 1 paid date is the
intentional exception and is stamped from payment.

## 11. Bitrix automation configuration

### 11.1 Initial payment-stage outbound webhook

Entity: Lead  
Source stage: Generate Payment Link (`STATUS_ID=10` in the reviewed portal)

Configure an outbound webhook/robot:

```text
POST https://<backend-domain>/webhooks/bitrix24
```

Include the lead document ID and the configured shared secret. Never place the
backend URL in a customer-facing field.

### 11.2 Invoice-sent inbound trigger

Create “Track inbound webhook” as a trigger on the destination Lead stage,
normally Deal Won / Converted.

Railway variable:

```text
BITRIX_INVOICE_SENT_TRIGGER_URL=<generated Bitrix trigger URL>
```

The backend extracts the generated `code` and calls:

```text
crm.automation.trigger
target=LEAD_<lead id>
code=<generated code>
```

Trigger conditions:

- Recommended: no extra trigger condition, because the backend calls it only
  after verified first payment and invoice delivery.
- If required: Paid Status = Partially paid **OR** Fully Paid.
- Never configure those two values with AND.

The trigger should move/convert the lead, then Bitrix creates Sales and copies
to Finance.

### 11.3 Trigger diagnostics

Production logs distinguish:

- Trigger URL not configured.
- Lead state before call.
- Actual Bitrix boolean activation result.
- Stage before and immediately after.
- Trigger accepted but stage unchanged.
- Lead no longer readable because conversion completed.

If Bitrix returns true but no stage-history entry appears after several minutes,
the backend call succeeded and the Bitrix trigger placement, condition, or
enabled state must be corrected.

### 11.4 Sales-to-Finance tunnel

Configure the Sales pipeline to copy or tunnel the converted deal to Finance.
Copy is recommended when Sales needs its own retained record.

Required mapping:

1. Preserve native Lead relationship.
2. Copy Contact and products.
3. Copy payment and installment fields.
4. Set Finance Original Deal ID to the source Sales deal ID.
5. Start Finance in the intended initial/50%-paid stage.

Creating a Finance deal directly in the 50%-paid stage does not automatically
execute robots that only run on a later manual stage transition. Configure the
workflow to start on deal creation at that stage, or explicitly add a Run
Workflow robot.

## 12. Installment due workflow in Bitrix

<!-- DIAGRAM:installment-workflow -->

### 12.1 Recommended start condition

Run on Finance deal creation or entry into the stage that represents first
payment received.

Condition:

- Paid Status = Partially paid.
- Required due-date field is not empty.
- Remaining balance is greater than zero where available.

Fully Paid should take the opposite branch and end without a reminder.

### 12.2 Wait until one day before due date

To trigger at 9:00 AM one day before a due date:

```text
{{=settime(dateadd({=Document:INSTALLMENT_DUE_FIELD}, "-1d"), 9, 0)}}
```

Replace `INSTALLMENT_DUE_FIELD` using Bitrix Insert Value so the expression
references the actual document field.

Bitrix reads the date when the Pause begins. Editing the date afterward does not
recalculate an already-running pause. Restart the workflow after changing a due
date.

### 12.3 Outbound installment call

After the pause:

```text
POST https://<backend-domain>/webhooks/bitrix24/installment-due
```

Pass:

```text
deal_id={=Document:ID}
installment=2
token=<shared secret>
```

Create equivalent branches for installments 3 and 4 only after distinct due
date fields are confirmed.

### 12.4 Backend response behavior

The backend:

- Resolves Finance → Original Sales deal → Lead workflow.
- Merges installment values from Finance where converted Lead fields are blank.
- Skips when the balance is settled.
- Honors installment-specific Cash and Bank Transfer modes.
- Defaults a blank later-installment mode to the online selection page rather
  than inheriting Installment 1 Cash mode.
- Creates/reuses a locked session for the installment.
- Returns HTTP 200 with a JSON business status.

Bitrix treats HTTP 200 as delivered, so operators must inspect JSON/log fields
`status`, `reason`, `installment`, and `payment_url`.

### 12.5 Testing without waiting

1. Duplicate the production workflow into a test workflow.
2. Use a test Finance deal.
3. Temporarily set due date to today/tomorrow and wait time to a few minutes.
4. Confirm Paid Status is Partially paid.
5. Start the workflow explicitly.
6. Review workflow log and backend installment-due log.
7. Restore the production date expression before enabling.

## 13. API and webhook inventory

### 13.1 Health

- `GET /`
- `GET /health`
- `GET /ready`

### 13.2 External webhooks

- `POST /webhooks/bitrix24`
- `POST /webhooks/bitrix24/installment-due`
- `POST /webhooks/paymob`
- `GET /webhooks/paymob`

### 13.3 Customer payment API

- `GET /api/payment/{token}`
- `POST /api/payment/{token}/accept`
- `GET /api/payment/{token}/receipt`
- `POST /api/payment/{token}/receipt`
- `GET /api/payment/lookup/{merchant_reference}`

### 13.4 Manager approval API

- `GET /api/approvals/{token}`
- `POST /api/approvals/{token}/approve`
- `POST /api/approvals/{token}/reject`

### 13.5 Staff and Cash Desk API

- `POST /api/staff/login`
- `POST /api/staff/logout`
- `GET /api/staff/me`
- Employee cash queue, claim, collect, proof, summary, and deposit endpoints.
- Manager employee, dashboard, transaction, bank-transfer, cash-queue, and
  invoice-retrigger endpoints.

### 13.6 Development API

`/api/dev/*` includes payment simulation, reminder execution, mock seeding, and
Zoho OAuth utilities. These routes are currently mounted unconditionally and
must be disabled or strongly protected before a production security sign-off.

## 14. Database model summary

- `customer_workflows` — central aggregate keyed by Bitrix Lead ID.
- `payment_sessions` — secure token, amount, source entity, channel, method,
  provider references, status, and expiry.
- `payment_transactions` — provider/cash/bank ledger with unique transaction ID.
- `terms_acceptances` — accepted version, identity, participants, IP, and PDF.
- `workflow_installments` — frozen installment number, amount, date, and notice.
- `price_approvals` — approval token, pricing payload, manager, decision, expiry.
- `cash_collections` — queue, claimant, proof, collection method, and status.
- `cash_deposits` — employee physical-cash deposits.
- `bank_transfers` — receipt, review state, reviewer, and approved amount.
- `staff_users` — manager/employee login and status.

Migrations are linear from `001_initial` through `021_cash_collect_method`.

## 15. Security controls

Implemented:

- Cryptographically random payment and approval tokens.
- Session expiration and invalidation.
- Paymob HMAC verification with constant-time comparison.
- Duplicate provider transaction protection.
- Staff PBKDF2 password hashing.
- Staff JWT with active-user and role checks.
- Manager-only authorization for management APIs.
- Upload size and MIME allowlists.
- Partial sensitive-field redaction in webhook diagnostics.

Production actions required:

1. Set `APP_ENV=production`.
2. Set a strong `BITRIX_WEBHOOK_SECRET`; blank fails open.
3. Rotate any webhook URL exposed in chat, logs, or tickets.
4. Remove or protect `/api/dev/*`.
5. Add login and webhook rate limiting.
6. Move proofs and generated PDFs to durable object storage or a persistent volume.
7. Add malware/content-signature validation for uploads.
8. Add CSP, HSTS, and other security headers.
9. Review localStorage JWT exposure and CSRF posture.
10. Rotate the hardcoded secret found in the root `hmac.py` utility and remove it
    from source/history as appropriate.

## 16. Deployment

### 16.1 Railway topology

**Service A — Backend**

- Root directory: `backend`
- Start: `sh start.sh`
- Runs Alembic migration then Uvicorn.

**Service B — Frontend + Cash Desk**

- Root directory: repository root
- Dockerfile: `Dockerfile.frontend`
- Serves Jinja frontend and static Cash Desk at `/cashdesk`.

### 16.2 Core backend environment groups

- Application URLs and CORS.
- PostgreSQL/Supabase URL.
- Bitrix REST URL, inbound secret, trigger URL, stage IDs, and field IDs.
- Paymob API, public key, secret key, HMAC, integration IDs, and URLs.
- Zoho client, secret, refresh token, organization, and region.
- SendGrid key and sender.
- Payment thresholds, terms version, session TTL, and reminders.
- Staff JWT and bootstrap-manager credentials.
- Persistent storage path.

Use `.env.example` and `backend/railway.env.example` as checklists, but compare
them with `backend/app/config.py`; configuration drift currently exists.

### 16.3 Deployment verification

1. Confirm migrations completed.
2. `GET /health` returns OK.
3. `GET /ready` reports database OK.
4. Frontend `/health` responds.
5. Confirm commit SHA in backend startup logs.
6. Test a low-value sandbox lead through payment-link creation.
7. Verify Paymob callback, Zoho invoice, Bitrix attachments, and stage trigger.
8. Verify Cash Desk authentication and manager dashboard.

## 17. Monitoring and reconciliation

Recommended daily checks:

- Successful transactions without Zoho invoice ID.
- Zoho invoice balance versus backend remaining balance.
- Finance deals without Original Deal ID.
- Converted leads without a linked workflow/deal.
- Trigger accepted but stage unchanged warnings.
- Installment-due callbacks returning error/ignored.
- Bank transfers pending review beyond SLA.
- Claimed cash cases not collected.
- Employee cash on hand versus deposits.
- Proof files accessible after deploy/restart.

Payment is committed before several external side effects. A successful payment
may therefore coexist with a failed email, attachment, invoice, or Bitrix
automation. Reconciliation must start from the backend transaction ledger and
repair outward.

## 18. Troubleshooting runbook

### 18.1 Bitrix webhook returns 200 but nothing happens

- Read JSON business status; do not rely on HTTP status alone.
- Confirm entity ID and configured stage.
- Confirm current live entity still occupies that stage.
- Confirm workflow resolution by Lead ID or Original Deal ID.
- Check balance and installment number.

### 18.2 Invoice trigger accepted but lead does not move

- Confirm `crm.automation.trigger` result is true.
- Check stage history after several minutes.
- Confirm trigger is saved/enabled on the destination Lead stage.
- Confirm generated code matches Railway.
- Remove conditions temporarily.
- If conditions are retained, use Partially paid OR Fully Paid.

### 18.3 Finance deal cannot find workflow

- Verify Finance Original Deal ID contains the Sales deal ID.
- Fetch Sales deal and confirm native `LEAD_ID`.
- Confirm backend workflow exists for that Lead ID.
- Avoid relying on Contact fallback where the contact has multiple purchases.

### 18.4 Wrong initial link amount

- Inspect Installment 1 at the time the payment-stage webhook ran.
- A positive Installment 1 always wins over blank Installment Count.
- Clear installment values before entering the stage to generate full payment.
- Existing active sessions retain their locked amount; use a new/replaced session.

### 18.5 Wrong name on later payment page

- Compare first `TermsAcceptance` identity with current workflow/Bitrix name.
- Later pages must display first acceptance identity, matching Zoho invoice.
- A later Bitrix refresh must not replace the displayed invoice identity.

### 18.6 Invoice PDF not attached

- Converted leads may no longer be readable.
- First payment targets Lead Payment Proof and Lead Invoice.
- Later payments target Finance Proof of Next payment.
- Verify the Bitrix file payload and refetch field after write.

### 18.7 Duplicate deals

- Backend normal flow does not create deals.
- Inspect Bitrix lead conversion robots and Sales tunnels.
- Ensure only one conversion/creation rule runs at Deal Won.
- Check copied deal rules in every target pipeline.

### 18.8 Paid Status not updating

- Confirm live enum IDs; deleting/recreating options changes IDs.
- Lead Partially paid is currently `19700`.
- Deal Partially paid is `19698`; Fully Paid is `19696`.
- Confirm Finance deal ID has been resolved before second-payment summary update.

## 19. Testing

The backend suite covers:

- Bitrix payload formats, authentication, and stage guards.
- Paymob HMAC and method mapping.
- Terms and locked amounts.
- First/subsequent payment and invoice reuse.
- Catalog and unlisted-course approvals.
- Installment plans, policies, due notices, and reminders.
- Complete Lead autofill and Paid Status.
- Original Deal ID and Contact fallbacks.
- Email validation and duplicate handling.

Important gaps:

- No CI pipeline currently runs tests automatically.
- No live Bitrix/Paymob/Zoho contract suite.
- No PostgreSQL migration test.
- Limited staff, Cash Desk, bank-transfer concurrency, browser, and frontend tests.
- No security, load, accessibility, or multi-replica scheduler suite.

Recommended release gate:

```text
Backend focused/unit tests
Frontend template parse/build
Cash Desk production build
PostgreSQL migration smoke test
Sandbox end-to-end payment
Bitrix automation verification
```

## 20. Known limitations and risks

1. Installment 2 and 3 due-date defaults collide.
2. Runtime environment examples do not contain every current setting.
3. README contains obsolete deal-creation behavior.
4. Development endpoints are exposed unless deployment blocks them.
5. Proof/PDF storage may be ephemeral and instance-local.
6. Scheduler runs inside each API process without a distributed lock.
7. External side effects are not coordinated by a durable outbox.
8. Synchronous database/filesystem work occurs within async flows.
9. Contact fallback can select the wrong purchase for shared contacts.
10. Contact/deal fallback listing is not fully paginated.
11. Bitrix field IDs are assumed compatible across copied entities.
12. Webhook authentication fails open if its secret is blank.
13. `/ready` can report degraded state with HTTP 200.
14. Migrations can race when multiple instances start together.
15. Approval links are capability tokens rather than authenticated manager sessions.
16. No automated backup, restore, rollback, metrics, or incident-response runbook.

## 21. Operational checklists

### 21.1 New Bitrix field or enum

- Create field on the correct entity: Lead or Deal.
- Record field code and option IDs.
- Add configuration with a safe default/example.
- Verify using `crm.lead.userfield.list` or `crm.deal.userfield.list`.
- Test write then refetch.
- Map through lead conversion and Sales-to-Finance copy.

### 21.2 New Finance installment workflow

- Confirm distinct amount and due-date fields.
- Confirm Paid Status field mapping.
- Set start condition to Partially paid.
- Add exact-date Pause expression.
- Add installment-due webhook with secret.
- Add opposite Fully Paid end branch.
- Test in a copied workflow and review logs.

### 21.3 Payment incident

- Record Lead, Sales, Finance, workflow, session, and transaction IDs.
- Confirm provider/cash/bank source of truth.
- Do not manually add a second backend transaction.
- Compare backend, Zoho, and Bitrix balances.
- Retrigger only missing external side effects.
- Document correction and responsible operator.

## 22. Recommended roadmap

**Priority 0 — production safety**

- Protect development routes.
- Enforce startup validation for production secrets.
- Rotate exposed and hardcoded credentials.
- Use durable proof/PDF storage.
- Add CI.

**Priority 1 — reliability**

- Durable outbox/job queue for Zoho, Bitrix, and email side effects.
- Distributed scheduler lock or external scheduled worker.
- Reconciliation dashboard and alerts.
- Idempotent manual recovery commands.

**Priority 2 — maintainability**

- Split the large workflow orchestrator into domain services.
- Unify environment examples.
- Correct README and Railway instructions.
- Add typed Bitrix field registry and startup field validation.
- Add browser and contract tests.

## Appendix A — Source map

Primary backend files:

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/routers/webhooks.py`
- `backend/app/routers/payment_api.py`
- `backend/app/routers/approval_api.py`
- `backend/app/routers/cash_api.py`
- `backend/app/services/workflow_orchestrator.py`
- `backend/app/services/payment_session_service.py`
- `backend/app/services/terms_service.py`
- `backend/app/services/estimate_price_gate.py`
- `backend/app/services/price_approval_service.py`
- `backend/app/services/installment_plan.py`
- `backend/app/services/installment_notices.py`
- `backend/app/services/reminder_service.py`
- `backend/app/services/invoice_service.py`
- `backend/app/services/payment_threshold_service.py`
- `backend/app/services/cash_collection_service.py`
- `backend/app/services/bank_transfer_service.py`
- `backend/app/integrations/bitrix.py`
- `backend/app/integrations/paymob.py`
- `backend/app/integrations/zoho.py`
- `backend/app/integrations/email.py`

Frontend:

- `frontend/app/routers/payment.py`
- `frontend/app/routers/approvals.py`
- `frontend/app/templates/terms.html`
- `frontend/app/templates/approval.html`
- `frontend/app/templates/receipt.html`

Cash Desk:

- `cashdesk/src/app/employee/`
- `cashdesk/src/app/manager/`
- `cashdesk/src/lib/api.ts`

Deployment:

- `backend/Dockerfile`
- `backend/start.sh`
- `backend/railway.toml`
- `Dockerfile.frontend`
- `frontend/railway.toml`
- `docker-compose.yml`
- `.env.example`
- `backend/railway.env.example`

## Appendix B — Environment validation worksheet

Before production deployment, record “configured and verified” for:

- Database connectivity.
- Public backend and frontend URLs.
- Frontend and Cash Desk CORS origins.
- Bitrix REST webhook and inbound secret.
- Bitrix payment and threshold stage IDs.
- Bitrix payment-link, Original Deal ID, invoice, proof, and Paid Status fields.
- Bitrix invoice-sent trigger URL/code.
- Paymob keys, HMAC, integrations, notification URL, and return URL.
- Zoho credentials, organization, domain/region.
- SendGrid sender and key.
- Staff JWT and bootstrap manager.
- Persistent storage.
- Reminder mode: Bitrix workflow versus backend poller.

## Appendix C — Acceptance scenarios

1. Full payment, catalog course, online card.
2. Two installments, first cash and second card.
3. Two installments, second mode blank defaults to online selection.
4. Unlisted course approved at sold amount.
5. Unlisted course rejected with manager-proposed amount.
6. Below-catalog course approved.
7. Bank receipt approved for exact amount.
8. Bank receipt rejected and replaced.
9. Duplicate Paymob callback.
10. Converted lead unavailable during invoice attachment.
11. Finance deal resolved using Original Deal ID.
12. Fully paid second installment updates existing Zoho invoice and Deal Paid Status.
13. Invoice trigger accepted and lead converted.
14. Due date changed after wait; workflow restarted.
15. Deployment restart retains all proof files.

## Appendix D — Final responsibility matrix

**Sales**

- Correct customer/product/amount/installment data.
- Respond to manager rejection and proposed amounts.

**Manager**

- Approve or reject pricing and installment exceptions.
- Provide a proposed amount/date when rejecting.

**Finance**

- Review bank transfer.
- Reconcile backend and Zoho balances.
- Review Fully Paid status.

**Cash Desk employee**

- Claim authorized cases.
- Verify payer, collect correct amount, upload proof.
- Record physical cash deposits.

**Bitrix administrator**

- Maintain trigger, stages, tunnel, mappings, and due workflows.
- Record every automation change.

**Development/Operations**

- Deploy, monitor, reconcile failures, rotate secrets, and maintain tests.

---

**End of document**
