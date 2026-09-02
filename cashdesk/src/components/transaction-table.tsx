"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { api } from "@/lib/api";
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
};

type RetriggerResult = {
  ok: boolean;
  zoho_invoice_id?: string | null;
  invoice_number?: string | null;
  created_new?: boolean;
  steps?: Record<string, string>;
  detail?: string | null;
};

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.75rem_1fr] gap-x-3 gap-y-1 border-b border-stone-200/70 py-2 last:border-b-0 sm:grid-cols-[7.5rem_1fr]">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="break-words text-sm text-stone-900">{value || "-"}</dd>
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
            <p className="mt-1 text-sm text-stone-500">
              Lead #{row.bitrix_lead_id ?? "-"} · {row.course_title || "No course title"}
            </p>
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
              <Badge variant={row.channel === "cash" ? "cash" : "online"}>{row.channel}</Badge>
              {row.invoice_synced ? (
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

        <footer className="txn-modal-footer">
          <Button variant="outline" onClick={onClose} className="min-w-[6.5rem]">
            Close
          </Button>
          <Button
            disabled={busy || !row.workflow_id}
            onClick={onRetrigger}
            className="min-w-[10rem]"
          >
            {busy
              ? "Working…"
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

  useEffect(() => {
    if (!selected) return;
    const fresh = items.find((item) => item.id === selected.id);
    if (fresh) setSelected(fresh);
  }, [items, selected?.id]);

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
      const steps = result.steps
        ? `Zoho: ${result.steps.zoho}; Bitrix: ${result.steps.bitrix}; Email: ${result.steps.email}`
        : "";
      const nextNotice = result.created_new
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
            items.map((row) => (
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
                  <div className="text-xs text-stone-500">
                    Lead #{row.bitrix_lead_id ?? "-"} · {row.course_title || "-"}
                  </div>
                </TD>
                <TD>
                  <Badge variant={row.channel === "cash" ? "cash" : "online"}>{row.channel}</Badge>
                </TD>
                <TD className="font-semibold text-stone-900">{money(row.amount, row.currency)}</TD>
                <TD className="text-xs text-stone-600">
                  <div>Total {money(row.course_total)}</div>
                  <div>
                    {money(row.amount_paid)} paid · {money(row.remaining_balance)} left
                  </div>
                </TD>
                <TD>
                  {row.invoice_synced ? (
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
