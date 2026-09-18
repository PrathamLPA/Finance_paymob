# Finance Paymob User Guide

**A plain-language guide for Sales, Finance, Cash Desk, Managers, and Account Management**

Version 1.0  
Prepared: 17 September 2026  
Classification: Internal use

---

## Welcome

This guide explains how to use the Finance Paymob system from beginning to end.
It is written for day-to-day users. You do not need to understand programming,
webhooks, APIs, or databases.

The system connects Bitrix, the customer payment page, Paymob, Zoho Books,
email, and the Cash Desk. Each system has a different job:

- Bitrix holds the customer, course, amount, installment plan, and work stages.
- The payment page lets the customer check details, choose how to pay, and
  accept the terms.
- Paymob collects online payments.
- Zoho creates and updates the invoice.
- Cash Desk records cash and card-machine payments made at the office.
- Finance reviews bank transfers.

## 1. The complete journey in one page

<!-- DIAGRAM:payment-flow -->

1. Sales prepares the Lead in Bitrix.
2. Sales adds the correct course and selling amount.
3. Sales adds installment details only when the customer has an installment plan.
4. The Lead is moved to Generate Payment Link.
5. The system checks the course price and installment plan.
6. If approval is needed, the manager receives an approval request.
7. If everything is acceptable, the customer receives a secure payment link.
8. The customer checks their details, chooses a payment method, accepts the
   terms, and continues.
9. The payment is completed online, at Cash Desk, or by bank transfer.
10. Zoho creates the invoice and records the payment.
11. Bitrix receives the invoice and payment details.
12. After the first payment, Bitrix converts the Lead and creates the Sales and
    Finance cards.
13. If money is still due, Bitrix waits until the next payment date and sends
    the next link.
14. After the final payment, the Finance card becomes Fully Paid.

## 2. Who does what?

### 2.1 Sales

Sales is responsible for the information before the first payment:

- Correct customer name, email, and phone.
- Correct course.
- Correct selling amount.
- Correct installment amounts and dates.
- Moving the Lead to Generate Payment Link.
- Correcting information when a manager rejects a request.

### 2.2 Customer

The customer:

- Opens the secure payment link.
- Checks or enters their details on the first payment.
- Chooses the payment method.
- Reads and accepts the Terms and Refund Policy.
- Completes the payment or uploads bank proof.

### 2.3 Manager

The manager:

- Reviews prices below the allowed catalog price.
- Reviews courses that are not in inventory.
- Reviews unusual installment plans.
- Approves the request or rejects it with a proposed correction.

### 2.4 Cash Desk employee

The employee:

- Opens the Cash Queue.
- Claims a customer before collecting.
- Checks the due amount.
- Records Cash or POS correctly.
- Uploads proof.
- Records cash deposits.

### 2.5 Finance manager

Finance:

- Reviews bank-transfer proof.
- Approves the amount actually received.
- Rejects unclear or incorrect proof.
- Checks invoice and remaining balance.
- Reconciles Fully Paid customers.

### 2.6 Bitrix administrator

The Bitrix administrator maintains:

- Lead and Finance stages.
- The first-payment completion trigger.
- Sales-to-Finance copying.
- Installment wait workflows.
- Field copying between Lead, Sales, and Finance cards.

## 3. Before Sales requests a payment link

Use this checklist every time.

### 3.1 Customer details

Confirm:

- Customer or payer name is spelled correctly.
- Email belongs to the person who should receive the payment link.
- Phone number includes the country code where possible.
- The correct responsible Sales person is selected.

Incorrect details can cause the payment link, terms email, or invoice to go to
the wrong person.

### 3.2 Course details

Add the course as a product on the Lead. Check:

- Course name.
- Quantity or number of seats.
- Selling amount.
- VAT treatment.

Do not type a course only inside a comment. The course must appear in the
product list so it can appear on the estimate and invoice.

### 3.3 Full payment

If the customer will pay the full amount:

- Leave Installment 1, Installment 2, and later installment amounts empty.
- Leave Number of Installments empty or set it to one according to the agreed
  Bitrix procedure.
- Confirm the Lead total is correct.

When Installment 1 is empty, the system creates a link for the full outstanding
amount.

### 3.4 Installment payment

If the customer will pay in installments:

- Select the number of installments.
- Enter Installment 1 amount.
- Enter Installment 2 amount and due date.
- Add Installment 3 or 4 only when approved and the correct fields exist.
- Confirm all installment amounts add up exactly to the course total.

Example:

```text
Course total: AED 4,000
Installment 1: AED 2,000
Installment 2: AED 2,000
Total installments: AED 4,000
```

If Installment 1 contains an amount, the first link will use that amount even
when Number of Installments is blank.

### 3.5 Payment mode

Only set a Bitrix installment payment mode when the method is already agreed.

- Cash means the case goes to Cash Desk.
- Bank Transfer means the customer uploads transfer proof.
- Online or a blank later-installment mode shows the customer the online
  payment-method choices.

## 4. Requesting the first payment link

### 4.1 Sales action

After checking all information:

1. Save the Lead.
2. Move it to Generate Payment Link.
3. Wait for the system result.
4. Check the Bitrix timeline.

### 4.2 What happens automatically

The system:

- Reads the latest Lead information.
- Checks the course and price.
- Checks installment rules.
- Creates an estimate.
- Creates a secure payment request.
- Sends or posts the payment link.

Moving the same Lead repeatedly should not create a new active link every time.
The system normally reuses the existing active request.

## 5. Manager approval cycles

### 5.1 Price below catalog minimum

When the selling amount is lower than the allowed catalog amount:

1. No customer payment link is sent yet.
2. The manager receives an approval email/link.
3. The manager sees the sold amount and catalog minimum.
4. The manager approves or rejects.

If approved:

- The payment link is sent using the approved sold amount.
- The Bitrix timeline records the approval.

If rejected:

- No payment link is sent.
- The manager enters the proposed amount and a note.
- Sales receives a message showing the proposed amount.
- Sales corrects the Lead and requests approval again.

### 5.2 Course not in inventory

When a custom course is not found in the catalog:

1. The system shows the course name and sold amount to the manager.
2. The manager may approve that amount as a one-time exception.
3. Or the manager may reject and enter a proposed amount.
4. Sales receives the manager’s decision and comment.

The normal flow is unchanged for courses already in inventory.

### 5.3 Installment approval

Approval may also be requested when:

- The first payment is below the required percentage.
- More than two installments are requested.
- The second date is too far from the first date.
- A due date exists but its amount is missing.

The manager should check the entire schedule before approving.

## 6. Customer first-payment page

The first link asks the customer for information that will be used for payment,
terms, and invoice records.

### 6.1 “For me”

Select this when the payer is also the student. The entered name becomes the
main invoice/customer name.

### 6.2 “For someone else”

Select this when one person pays for another student or several candidates.
Enter the payer details and all required candidate details.

### 6.3 Payment summary

The customer should check:

- Course total.
- Amount already paid, usually zero on the first request.
- Amount to pay now.
- Balance after payment.
- Installment schedule where applicable.

The amount is locked when it comes from the approved Bitrix plan.

### 6.4 Payment method

The customer chooses:

- Card.
- Website payment.
- Tabby.
- Tamara.
- Bank transfer.
- Cash.

The customer must then open the Terms and Refund Policy, read to the end, accept,
and continue.

## 7. Online payment cycle

### 7.1 Customer steps

1. Choose Card, Website payment, Tabby, or Tamara.
2. Accept the terms.
3. Continue to Paymob.
4. Complete the hosted checkout.
5. Wait for the success/thank-you page.

### 7.2 After success

The system:

- Confirms the payment with Paymob.
- Records the transaction once.
- Updates paid and remaining amounts.
- Creates or updates the Zoho invoice.
- Sends the invoice by email.
- Adds invoice proof to Bitrix.

If the customer refreshes the Paymob result page, it should not record the same
provider transaction twice.

### 7.3 Failed online payment

If payment fails:

- No paid amount should be added.
- The Bitrix timeline may show the failure.
- The responsible person may receive a notification.
- The customer can retry with a valid active link or request a replacement.

Never manually mark the Finance card Fully Paid because the customer says they
paid. Confirm the provider result first.

## 8. Cash and POS cycle

### 8.1 Customer

1. Select Cash.
2. Enter/check details.
3. Accept terms.
4. The page confirms payment will be made at the office.

### 8.2 Employee

1. Sign in to Cash Desk.
2. Open Cash Queue.
3. Find the customer.
4. Check installment number and due amount.
5. Claim the case.
6. Collect the exact amount.
7. Select Cash or POS.
8. Upload clear proof.
9. Confirm collection.

### 8.3 Cash versus POS

- Cash increases the employee’s physical cash-on-hand balance.
- POS records payment but does not increase physical cash on hand.

Choosing the wrong method causes employee balances to be incorrect.

### 8.4 Depositing cash

After handing over physical cash:

1. Open Deposits.
2. Enter the deposited amount.
3. Add reference/details.
4. Submit.

The deposit reduces employee cash on hand. It does not create a second customer
payment.

## 9. Bank-transfer cycle

### 9.1 Customer

1. Select Bank transfer.
2. Accept terms.
3. Follow the displayed bank instructions.
4. Upload a clear receipt image or PDF.
5. Submit for review.

Uploading proof does not mean the payment is approved.

### 9.2 Finance review

1. Open Bank Transfers in the manager Cash Desk.
2. Open the submitted proof.
3. Confirm sender, amount, date, and reference.
4. Approve the amount actually received or reject with a note.

On approval, the normal invoice and Bitrix update cycle starts.

On rejection:

- No payment is added.
- The reason should clearly tell the customer/staff what must be corrected.
- The customer may upload replacement proof.

## 10. What happens after the first payment

After the first successful payment:

1. Zoho creates the customer and full-course invoice.
2. The first payment is applied to the invoice.
3. The invoice PDF is attached to the Lead.
4. Paid Status becomes Partially paid or Fully Paid.
5. The backend rings the Bitrix invoice-complete trigger.
6. Bitrix converts the Lead.
7. Bitrix creates the Sales deal.
8. Bitrix copies/tunnels it to Finance.

The backend does not normally create these deals. If duplicate Sales or Finance
cards appear, check Bitrix conversion rules and tunnels.

## 11. Finance card and status

### 11.1 Partially paid

Use when:

- At least one verified payment exists.
- A balance remains.

This status allows the next-installment workflow to continue.

### 11.2 Fully Paid

Use when:

- Verified cumulative payments equal the total.
- Remaining balance is zero.

The system updates Fully Paid automatically after the final successful payment
when the Finance card is correctly linked.

### 11.3 Original Deal ID

The Finance card must contain the Sales deal ID in Original Deal ID. This is how
the system reliably finds the correct customer workflow.

Do not replace it with Lead title, Deal name, or Contact ID.

## 12. Second-installment cycle

<!-- DIAGRAM:installment-workflow -->

### 12.1 Before the due date

The Bitrix Finance workflow:

1. Starts when the Finance card is created in the correct stage.
2. Checks that Paid Status is Partially paid.
3. Waits until the configured time before the due date.
4. Requests the second payment link.

Fully Paid cards should leave the opposite branch and stop.

### 12.2 Customer second-payment page

The second page is shorter than the first. It shows only the invoice details:

- Invoice name used on the first Zoho invoice.
- Course.
- Email ID.
- Phone number.

It also shows:

- Total.
- Already paid.
- Outstanding balance.
- Pay now.
- Balance after payment.

The customer does not choose “For me / someone else” again and does not re-enter
their identity. They only:

1. Check invoice and amount details.
2. Choose payment method.
3. Read and accept current terms.
4. Continue payment.

### 12.3 After second payment

The system:

- Reuses the same Zoho invoice.
- Adds the second payment to its payment history.
- Downloads the updated invoice PDF.
- Adds the updated PDF to Finance Proof of Next payment.
- Updates cumulative paid and remaining balance.
- Changes Finance Paid Status to Fully Paid when the balance reaches zero.

A second installment does not create a second Zoho invoice.

## 13. Invoice guide

### 13.1 What name appears?

The invoice name comes from the name accepted during the first payment.

Later Bitrix name/title changes must not change the name shown on the
second-payment confirmation page.

### 13.2 What course appears?

The invoice uses the selected Bitrix product/course rows. Course name must be
correct before the first payment.

### 13.3 What amounts appear?

The invoice represents the full course total. Payments are applied against it,
so it can show:

- Total.
- Amount paid.
- Remaining balance.
- Partially paid or paid state.

### 13.4 Missing invoice

Do not record the customer payment again. A manager should use Invoice Retrigger
to recreate or redeliver the missing invoice without adding another payment.

## 14. Account Management cycle

Where the Account Management pipeline is enabled:

- Finance can copy a due-payment case into Account Management.
- AM contacts the customer and records follow-up.
- The AM copy must remain linked to the Finance deal.
- Once payment is received, Finance is updated from the payment system.
- AM marks its follow-up resolved according to the Bitrix process.

AM should not manually change paid amounts without Finance verification.

## 15. Common examples

### 15.1 Customer pays everything first time

- No installment amount is entered.
- Full-payment link is generated.
- Customer pays the total.
- Zoho invoice balance becomes zero.
- Paid Status becomes Fully Paid.
- No second reminder should run.

### 15.2 Customer pays 50% cash, then 50% card

- Sales enters two equal installments.
- Customer chooses Cash for payment one.
- Cash Desk records the first payment.
- Paid Status becomes Partially paid.
- Bitrix waits for Installment 2 date.
- Customer opens the shorter second link and chooses Card.
- Zoho updates the same invoice.
- Finance becomes Fully Paid.

### 15.3 Course is not in inventory

- Manager receives course and sold amount.
- Approve sends the payment link unchanged.
- Reject sends the proposed amount to Sales.
- Sales corrects and resubmits.

### 15.4 Bank transfer proof is unclear

- Finance rejects with a clear reason.
- No paid amount is recorded.
- Customer submits replacement proof.
- Finance approves only after matching the bank record.

## 16. What not to do

- Do not put a Lead in Generate Payment Link before checking products and amount.
- Do not enter half the total in Installment 1 for a full-payment customer.
- Do not create a new Zoho invoice manually for the second installment.
- Do not collect a Cash Desk case claimed by another employee.
- Do not approve bank proof without checking the actual bank receipt.
- Do not mark Fully Paid based only on a screenshot or customer message.
- Do not change Original Deal ID to a Contact ID.
- Do not duplicate Bitrix conversion robots.
- Do not edit due date after a workflow starts without restarting the workflow.
- Do not share customer payment or approval links in public channels.

## 17. Quick troubleshooting

### Payment link amount is wrong

Check Installment 1. If it has a positive amount, that becomes the first link.
For full payment, clear installment amounts before requesting a new link.

### Manager did not receive approval

Check the responsible Sales person and their manager assignment. Review the Lead
timeline for pending approval information.

### Lead did not convert

Confirm the invoice exists and check the backend trigger log. Then check that
the Bitrix inbound trigger is enabled on Deal Won and does not use impossible
AND conditions.

### Second reminder did not run

Check:

- Finance Paid Status is Partially paid.
- Due date exists.
- Workflow was started when the Finance card was created.
- The wait was restarted after any due-date edit.

### Finance deal cannot be matched

Check Original Deal ID and the Sales deal’s Lead ID.

### Second page shows the wrong invoice name

Compare it with the first payment’s accepted name and the Zoho invoice customer.
Escalate with Lead ID and invoice number.

### Invoice is missing from Bitrix

Check whether the Lead was already converted. First invoice belongs on Lead;
later invoice proof belongs on Finance.

### Customer paid but status remains partial

Compare total, cumulative paid, and remaining balance. Confirm the Finance deal
is linked before asking an operator to repair the status.

## 18. Information to include when asking for support

Provide only internal identifiers, not passwords or API keys:

- Bitrix Lead ID.
- Sales deal ID.
- Finance deal ID.
- Zoho invoice number.
- Payment date and amount.
- Payment method.
- Screenshot of the visible error.
- Approximate time the action happened.
- Whether it was first or later installment.

Never paste full webhook URLs, payment tokens, provider keys, or staff passwords.

## 19. Daily role checklists

### Sales

- Customer details correct.
- Product and amount correct.
- Installments balanced.
- Manager rejection handled.
- Timeline checked after requesting link.

### Cash Desk employee

- Correct case claimed.
- Amount confirmed.
- Cash/POS selected correctly.
- Proof uploaded.
- Physical cash deposits recorded.

### Finance manager

- Pending bank transfers reviewed.
- Zoho and backend balances compared.
- Fully Paid records checked.
- Missing invoices retriggered without duplicate payment.

### Bitrix administrator

- Failed workflows reviewed.
- Trigger codes and stages unchanged unless documented.
- Due-date edits followed by workflow restart.
- Duplicate deal automation monitored.

## 20. Final summary

The safest way to use Finance Paymob is:

1. Enter accurate information once in Bitrix.
2. Let the customer confirm identity on the first payment.
3. Treat the backend transaction ledger as the payment source of truth.
4. Let Zoho keep one invoice with several payments.
5. Let Bitrix control conversion and due-date workflow.
6. Let later payment pages reuse the first invoice identity.
7. Let Fully Paid happen only when the remaining balance is zero.

When something fails after money is recorded, repair the missing invoice, email,
attachment, or Bitrix stage. Do not record the payment a second time.

---

**End of user guide**
