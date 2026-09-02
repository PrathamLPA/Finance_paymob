"use client";

import { useState } from "react";
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

export function TransactionTable({
  items,
  onUpdated,
}: {
  items: TxnRow[];
  onUpdated?: () => void | Promise<void>;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");

  async function retrigger(row: TxnRow) {
    setBusyId(row.id);
    setError("");
    setMessage("");
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
      setMessage(
        result.created_new
          ? `Invoice created ${result.invoice_number || result.zoho_invoice_id || ""}. ${steps}`
          : `Invoice resent ${result.invoice_number || result.zoho_invoice_id || ""}. ${steps}`
      );
      await onUpdated?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retrigger failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-3">
      {message ? <p className="px-4 pt-3 text-sm text-emerald-800">{message}</p> : null}
      {error ? <p className="px-4 pt-3 text-sm text-red-700">{error}</p> : null}
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
              <TR key={row.id}>
                <TD className="whitespace-nowrap text-xs text-stone-600">
                  {row.paid_at ? new Date(row.paid_at).toLocaleString() : "—"}
                </TD>
                <TD>
                  <div className="font-medium text-stone-900">{row.customer_name || "—"}</div>
                  <div className="text-xs text-stone-500">
                    Lead #{row.bitrix_lead_id ?? "—"} · {row.course_title || "—"}
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
                <TD className="min-w-[9.5rem]">
                  <div className="flex flex-col items-start gap-1.5">
                    {row.invoice_synced ? (
                      <Badge variant="success">Sent</Badge>
                    ) : (
                      <Badge variant="warning">Missing</Badge>
                    )}
                    {row.zoho_invoice_id ? (
                      <span className="max-w-[8rem] truncate text-[11px] text-stone-500">
                        {row.zoho_invoice_id}
                      </span>
                    ) : null}
                    <Button
                      size="sm"
                      variant={row.invoice_synced ? "outline" : "default"}
                      disabled={busyId === row.id || !row.workflow_id}
                      onClick={() => retrigger(row)}
                    >
                      {busyId === row.id
                        ? "Working…"
                        : row.invoice_synced
                          ? "Resend"
                          : "Create & send"}
                    </Button>
                  </div>
                </TD>
                <TD>
                  <div className="text-sm">{row.employee_name || "—"}</div>
                  <div className="text-xs text-stone-500">{row.employee_email || ""}</div>
                </TD>
              </TR>
            ))
          )}
        </TBody>
      </Table>
    </div>
  );
}
