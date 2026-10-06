"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Overview = {
  finance_manager_verification: boolean;
  pending_verifications: number;
};

function SettingsPage() {
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
        title="Settings"
        description="Turn the manager confirmation on while you are checking the flow. Turn it off when payments should continue on their own."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Only after manager confirmation</CardTitle>
          <CardDescription>
            When this is on, a recorded payment does not send the invoice, update Bitrix, or fire the
            follow-up trigger until a finance manager confirms it. When it is off, those steps run as
            soon as the payment is recorded.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-stone-900">{on ? "On" : "Off"}</p>
            <p className="text-sm text-stone-600">
              {data
                ? `${data.pending_verifications} payment${data.pending_verifications === 1 ? "" : "s"} waiting`
                : "Loading…"}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={on}
            aria-label="Only after manager confirmation"
            disabled={busy || data === null}
            onClick={() => setVerification(!on)}
            className={`inline-flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors disabled:opacity-50 ${
              on ? "justify-end bg-teal-800" : "justify-start bg-stone-300"
            }`}
          >
            <span className="block h-5 w-5 rounded-full bg-white shadow-sm" />
          </button>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3 text-sm text-stone-600">
        <span>Confirm or reject waiting payments on Finance check.</span>
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/verification">Open finance check</Link>
        </Button>
      </div>
    </div>
  );
}

export default function AdminSettingsPage() {
  return <RequireAuth role="admin">{() => <SettingsPage />}</RequireAuth>;
}
