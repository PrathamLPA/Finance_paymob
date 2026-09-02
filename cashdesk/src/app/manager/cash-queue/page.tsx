"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
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
};

function CashQueuePage() {
  const [items, setItems] = useState<Collection[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const res = await api<{ items: Collection[] }>("/api/staff/cash/queue");
    setItems(res.items);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

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
                  <TR key={row.id}>
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
                      <Badge
                        variant={
                          row.status === "claimed" ? "warning" : row.status === "open" ? "muted" : "success"
                        }
                      >
                        {row.status}
                      </Badge>
                    </TD>
                    <TD>{row.claimed_by_name || "-"}</TD>
                  </TR>
                ))
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

export default function ManagerCashQueuePage() {
  return (
    <RequireAuth role="manager">{() => <CashQueuePage />}</RequireAuth>
  );
}
