"use client";

import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Collection = {
  id: number;
  bitrix_lead_id: number;
  installment_number: number;
  course_title: string | null;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  due_amount: string;
  currency: string;
  status: string;
  claimed_by_name: string | null;
  course_total: string;
  amount_paid: string;
  remaining_balance: string;
  collect_method?: string | null;
};

function statusVariant(status: string) {
  if (status === "claimed") return "warning" as const;
  if (status === "open") return "muted" as const;
  if (status === "collected") return "success" as const;
  return "default" as const;
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.75rem_1fr] gap-x-3 gap-y-1 border-b border-stone-200/70 py-2 last:border-b-0 sm:grid-cols-[7.5rem_1fr]">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="break-words text-sm text-stone-900">{value || "-"}</dd>
    </div>
  );
}

function CashQueueDetailModal({
  row,
  onClose,
}: {
  row: Collection;
  onClose: () => void;
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
              Cash queue details
            </p>
            <h2
              id={titleId}
              className="mt-1 truncate text-xl font-semibold tracking-tight text-stone-900"
            >
              {row.customer_name || "Customer"}
            </h2>
            <p className="mt-1 text-sm text-stone-500">
              Lead #{row.bitrix_lead_id} · {row.course_title || "No course title"}
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
              <Badge variant="cash">cash desk</Badge>
              <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
              {row.collect_method === "pos" ? (
                <Badge variant="online">POS</Badge>
              ) : row.status === "collected" ? (
                <Badge variant="cash">Cash</Badge>
              ) : null}
            </div>
            <dl>
              <DetailRow label="Installment" value={`I${row.installment_number}`} />
              <DetailRow label="Due" value={money(row.due_amount, row.currency)} />
              <DetailRow label="Course total" value={money(row.course_total, row.currency)} />
              <DetailRow label="Amount paid" value={money(row.amount_paid, row.currency)} />
              <DetailRow label="Remaining" value={money(row.remaining_balance, row.currency)} />
              <DetailRow label="Email" value={row.customer_email || "-"} />
              <DetailRow label="Phone" value={row.customer_phone || "-"} />
              <DetailRow
                label="Assigned to"
                value={
                  row.claimed_by_name ? (
                    <span className="font-medium">{row.claimed_by_name}</span>
                  ) : (
                    "Unassigned"
                  )
                }
              />
            </dl>
          </section>

          <section className="txn-modal-panel">
            <h3 className="text-sm font-semibold text-stone-900">Collection status</h3>
            <p className="mt-1 text-sm leading-relaxed text-stone-600">
              {row.status === "open"
                ? "Waiting for an employee to claim this cash collection."
                : row.status === "claimed"
                  ? "An employee has claimed this collection and is handling the handover."
                  : "This cash collection has been completed."}
            </p>
          </section>
        </div>

        <footer className="txn-modal-footer">
          <Button variant="outline" onClick={onClose} className="min-w-[6.5rem]">
            Close
          </Button>
        </footer>
      </div>
    </div>,
    document.body
  );
}

function CashQueuePage() {
  const [items, setItems] = useState<Collection[]>([]);
  const [selected, setSelected] = useState<Collection | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const res = await api<{ items: Collection[] }>("/api/staff/cash/queue");
    setItems(res.items);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  useEffect(() => {
    if (!selected) return;
    const fresh = items.find((item) => item.id === selected.id);
    if (fresh && fresh !== selected) setSelected(fresh);
  }, [items, selected]);

  const open = items.filter((i) => i.status === "open").length;
  const claimed = items.filter((i) => i.status === "claimed").length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cash queue"
        description="All open and in-progress cash collections across employees."
      />

      <div className="flex gap-3 text-sm">
        <Badge variant="muted">{open} open</Badge>
        <Badge variant="warning">{claimed} claimed</Badge>
      </div>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
        <CardContent className="px-0 pb-0 pt-0">
          <Table>
            <THead>
              <TR>
                <TH>Customer</TH>
                <TH>Installment</TH>
                <TH>Due</TH>
                <TH>Progress</TH>
                <TH>Status</TH>
                <TH>Assigned to</TH>
              </TR>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <TR>
                  <TD colSpan={6} className="py-10 text-center text-stone-500">
                    No pending cash collections
                  </TD>
                </TR>
              ) : (
                items.map((row) => (
                  <TR
                    key={row.id}
                    className="cursor-pointer hover:bg-teal-50/60"
                    onClick={() => setSelected(row)}
                  >
                    <TD>
                      <div className="font-medium">{row.customer_name || "-"}</div>
                      <div className="text-xs text-stone-500">
                        Lead #{row.bitrix_lead_id} · {row.course_title || "-"}
                      </div>
                      {row.customer_phone ? (
                        <div className="text-xs text-stone-500">{row.customer_phone}</div>
                      ) : null}
                    </TD>
                    <TD>I{row.installment_number}</TD>
                    <TD className="font-medium">{money(row.due_amount, row.currency)}</TD>
                    <TD className="text-xs text-stone-600">
                      {money(row.amount_paid, row.currency)} / {money(row.course_total, row.currency)}
                      <div>Left {money(row.remaining_balance, row.currency)}</div>
                    </TD>
                    <TD>
                      <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
                    </TD>
                    <TD>{row.claimed_by_name || "-"}</TD>
                  </TR>
                ))
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      {selected ? (
        <CashQueueDetailModal row={selected} onClose={() => setSelected(null)} />
      ) : null}
    </div>
  );
}

export default function ManagerCashQueuePage() {
  return (
    <RequireAuth role="manager">{() => <CashQueuePage />}</RequireAuth>
  );
}
