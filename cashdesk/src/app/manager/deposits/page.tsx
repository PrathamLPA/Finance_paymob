"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Deposit = {
  id: number;
  employee_name: string | null;
  amount: string;
  currency: string;
  note: string | null;
  deposited_at: string | null;
  recorded_by_name: string | null;
};

function DepositsPage() {
  const [items, setItems] = useState<Deposit[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const res = await api<{ items: Deposit[] }>("/api/staff/cash/deposits");
    setItems(res.items);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Deposits"
        description="Cash handed to the office or bank by all employees."
      />

      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
        <CardContent className="px-0 pb-0 pt-0">
          <Table>
            <THead>
              <TR>
                <TH>When</TH>
                <TH>Employee</TH>
                <TH>Amount</TH>
                <TH>Note</TH>
                <TH>Recorded by</TH>
              </TR>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <TR>
                  <TD colSpan={5} className="py-10 text-center text-stone-500">
                    No deposits recorded yet
                  </TD>
                </TR>
              ) : (
                items.map((row) => (
                  <TR key={row.id}>
                    <TD className="whitespace-nowrap text-xs">
                      {row.deposited_at ? new Date(row.deposited_at).toLocaleString() : "—"}
                    </TD>
                    <TD>{row.employee_name || "—"}</TD>
                    <TD className="font-medium">{money(row.amount, row.currency)}</TD>
                    <TD className="text-stone-600">{row.note || "—"}</TD>
                    <TD>{row.recorded_by_name || "—"}</TD>
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

export default function ManagerDepositsPage() {
  return (
    <RequireAuth role="manager">{() => <DepositsPage />}</RequireAuth>
  );
}
