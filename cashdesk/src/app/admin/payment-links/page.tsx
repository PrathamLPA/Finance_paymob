"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/toast";
import { money } from "@/lib/utils";
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

type PriceApproval = {
  id: number;
  lead_id: number;
  lead_title: string | null;
  customer_name: string | null;
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

function PaymentLinks() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const toast = useToast();
  const [openMail, setOpenMail] = useState<number | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const [copiedApproval, setCopiedApproval] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setData(await api<Overview>("/api/staff/admin/payment-links"));
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load"));
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

  async function copy(row: LinkRow) {
    try {
      await navigator.clipboard.writeText(row.payment_url);
      setCopied(row.id);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* clipboard blocked */
    }
  }

  async function copyApproval(row: PriceApproval) {
    try {
      await navigator.clipboard.writeText(row.approval_url);
      setCopiedApproval(row.id);
      setTimeout(() => setCopiedApproval(null), 1500);
    } catch {
      /* clipboard blocked */
    }
  }

  const pending = data?.pending_approvals ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Payment links"
        description="Every payment link, the emails that went out, the method each customer chose, and what a finance manager still has to approve."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Manager price approvals ({data?.price_approvals.length ?? 0})</CardTitle>
          <CardDescription>
            Below-minimum price requests: which manager the approval link went to, how it was sent, and
            what they decided.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>Lead</TH>
                <TH>Manager</TH>
                <TH>Price</TH>
                <TH>Sent</TH>
                <TH>Decision</TH>
                <TH></TH>
              </TR>
            </THead>
            <TBody>
              {!data || data.price_approvals.length === 0 ? (
                <TR>
                  <TD colSpan={6} className="py-8 text-center text-stone-500">
                    {data ? "No manager approvals yet" : "Loading..."}
                  </TD>
                </TR>
              ) : (
                data.price_approvals.map((row) => (
                  <TR key={row.id}>
                    <TD>
                      <div className="font-medium">{row.customer_name || row.lead_title || "Customer"}</div>
                      <div className="text-xs text-stone-500">
                        Lead #{row.lead_id}
                        {row.sales_owner ? ` · sales: ${row.sales_owner}` : ""}
                      </div>
                    </TD>
                    <TD>
                      <div className="font-medium">{row.manager_name || "Manager not found"}</div>
                      <div className="text-xs text-stone-500">{row.manager_email || "no email on file"}</div>
                    </TD>
                    <TD>
                      {money(row.total_payable, row.currency)}
                      <div className="text-xs text-stone-500">
                        minimum {money(row.catalog_minimum_total, row.currency)}
                      </div>
                    </TD>
                    <TD>
                      {row.sent_at ? (
                        <>
                          <Badge variant="success">sent via {(row.sent_via || "").replace(/\+/g, " + ")}</Badge>
                          <div className="mt-1 text-xs text-stone-500">{when(row.sent_at)}</div>
                        </>
                      ) : (
                        <Badge variant="warning">not delivered</Badge>
                      )}
                      {row.emails.map((mail) => (
                        <div key={mail.id} className="text-xs text-stone-500">
                          email to {mail.to}: {mail.status}
                        </div>
                      ))}
                      <div className="text-xs text-stone-500">Expires {when(row.expires_at)}</div>
                    </TD>
                    <TD>
                      <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
                      {row.decided_at ? (
                        <div className="mt-1 text-xs text-stone-500">{when(row.decided_at)}</div>
                      ) : null}
                      {row.decision_note ? (
                        <div className="text-xs text-stone-500">{row.decision_note}</div>
                      ) : null}
                    </TD>
                    <TD className="text-right">
                      <Button size="sm" variant="outline" onClick={() => copyApproval(row)}>
                        {copiedApproval === row.id ? "Copied" : "Copy link"}
                      </Button>
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
                <TH>Customer</TH>
                <TH>Amount</TH>
                <TH>Method chosen</TH>
                <TH>Link status</TH>
                <TH>Emails sent</TH>
                <TH>Approval</TH>
                <TH>Created</TH>
                <TH></TH>
              </TR>
            </THead>
            <TBody>
              {!data || data.links.length === 0 ? (
                <TR>
                  <TD colSpan={8} className="py-8 text-center text-stone-500">
                    {data ? "No payment links yet" : "Loading..."}
                  </TD>
                </TR>
              ) : (
                data.links.map((row) => (
                  <TR key={row.id}>
                    <TD>
                      <div className="font-medium">{row.customer_name || "Customer"}</div>
                      <div className="text-xs text-stone-500">
                        Lead #{row.lead_id}
                        {row.customer_email ? ` · ${row.customer_email}` : ""}
                      </div>
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
                      {row.emails.length === 0 ? (
                        <span className="text-xs text-stone-500">none recorded</span>
                      ) : (
                        row.emails.map((mail) => (
                          <div key={mail.id} className="text-xs">
                            <Badge variant={statusVariant(mail.status)}>{mail.status}</Badge> {mail.to} ·{" "}
                            {when(mail.sent_at)}
                          </div>
                        ))
                      )}
                    </TD>
                    <TD>
                      {row.approval ? (
                        <Badge variant={statusVariant(row.approval.status)}>{row.approval.status}</Badge>
                      ) : (
                        <span className="text-xs text-stone-500">-</span>
                      )}
                    </TD>
                    <TD className="text-xs text-stone-500">{when(row.created_at)}</TD>
                    <TD className="text-right">
                      <Button size="sm" variant="outline" onClick={() => copy(row)}>
                        {copied === row.id ? "Copied" : "Copy link"}
                      </Button>
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
