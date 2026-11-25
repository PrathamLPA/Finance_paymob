"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { money } from "@/lib/utils";

export type TxnRow = {
  id: number;
  transaction_id?: string;
  workflow_id: number | null;
  channel: string;
  amount: string;
  currency: string;
  paid_at: string | null;
  bitrix_lead_id: number | null;
  customer_name: string | null;
  customer_email?: string | null;
  course_title: string | null;
  course_total: string | null;
  amount_paid: string | null;
  remaining_balance: string | null;
  employee_name: string | null;
  employee_email: string | null;
  zoho_invoice_id: string | null;
  invoice_synced: boolean;
  awaiting_approval?: boolean;
  follow_up?: { state: string; problems: string[] };
};

type RetriggerResult = {
  ok: boolean;
  zoho_invoice_id?: string | null;
  invoice_number?: string | null;
  created_new?: boolean;
  released_hold?: boolean;
  queued?: boolean;
  job?: string | null;
  verification?: { job?: string | null };
  steps?: Record<string, string>;
  detail?: string | null;
};

const PAGE_SIZE = 100;

// "Lead #123 · Lead 123" reads as a bug; the backend falls back to "Lead <id>" when a
// payment has no course title, so only show a real title next to the lead number.
function leadLine(row: TxnRow): string {
  const title = (row.course_title || "").trim();
  const placeholder = /^lead\s*#?\s*\d+$/i.test(title);
  return `Lead #${row.bitrix_lead_id ?? "-"}${title && !placeholder ? ` · ${title}` : ""}`;
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[5.75rem_minmax(0,1fr)] gap-x-3 gap-y-1 border-b border-stone-200/70 py-2 last:border-b-0 sm:grid-cols-[7.5rem_minmax(0,1fr)]">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="min-w-0 break-words text-sm text-stone-900">{value || "-"}</dd>
    </div>
  );
}

function TransactionDetailModal({
  row,
  busy,
  notice,
  error,
  onClose,
  onRetrigger,
}: {
  row: TxnRow;
  busy: boolean;
  notice: string;
  error: string;
  onClose: () => void;
  onRetrigger: () => void;
}) {
  const titleId = useId();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const prevOverflow = document.body.style.overflow;
    const prevPadding = document.body.style.paddingRight;
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbar > 0) document.body.style.paddingRight = `${scrollbar}px`;

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      document.body.style.paddingRight = prevPadding;
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  if (!mounted) return null;

  return createPortal(
    <div className="txn-modal" role="presentation">
      <button
        type="button"
        className="txn-modal-backdrop"
        aria-label="Close details"
        onClick={onClose}
      />
      <div
        className="txn-modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="txn-modal-header">
          <div className="min-w-0 pr-2">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-teal-800/70">
              Payment details
            </p>
            <h2
              id={titleId}
              className="mt-1 truncate text-xl font-semibold tracking-tight text-stone-900"
            >
              {row.customer_name || "Customer"}
            </h2>
            <p className="mt-1 text-sm text-stone-500">{leadLine(row)}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg border border-stone-200 bg-white/80 p-2 text-stone-600 transition hover:bg-white hover:text-stone-900"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="txn-modal-body">
          <section className="txn-modal-panel">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge
                variant={
                  row.channel === "cash"
                    ? "cash"
                    : row.channel === "pos"
                      ? "online"
                      : "online"
                }
              >
                {row.channel === "pos" ? "POS" : row.channel}
              </Badge>
              {row.awaiting_approval ? (
                <Badge variant="warning">Awaiting finance approval</Badge>
              ) : row.follow_up?.state === "problem" ? (
                <Badge variant="warning">Follow-up incomplete</Badge>
              ) : row.follow_up?.state === "running" ? (
                <Badge variant="online">Finishing...</Badge>
              ) : row.invoice_synced ? (
                <Badge variant="success">Invoice sent</Badge>
              ) : (
                <Badge variant="warning">Invoice missing</Badge>
              )}
            </div>
            <dl>
              <DetailRow
                label="Paid at"
                value={row.paid_at ? new Date(row.paid_at).toLocaleString() : " - "}
              />
              <DetailRow label="Amount" value={money(row.amount, row.currency)} />
              <DetailRow label="Course total" value={money(row.course_total, row.currency)} />
              <DetailRow label="Amount paid" value={money(row.amount_paid, row.currency)} />
              <DetailRow
                label="Remaining"
                value={money(row.remaining_balance, row.currency)}
              />
              <DetailRow label="Email" value={row.customer_email || "-"} />
              <DetailRow
                label="Collector"
                value={
                  row.employee_name ? (
                    <span>
                      {row.employee_name}
                      {row.employee_email ? (
                        <span className="block text-xs text-stone-500">{row.employee_email}</span>
                      ) : null}
                    </span>
                  ) : (
                    " - "
                  )
                }
              />
              <DetailRow label="Txn ref" value={row.transaction_id || `#${row.id}`} />
              <DetailRow label="Zoho invoice" value={row.zoho_invoice_id || "Not created yet"} />
            </dl>
          </section>

          <section className="txn-modal-panel">
            <h3 className="text-sm font-semibold text-stone-900">Invoice delivery</h3>
            <p className="mt-1 text-sm leading-relaxed text-stone-600">
              Creates the Zoho Books invoice if missing, then posts it to Bitrix timelines and
              emails the customer.
            </p>
            {notice ? <p className="mt-3 text-sm text-emerald-800">{notice}</p> : null}
            {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
          </section>
        </div>

        {row.follow_up?.state === "problem" && row.follow_up.problems.length > 0 ? (
          <div className="mx-5 mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <p className="font-medium">The payment is saved, but these steps did not finish:</p>
            <ul className="mt-1 list-disc pl-4">
              {row.follow_up.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
            <p className="mt-1 opacity-80">The system retries by itself. You can also press Retry now.</p>
          </div>
        ) : null}

        <footer className="txn-modal-footer">
          <Button variant="outline" onClick={onClose} className="min-w-[6.5rem]">
            Close
          </Button>
          <Button
            loading={busy}
            disabled={!row.workflow_id}
            onClick={onRetrigger}
            className="min-w-[10rem]"
          >
            {busy
              ? "Starting..."
              : row.awaiting_approval
                ? "Approve & send invoice"
                : row.follow_up?.state === "problem"
                  ? "Retry unfinished steps"
                  : row.invoice_synced
                  ? "Resend invoice"
                  : "Create & send invoice"}
          </Button>
        </footer>
      </div>
    </div>,
    document.body
  );
}

export function TransactionTable({
  items,
  onUpdated,
}: {
  items: TxnRow[];
  onUpdated?: () => void | Promise<void>;
}) {
  const [selected, setSelected] = useState<TxnRow | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  // Render in pages so a long month does not freeze the browser.
  const [visible, setVisible] = useState(PAGE_SIZE);

  useEffect(() => {
    // Keep "Show more" progress on a plain refresh; shrink only if the list got shorter.
    setVisible((v) => Math.max(PAGE_SIZE, Math.min(v, items.length)));
  }, [items]);

  useEffect(() => {
    setSelected((current) => {
      if (!current) return current;
      const fresh = items.find((item) => item.id === current.id);
      return fresh && fresh !== current ? fresh : current;
    });
  }, [items]);

  const shown = items.length > visible ? items.slice(0, visible) : items;

  const toast = useToast();

  async function retrigger(row: TxnRow) {
    setBusyId(row.id);
    setError("");
    setNotice("");
    try {
      const result = await api<RetriggerResult>("/api/staff/invoices/retrigger", {
        method: "POST",
        body: JSON.stringify({
          payment_transaction_id: row.id,
          workflow_id: row.workflow_id,
        }),
      });
      // The server answers at once and finishes in the background: follow it with a toast.
      if (result.queued || result.released_hold) {
        const approved = Boolean(result.released_hold);
        toast.trackJob(result.job ?? result.verification?.job, {
          runningTitle: approved
            ? "Approved. Sending the invoice and updating Bitrix..."
            : "Creating the invoice and sending it...",
          runningDetail: "You can keep working. This takes a few seconds.",
          doneTitle: approved
            ? "Approved. Invoice sent and Bitrix updated."
            : "Invoice created and sent to the customer and Bitrix.",
          onFinished: () => void onUpdated?.(),
        });
        return;
      }
      const steps = result.steps
        ? `Zoho: ${result.steps.zoho}; Bitrix: ${result.steps.bitrix}; Email: ${result.steps.email}`
        : "";
      const nextNotice = result.released_hold
        ? "Payment approved and released: invoice, Bitrix paid status and the next-stage trigger have been run. Check the Finance check page for the result."
        : result.created_new
        ? `Invoice created ${result.invoice_number || result.zoho_invoice_id || ""}. ${steps}`
        : `Invoice resent ${result.invoice_number || result.zoho_invoice_id || ""}. ${steps}`;
      setNotice(nextNotice);
      await onUpdated?.();
      setSelected((current) =>
        current && current.id === row.id
          ? {
              ...current,
              invoice_synced: true,
              zoho_invoice_id:
                result.zoho_invoice_id || current.zoho_invoice_id || result.invoice_number || null,
            }
          : current
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retrigger failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-3">
      <Table>
        <THead>
          <TR>
            <TH>When</TH>
            <TH>Customer / course</TH>
            <TH>Channel</TH>
            <TH>Amount</TH>
            <TH>Paid / left</TH>
            <TH>Invoice</TH>
            <TH>Collector</TH>
          </TR>
        </THead>
        <TBody>
          {items.length === 0 ? (
            <TR>
              <TD colSpan={7} className="py-10 text-center text-stone-500">
                No transactions match your filters
              </TD>
            </TR>
          ) : (
            shown.map((row) => (
              <TR
                key={row.id}
                className="cursor-pointer transition-colors hover:bg-teal-50/60"
                onClick={() => {
                  setNotice("");
                  setError("");
                  setSelected(row);
                }}
              >
                <TD className="whitespace-nowrap text-xs text-stone-600">
                  {row.paid_at ? new Date(row.paid_at).toLocaleString() : " - "}
                </TD>
                <TD>
                  <div className="font-medium text-stone-900">{row.customer_name || "-"}</div>
                  <div className="text-xs text-stone-500">{leadLine(row)}</div>
                </TD>
                <TD>
                  <Badge
                variant={
                  row.channel === "cash"
                    ? "cash"
                    : row.channel === "pos"
                      ? "online"
                      : "online"
                }
              >
                {row.channel === "pos" ? "POS" : row.channel}
              </Badge>
                </TD>
                <TD className="font-semibold text-stone-900">{money(row.amount, row.currency)}</TD>
                <TD className="text-xs text-stone-600">
                  <div>Total {money(row.course_total)}</div>
                  <div>
                    {money(row.amount_paid)} paid · {money(row.remaining_balance)} left
                  </div>
                </TD>
                <TD>
                  {row.awaiting_approval ? (
                    <Badge variant="warning">Awaiting approval</Badge>
                  ) : row.follow_up?.state === "problem" ? (
                    <Badge variant="warning">Follow-up incomplete</Badge>
                  ) : row.follow_up?.state === "running" ? (
                    <Badge variant="online">Finishing...</Badge>
                  ) : row.invoice_synced ? (
                    <Badge variant="success">Sent</Badge>
                  ) : (
                    <Badge variant="warning">Missing</Badge>
                  )}
                </TD>
                <TD>
                  <div className="text-sm">{row.employee_name || "-"}</div>
                  <div className="text-xs text-stone-500">{row.employee_email || ""}</div>
                </TD>
              </TR>
            ))
          )}
        </TBody>
      </Table>

      {items.length > shown.length ? (
        <div className="flex items-center justify-between gap-3 border-t border-stone-100 px-3 py-3 text-xs text-stone-500">
          <span>
            Showing {shown.length} of {items.length}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setVisible((v) => v + PAGE_SIZE)}
          >
            Show more
          </Button>
        </div>
      ) : null}

      {selected ? (
        <TransactionDetailModal
          row={selected}
          busy={busyId === selected.id}
          notice={notice}
          error={error}
          onClose={() => setSelected(null)}
          onRetrigger={() => retrigger(selected)}
        />
      ) : null}
    </div>
  );
}
