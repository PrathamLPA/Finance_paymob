"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, HandCoins, PiggyBank, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

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
  claimed_by_id: number | null;
  course_total: string;
  amount_paid: string;
  remaining_balance: string;
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
  const [success, setSuccess] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [proofById, setProofById] = useState<Record<number, File | null>>({});

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
    setSuccess("");
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
    const file = proofById[id];
    if (!file) {
      setError("Please attach a photo or screenshot before confirming cash received.");
      return;
    }
    setBusyId(id);
    setError("");
    setSuccess("");
    try {
      const body = new FormData();
      body.append("proof", file);
      await api(`/api/staff/cash/${id}/collect`, { method: "POST", body });
      setSuccess("Cash recorded with photo. Bitrix lead timeline and assigned agent were notified.");
      setProofById((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collect failed");
    } finally {
      setBusyId(null);
    }
  }

  const open = items.filter((i) => i.status === "open");
  const mine = items.filter((i) => i.status === "claimed" && i.claimed_by_id === userId);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Collections"
        description="Claim a cash case, upload a handover photo, then confirm collection. Deposit later when you hand cash to the office."
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Cash in hand" value={money(summary?.on_hand, summary?.currency)} icon={HandCoins} accent="amber" />
        <StatCard label="Deposited" value={money(summary?.deposited, summary?.currency)} icon={PiggyBank} accent="teal" />
        <StatCard label="Left to deposit" value={money(summary?.left_to_deposit, summary?.currency)} icon={Wallet} accent="stone" />
      </div>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}
      {success ? (
        <p className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {success}
        </p>
      ) : null}

      {mine.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-500">Your claimed cases</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            {mine.map((row) => (
              <Card key={row.id} className="border-amber-200/80 bg-amber-50/30">
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-lg">{row.customer_name || "Customer"}</CardTitle>
                      <CardDescription>
                        Lead #{row.bitrix_lead_id} · {row.course_title || "Course"}
                      </CardDescription>
                    </div>
                    <Badge variant="warning">claimed</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-stone-500">Installment</p>
                      <p className="font-medium">I{row.installment_number}</p>
                    </div>
                    <div>
                      <p className="text-stone-500">Collect now</p>
                      <p className="text-lg font-semibold text-teal-900">
                        {money(row.due_amount, row.currency)}
                      </p>
                    </div>
                  </div>
                  {row.customer_phone ? (
                    <p className="text-sm text-stone-600">Phone: {row.customer_phone}</p>
                  ) : null}

                  <label className="block space-y-1.5">
                    <span className="text-sm font-medium text-stone-700">
                      Collection photo / screenshot
                    </span>
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp,application/pdf"
                      className="block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-teal-800 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white"
                      onChange={(e) => {
                        const file = e.target.files?.[0] || null;
                        setProofById((prev) => ({ ...prev, [row.id]: file }));
                      }}
                    />
                    <span className="text-xs text-stone-500">
                      {proofById[row.id]
                        ? proofById[row.id]?.name
                        : "JPG, PNG, WEBP, or PDF — max 8MB. Required before confirming."}
                    </span>
                  </label>

                  <Button
                    className="w-full"
                    disabled={busyId === row.id || !proofById[row.id]}
                    onClick={() => collect(row.id)}
                  >
                    {busyId === row.id ? "Saving…" : "Confirm cash received"}
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-500">Open queue</h2>
        {open.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-stone-500">No open cash cases right now</CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {open.map((row) => (
              <Card key={row.id}>
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-lg">{row.customer_name || "Customer"}</CardTitle>
                      <CardDescription>
                        Lead #{row.bitrix_lead_id} · {row.course_title || "Course"}
                      </CardDescription>
                    </div>
                    <Badge variant="muted">open</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <p className="text-stone-500">Installment</p>
                      <p className="font-medium">I{row.installment_number}</p>
                    </div>
                    <div>
                      <p className="text-stone-500">Amount due</p>
                      <p className="font-semibold">{money(row.due_amount, row.currency)}</p>
                    </div>
                    <div className="col-span-2">
                      <p className="text-stone-500">Course total / paid / left</p>
                      <p>
                        {money(row.course_total, row.currency)} · {money(row.amount_paid, row.currency)} paid ·{" "}
                        {money(row.remaining_balance, row.currency)} left
                      </p>
                    </div>
                  </div>
                  <Button variant="outline" className="w-full" disabled={busyId === row.id} onClick={() => claim(row.id)}>
                    Claim this collection
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>
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
