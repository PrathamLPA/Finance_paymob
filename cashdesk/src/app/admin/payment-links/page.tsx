"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { useToast } from "@/components/toast";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type LinkEmail = { id: number; to: string; subject: string; status: string; sent_at: string | null };

type LinkRow = {
  id: number;
  lead_id: number;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  bitrix_posted_at: string | null;
  amount: string;
  currency: string;
  installment_number: number | null;
  channel: string;
  chosen_mode: string | null;
  paid_with: string | null;
  status: string;
  payment_url: string;
  paymob_checkout_url: string | null;
  created_at: string | null;
  expires_at: string | null;
  completed_at: string | null;
  emails: LinkEmail[];
  approval: { id: number; status: string } | null;
};

type ApprovalLink = {
  url: string;
  status: string;
  created_at: string | null;
  bitrix_posted_at: string | null;
  emails: LinkEmail[];
};

type PriceApproval = {
  id: number;
  lead_id: number;
  lead_title: string | null;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  sales_owner: string | null;
  manager_name: string | null;
  manager_email: string | null;
  status: string;
  reason: string;
  currency: string;
  total_payable: string;
  catalog_minimum_total: string;
  sent_at: string | null;
  sent_via: string | null;
  created_at: string | null;
  expires_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
  approval_url: string;
  emails: LinkEmail[];
  payment_link: ApprovalLink | null;
};

type Pending = {
  id: number;
  lead_id: number;
  customer_name: string | null;
  amount: string;
  currency: string;
  channel: string | null;
  chosen_mode: string | null;
  paid_with: string | null;
  transaction_id: string | null;
  created_at: string | null;
};

type EmailRow = {
  id: number;
  to: string;
  subject: string;
  status: string;
  has_attachment: boolean;
  sent_at: string | null;
  body: string | null;
};

type Overview = {
  verification_enabled: boolean;
  price_approvals: PriceApproval[];
  links: LinkRow[];
  pending_approvals: Pending[];
  emails: EmailRow[];
};

function when(value: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function mode(value: string | null) {
  return value ? value.replace(/_/g, " ") : "not chosen yet";
}

function statusVariant(status: string): "success" | "warning" | "muted" | "default" {
  if (status === "completed" || status === "sent" || status === "approved") return "success";
  if (status === "failed" || status === "expired" || status === "rejected") return "muted";
  if (status === "pending" || status === "terms_accepted") return "warning";
  return "default";
}

/** Who a payment link went to, shown the same way in both tables. */
function Recipient({
  name,
  email,
  phone,
}: {
  name: string | null;
  email: string | null;
  phone?: string | null;
}) {
  return (
    <div>
      <div className="font-medium">{name || "Customer"}</div>
      <div className="break-all text-xs text-stone-600">{email || "no email on file"}</div>
      {phone ? <div className="text-xs text-stone-500">{phone}</div> : null}
    </div>
  );
}

/** How the link actually reached them: a Bitrix comment, and/or an email to an address. */
function Delivery({ postedAt, emails }: { postedAt: string | null; emails: LinkEmail[] }) {
  if (!postedAt && emails.length === 0) {
    return <span className="text-xs text-stone-500">not delivered yet</span>;
  }
  return (
    <div className="space-y-1 text-xs">
      {postedAt ? (
        <div>
          <Badge variant="success">Posted on Bitrix lead</Badge>
          <div className="mt-0.5 text-stone-500">{when(postedAt)}</div>
        </div>
      ) : null}
      {emails.map((mail) => (
        <div key={mail.id}>
          <Badge variant={statusVariant(mail.status)}>email {mail.status}</Badge>
          <div className="mt-0.5 break-all text-stone-600">to {mail.to}</div>
          <div className="text-stone-500">{when(mail.sent_at)}</div>
        </div>
      ))}
    </div>
  );
}

function PaymentLinks() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [openMail, setOpenMail] = useState<number | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    setData(await api<Overview>("/api/staff/admin/payment-links"));
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load"));
    // Keep the page current while links and emails are being sent in the background.
    const timer = setInterval(() => void refresh().catch(() => undefined), 15000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function decide(id: number, action: "approve" | "reject") {
    setBusyId(id);
    setError("");
    try {
      const res = await api<{ job?: string | null }>(
        `/api/staff/admin/verifications/${id}/${action}`,
        { method: "POST", body: JSON.stringify({ note: null }) }
      );
      // Take it off the waiting list at once; the rest finishes in the background.
      setData((current) =>
        current
          ? { ...current, pending_approvals: current.pending_approvals.filter((p) => p.id !== id) }
          : current
      );
      if (action === "approve") {
        toast.trackJob(res.job, {
          runningTitle: "Approved. Sending the invoice and updating Bitrix...",
          runningDetail: "You can keep working. This takes a few seconds.",
          doneTitle: "Approved. Invoice sent and Bitrix updated.",
          onFinished: () => void refresh().catch(() => undefined),
        });
      } else {
        toast.show({ tone: "info", title: "Payment rejected. No invoice was sent." });
        void refresh().catch(() => undefined);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard blocked */
    }
  }

  const pending = data?.pending_approvals ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Payment links"
        description="Every payment link with who it was sent to and their email, how it was delivered, the method each customer chose, and what a finance manager still has to approve."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Manager price approvals ({data?.price_approvals.length ?? 0})</CardTitle>
          <CardDescription>
            Each approval request: which manager it went to, what they decided, and the payment link that
            was then sent to the customer.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>Lead</TH>
                <TH>Manager (approval sent to)</TH>
                <TH>Price</TH>
                <TH>Decision</TH>
                <TH>Payment link sent to customer</TH>
              </TR>
            </THead>
            <TBody>
              {!data || data.price_approvals.length === 0 ? (
                <TR>
                  <TD colSpan={5} className="py-8 text-center text-stone-500">
                    {data ? "No manager approvals yet" : "Loading..."}
                  </TD>
                </TR>
              ) : (
                data.price_approvals.map((row) => (
                  <TR key={row.id}>
                    <TD>
                      <div className="font-medium">{row.lead_title || row.customer_name || "Lead"}</div>
                      <div className="text-xs text-stone-500">
                        Lead #{row.lead_id}
                        {row.sales_owner ? ` · sales: ${row.sales_owner}` : ""}
                      </div>
                    </TD>
                    <TD>
                      <div className="font-medium">{row.manager_name || "Manager not found"}</div>
                      <div className="break-all text-xs text-stone-600">
                        {row.manager_email || "no email on file"}
                      </div>
                      <div className="mt-1 text-xs text-stone-500">
                        {row.sent_at
                          ? `sent via ${(row.sent_via || "").replace(/\+/g, " + ")} · ${when(row.sent_at)}`
                          : "approval link not delivered"}
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="mt-1.5"
                        onClick={() => copy(`a${row.id}`, row.approval_url)}
                      >
                        {copied === `a${row.id}` ? "Copied" : "Copy approval link"}
                      </Button>
                    </TD>
                    <TD>
                      {money(row.total_payable, row.currency)}
                      <div className="text-xs text-stone-500">
                        minimum {money(row.catalog_minimum_total, row.currency)}
                      </div>
                    </TD>
                    <TD>
                      <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
                      {row.decided_at ? (
                        <div className="mt-1 text-xs text-stone-500">{when(row.decided_at)}</div>
                      ) : (
                        <div className="mt-1 text-xs text-stone-500">Expires {when(row.expires_at)}</div>
                      )}
                      {row.decision_note ? (
                        <div className="text-xs text-stone-500">{row.decision_note}</div>
                      ) : null}
                    </TD>
                    <TD>
                      {row.status !== "approved" ? (
                        <span className="text-xs text-stone-500">
                          {row.status === "pending" ? "Waiting for the manager" : "No link was sent"}
                        </span>
                      ) : row.payment_link ? (
                        <div className="space-y-1.5">
                          <Recipient
                            name={row.customer_name}
                            email={row.customer_email}
                            phone={row.customer_phone}
                          />
                          <Delivery
                            postedAt={row.payment_link.bitrix_posted_at}
                            emails={row.payment_link.emails}
                          />
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => copy(`p${row.id}`, row.payment_link!.url)}
                          >
                            {copied === `p${row.id}` ? "Copied" : "Copy payment link"}
                          </Button>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <Recipient
                            name={row.customer_name}
                            email={row.customer_email}
                            phone={row.customer_phone}
                          />
                          <Badge variant="warning">Link is being prepared</Badge>
                        </div>
                      )}
                    </TD>
                  </TR>
                ))
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Waiting for finance manager ({pending.length})</CardTitle>
          <CardDescription>
            {data?.verification_enabled
              ? "Approving runs the invoice, the Bitrix paid status and the next-stage trigger."
              : "The finance check switch is off, so new payments skip this list. Anything here was queued earlier."}
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>Customer</TH>
                <TH>Amount</TH>
                <TH>Method chosen</TH>
                <TH>Paid with</TH>
                <TH>Queued</TH>
                <TH></TH>
              </TR>
            </THead>
            <TBody>
              {pending.length === 0 ? (
                <TR>
                  <TD colSpan={6} className="py-8 text-center text-stone-500">
                    Nothing waiting for approval
                  </TD>
                </TR>
              ) : (
                pending.map((row) => (
                  <TR key={row.id}>
                    <TD>
                      <div className="font-medium">{row.customer_name || "Customer"}</div>
                      <div className="text-xs text-stone-500">Lead #{row.lead_id}</div>
                    </TD>
                    <TD>{money(row.amount, row.currency)}</TD>
                    <TD className="capitalize">{mode(row.chosen_mode || row.channel)}</TD>
                    <TD className="capitalize">{mode(row.paid_with)}</TD>
                    <TD className="text-xs text-stone-500">{when(row.created_at)}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busyId === row.id}
                          onClick={() => decide(row.id, "reject")}
                        >
                          Reject
                        </Button>
                        <Button size="sm" loading={busyId === row.id} onClick={() => decide(row.id, "approve")}>
                          Approve
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>All payment links ({data?.links.length ?? 0})</CardTitle>
          <CardDescription>
            Newest first. Method chosen is what the customer picked on the payment page.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>Payment link</TH>
                <TH>Sent to</TH>
                <TH>How it was sent</TH>
                <TH>Amount</TH>
                <TH>Method chosen</TH>
                <TH>Status</TH>
                <TH>Approval</TH>
              </TR>
            </THead>
            <TBody>
              {!data || data.links.length === 0 ? (
                <TR>
                  <TD colSpan={7} className="py-8 text-center text-stone-500">
                    {data ? "No payment links yet" : "Loading..."}
                  </TD>
                </TR>
              ) : (
                data.links.map((row) => (
                  <TR key={row.id}>
                    <TD>
                      <div className="max-w-[14rem] break-all font-mono text-[11px] text-stone-600">
                        {row.payment_url}
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="mt-1.5"
                        onClick={() => copy(`l${row.id}`, row.payment_url)}
                      >
                        {copied === `l${row.id}` ? "Copied" : "Copy link"}
                      </Button>
                      <div className="mt-1 text-xs text-stone-500">Created {when(row.created_at)}</div>
                    </TD>
                    <TD>
                      <Recipient
                        name={row.customer_name}
                        email={row.customer_email}
                        phone={row.customer_phone}
                      />
                      <div className="mt-0.5 text-xs text-stone-500">Lead #{row.lead_id}</div>
                    </TD>
                    <TD>
                      <Delivery postedAt={row.bitrix_posted_at} emails={row.emails} />
                    </TD>
                    <TD>
                      {money(row.amount, row.currency)}
                      {row.installment_number ? (
                        <div className="text-xs text-stone-500">Installment {row.installment_number}</div>
                      ) : null}
                    </TD>
                    <TD className="capitalize">
                      {mode(row.chosen_mode)}
                      {row.paid_with ? (
                        <div className="text-xs text-stone-500">paid: {mode(row.paid_with)}</div>
                      ) : null}
                    </TD>
                    <TD>
                      <Badge variant={statusVariant(row.status)}>{row.status.replace(/_/g, " ")}</Badge>
                      <div className="mt-1 text-xs text-stone-500">Expires {when(row.expires_at)}</div>
                    </TD>
                    <TD>
                      {row.approval ? (
                        <Badge variant={statusVariant(row.approval.status)}>{row.approval.status}</Badge>
                      ) : (
                        <span className="text-xs text-stone-500">-</span>
                      )}
                    </TD>
                  </TR>
                ))
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Emails sent ({data?.emails.length ?? 0})</CardTitle>
          <CardDescription>
            Emails this system sends from now on (payment links, invoices, reminders). Click a row to read it.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>To</TH>
                <TH>Subject</TH>
                <TH>Status</TH>
                <TH>Sent</TH>
              </TR>
            </THead>
            <TBody>
              {!data || data.emails.length === 0 ? (
                <TR>
                  <TD colSpan={4} className="py-8 text-center text-stone-500">
                    {data ? "No emails recorded yet" : "Loading..."}
                  </TD>
                </TR>
              ) : (
                data.emails.map((mail) => (
                  <Fragment key={mail.id}>
                    <TR className="cursor-pointer" onClick={() => setOpenMail(openMail === mail.id ? null : mail.id)}>
                      <TD>{mail.to}</TD>
                      <TD>
                        {mail.subject}
                        {mail.has_attachment ? <span className="ml-2 text-xs text-stone-500">(attachment)</span> : null}
                      </TD>
                      <TD>
                        <Badge variant={statusVariant(mail.status)}>{mail.status}</Badge>
                      </TD>
                      <TD className="text-xs text-stone-500">{when(mail.sent_at)}</TD>
                    </TR>
                    {openMail === mail.id ? (
                      <TR>
                        <TD colSpan={4}>
                          <pre className="whitespace-pre-wrap break-words rounded-md bg-stone-50 p-3 text-xs text-stone-700">
                            {mail.body || "(no body)"}
                          </pre>
                        </TD>
                      </TR>
                    ) : null}
                  </Fragment>
                ))
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdminPaymentLinksPage() {
  return <RequireAuth role="admin">{() => <PaymentLinks />}</RequireAuth>;
}
