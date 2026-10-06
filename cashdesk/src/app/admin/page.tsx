"use client";

import { useCallback, useEffect, useState } from "react";
import { Banknote, Receipt, ShieldCheck, Users, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Overview = {
  finance_manager_verification: boolean;
  staff: { admin: number; manager: number; employee: number };
  staff_total: number;
  transactions: number;
  open_cash_collections: number;
  pending_bank_transfers: number;
  pending_verifications: number;
};

function AdminHome() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const overview = await api<Overview>("/api/staff/admin/overview");
    setData(overview);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load"));
  }, [refresh]);

  async function setVerification(enabled: boolean) {
    setBusy(true);
    setError("");
    try {
      await api("/api/staff/admin/verification", {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the switch");
    } finally {
      setBusy(false);
    }
  }

  const on = Boolean(data?.finance_manager_verification);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Control"
        description="Live counts for the finance flow. The finance check can stay on while you watch the system, then switch off so payments continue on their own."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard label="Active people" value={String(data?.staff_total ?? "—")} icon={Users} />
        <StatCard label="Managers" value={String(data?.staff.manager ?? "—")} hint="Cash desk managers" icon={Users} accent="stone" />
        <StatCard label="Employees" value={String(data?.staff.employee ?? "—")} icon={Wallet} accent="amber" />
        <StatCard label="Transactions" value={String(data?.transactions ?? "—")} icon={Receipt} accent="sky" />
        <StatCard label="Open cash cases" value={String(data?.open_cash_collections ?? "—")} icon={Banknote} accent="amber" />
        <StatCard label="Bank receipts waiting" value={String(data?.pending_bank_transfers ?? "—")} icon={Receipt} accent="stone" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-teal-800" />
            Finance manager check
          </CardTitle>
          <CardDescription>
            {on
              ? "On. A recorded payment waits here until a finance manager approves it. Invoice and Bitrix updates run after that."
              : "Off. Payments follow the normal flow with no extra approval."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button disabled={busy || on} onClick={() => setVerification(true)}>
            {busy && !on ? "Saving…" : "Turn on"}
          </Button>
          <Button variant="outline" disabled={busy || !on} onClick={() => setVerification(false)}>
            {busy && on ? "Saving…" : "Turn off"}
          </Button>
          <p className="text-sm text-stone-600">
            {data ? `${data.pending_verifications} waiting for a manager` : "Loading…"}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdminPage() {
  return <RequireAuth role="admin">{() => <AdminHome />}</RequireAuth>;
}
