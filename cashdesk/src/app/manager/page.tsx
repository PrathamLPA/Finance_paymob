"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Dashboard = {
  cash_on_hand: string;
  total_deposited: string;
  pending_collections: number;
  cash_collected: string;
  online_collected: string;
  employee_count: number;
};

type Txn = {
  id: number;
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
};

function ManagerDashboard() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [items, setItems] = useState<Txn[]>([]);
  const [channel, setChannel] = useState<"all" | "cash" | "online">("all");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({ channel });
    if (q.trim()) params.set("q", q.trim());
    const [d, tx] = await Promise.all([
      api<Dashboard>("/api/staff/dashboard"),
      api<{ items: Txn[] }>(`/api/staff/transactions?${params}`),
    ]);
    setDash(d);
    setItems(tx.items);
  }, [channel, q]);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl text-teal-950">Manager overview</h1>
        <p className="mt-1 text-stone-600">
          On-hand cash across employees, deposits, and every payment channel.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[
          { label: "Cash on hand (all staff)", value: dash?.cash_on_hand },
          { label: "Total deposited", value: dash?.total_deposited },
          { label: "Cash collected", value: dash?.cash_collected },
          { label: "Online collected", value: dash?.online_collected },
          {
            label: "Pending cash cases",
            value: String(dash?.pending_collections ?? 0),
            plain: true,
          },
          {
            label: "Employees",
            value: String(dash?.employee_count ?? 0),
            plain: true,
          },
        ].map((card) => (
          <Card key={card.label}>
            <CardHeader>
              <CardDescription>{card.label}</CardDescription>
              <CardTitle className="text-2xl">
                {card.plain ? card.value : money(card.value)}
              </CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <CardTitle>Transactions</CardTitle>
            <CardDescription>Filter by cash / online and search customer or course</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["all", "cash", "online"] as const).map((c) => (
              <Button
                key={c}
                size="sm"
                variant={channel === c ? "default" : "outline"}
                onClick={() => setChannel(c)}
              >
                {c}
              </Button>
            ))}
            <Input
              className="w-48"
              placeholder="Search…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          {error ? <p className="px-5 pb-3 text-sm text-red-700">{error}</p> : null}
          <Table>
            <THead>
              <TR>
                <TH>When</TH>
                <TH>Customer / course</TH>
                <TH>Channel</TH>
                <TH>Amount</TH>
                <TH>Course total / paid / left</TH>
                <TH>Employee</TH>
              </TR>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <TR>
                  <TD colSpan={6} className="py-8 text-center text-stone-500">
                    No transactions
                  </TD>
                </TR>
              ) : (
                items.map((row) => (
                  <TR key={row.id}>
                    <TD className="whitespace-nowrap text-xs">
                      {row.paid_at ? new Date(row.paid_at).toLocaleString() : "—"}
                    </TD>
                    <TD>
                      <div className="font-medium">{row.customer_name || "—"}</div>
                      <div className="text-xs text-stone-500">
                        Lead #{row.bitrix_lead_id ?? "—"} · {row.course_title || "—"}
                      </div>
                    </TD>
                    <TD>
                      <Badge variant={row.channel === "cash" ? "cash" : "online"}>
                        {row.channel}
                      </Badge>
                    </TD>
                    <TD className="font-medium">{money(row.amount, row.currency)}</TD>
                    <TD className="text-xs text-stone-600">
                      {money(row.course_total)} / {money(row.amount_paid)} /{" "}
                      {money(row.remaining_balance)}
                    </TD>
                    <TD>
                      <div>{row.employee_name || "—"}</div>
                      <div className="text-xs text-stone-500">{row.employee_email || ""}</div>
                    </TD>
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

export default function ManagerPage() {
  return (
    <RequireAuth role="manager">{() => <ManagerDashboard />}</RequireAuth>
  );
}
