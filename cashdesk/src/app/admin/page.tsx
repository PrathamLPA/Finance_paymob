"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
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

  const refresh = useCallback(async () => {
    const overview = await api<Overview>("/api/staff/admin/overview");
    setData(overview);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load"));
  }, [refresh]);

  const on = Boolean(data?.finance_manager_verification);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Control"
        description="Live counts for the finance flow. Manager confirmation is changed in Settings."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard label="Active people" value={String(data?.staff_total ?? "—")} icon={Users} />
        <StatCard label="Managers" value={String(data?.staff.manager ?? "—")} hint="Finance managers" icon={Users} accent="stone" />
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
              ? "On. Invoice, Bitrix updates, and the follow-up trigger wait until a finance manager confirms the payment."
              : "Off. Those steps run as soon as the payment is recorded."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button asChild variant="outline">
            <Link href="/admin/settings">Open settings</Link>
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
