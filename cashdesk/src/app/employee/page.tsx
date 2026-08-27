"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  collected_amount: string;
  currency: string;
  status: string;
  claimed_by_id: number | null;
  course_total: string;
  amount_paid: string;
  remaining_balance: string;
  is_collected: boolean;
};

type Summary = {
  on_hand: string;
  deposited: string;
  left_to_deposit: string;
  collected: string;
  currency: string;
};

function EmployeeDesk({ userId }: { userId: number }) {
  const [items, setItems] = useState<Collection[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    const [queue, bal] = await Promise.all([
      api<{ items: Collection[] }>("/api/staff/cash/queue"),
      api<Summary>("/api/staff/cash/my-summary"),
    ]);
    setItems(queue.items);
    setSummary(bal);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  async function claim(id: number) {
    setBusyId(id);
    setError("");
    try {
      await api(`/api/staff/cash/${id}/claim`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Claim failed");
    } finally {
      setBusyId(null);
    }
  }

  async function collect(id: number) {
    setBusyId(id);
    setError("");
    try {
      await api(`/api/staff/cash/${id}/collect`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collect failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl text-teal-950">Cash collections</h1>
        <p className="mt-1 text-stone-600">
          Claim open cash cases, collect the installment due, then deposit from Deposits.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          { label: "Cash in hand", value: summary?.on_hand },
          { label: "Deposited", value: summary?.deposited },
          { label: "Left to deposit", value: summary?.left_to_deposit },
        ].map((card) => (
          <Card key={card.label}>
            <CardHeader>
              <CardDescription>{card.label}</CardDescription>
              <CardTitle className="text-2xl">
                {money(card.value, summary?.currency || "AED")}
              </CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Queue</CardTitle>
          <CardDescription>Open cases and your claimed collections</CardDescription>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>Customer / course</TH>
                <TH>Installment</TH>
                <TH>To collect</TH>
                <TH>Balance</TH>
                <TH>Status</TH>
                <TH></TH>
              </TR>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <TR>
                  <TD colSpan={6} className="py-8 text-center text-stone-500">
                    No cash collections waiting
                  </TD>
                </TR>
              ) : (
                items.map((row) => {
                  const mine = row.claimed_by_id === userId;
                  return (
                    <TR key={row.id}>
                      <TD>
                        <div className="font-medium">{row.customer_name || "—"}</div>
                        <div className="text-xs text-stone-500">
                          Lead #{row.bitrix_lead_id} · {row.course_title || "Course"}
                        </div>
                        {row.customer_phone ? (
                          <div className="text-xs text-stone-500">{row.customer_phone}</div>
                        ) : null}
                      </TD>
                      <TD>
                        I{row.installment_number}
                        <div className="text-xs text-stone-500">
                          Total {money(row.course_total, row.currency)}
                        </div>
                      </TD>
                      <TD className="font-medium">{money(row.due_amount, row.currency)}</TD>
                      <TD>
                        Paid {money(row.amount_paid, row.currency)}
                        <div className="text-xs text-stone-500">
                          Left {money(row.remaining_balance, row.currency)}
                        </div>
                      </TD>
                      <TD>
                        <Badge
                          variant={
                            row.status === "claimed"
                              ? "warning"
                              : row.status === "collected"
                                ? "success"
                                : "muted"
                          }
                        >
                          {row.status}
                        </Badge>
                      </TD>
                      <TD className="text-right">
                        {row.status === "open" ? (
                          <Button
                            size="sm"
                            disabled={busyId === row.id}
                            onClick={() => claim(row.id)}
                          >
                            Claim
                          </Button>
                        ) : null}
                        {row.status === "claimed" && mine ? (
                          <Button
                            size="sm"
                            disabled={busyId === row.id}
                            onClick={() => collect(row.id)}
                          >
                            Mark collected
                          </Button>
                        ) : null}
                      </TD>
                    </TR>
                  );
                })
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

export default function EmployeePage() {
  return (
    <RequireAuth>
      {(user) => <EmployeeDesk userId={user.id} />}
    </RequireAuth>
  );
}
