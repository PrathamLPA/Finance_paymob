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
  data_mode: "test" | "live";
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
    // Flip the switch at once; put it back if the server says no.
    setData((d) => (d ? { ...d, finance_manager_verification: enabled } : d));
    try {
      await api("/api/staff/admin/verification", {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      void refresh().catch(() => undefined);
    } catch (err) {
      setData((d) => (d ? { ...d, finance_manager_verification: !enabled } : d));
      setError(err instanceof Error ? err.message : "Could not update the switch");
    } finally {
      setBusy(false);
    }
  }

  const on = Boolean(data?.finance_manager_verification);
  const live = data?.data_mode === "live";
  const [confirmText, setConfirmText] = useState("");
  const [cleared, setCleared] = useState("");
  const phrase = live ? "DELETE LIVE DATA" : "CLEAR TEST DATA";

  async function setMode(next: "test" | "live") {
    const message =
      next === "live"
        ? "Switch to PRODUCTION data? Screens will start from zero and show only real payments. Test data is kept and comes back when you switch to test."
        : "Switch to TEST data? Screens will show only test payments. Production data is kept.";
    if (!window.confirm(message)) return;
    setBusy(true);
    setError("");
    setCleared("");
    const previous = data?.data_mode ?? "test";
    setData((d) => (d ? { ...d, data_mode: next } : d));
    try {
      await api("/api/staff/admin/data-mode", {
        method: "PUT",
        body: JSON.stringify({ mode: next }),
      });
      void refresh().catch(() => undefined);
    } catch (err) {
      setData((d) => (d ? { ...d, data_mode: previous } : d));
      setError(err instanceof Error ? err.message : "Could not switch the data mode");
    } finally {
      setBusy(false);
    }
  }

  async function clearData() {
    setBusy(true);
    setError("");
    setCleared("");
    try {
      const res = await api<{ deleted: Record<string, number> }>("/api/staff/admin/clear-data", {
        method: "POST",
        body: JSON.stringify({ confirm: confirmText }),
      });
      const total = Object.values(res.deleted).reduce((a, b) => a + b, 0);
      setCleared(`Cleared ${total} record${total === 1 ? "" : "s"} of ${live ? "production" : "test"} data.`);
      setConfirmText("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not clear the data");
    } finally {
      setBusy(false);
    }
  }

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
            className={`inline-flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors duration-200 disabled:opacity-50 ${
              on ? "bg-teal-800" : "bg-stone-300"
            }`}
          >
            <span className={`block h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200 ${on ? "translate-x-5" : "translate-x-0"}`} />
          </button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Production data</CardTitle>
          <CardDescription>
            Off: every payment, cash collection, bank transfer and email you create is test data. On:
            they are production data and the screens start from zero. The two sets are kept apart, so
            switching back and forth never mixes them. Bitrix, Zoho and Paymob are not switched: a test
            payment still reaches the real systems, so use test leads while this is off.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-stone-900">
              {data ? (live ? "On - production data" : "Off - test data") : "Loading..."}
            </p>
            <p className="text-sm text-stone-600">
              Do not switch while a customer is in the middle of paying.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={live}
            aria-label="Production data"
            disabled={busy || data === null}
            onClick={() => setMode(live ? "test" : "live")}
            className={`inline-flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors duration-200 disabled:opacity-50 ${
              live ? "bg-teal-800" : "bg-stone-300"
            }`}
          >
            <span className={`block h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200 ${live ? "translate-x-5" : "translate-x-0"}`} />
          </button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Clear {live ? "production" : "test"} payment data</CardTitle>
          <CardDescription>
            Permanently deletes every payment, cash collection, deposit, bank transfer, finance check and
            email of the {live ? "PRODUCTION" : "test"} data set, so collected goes back to 0. The other
            data set is not touched. Bitrix, Zoho and Google Drive are not changed.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-stone-600">
            Type <span className="font-mono font-semibold">{phrase}</span> to enable the button.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={phrase}
              className="h-9 w-64 rounded-md border border-stone-300 px-3 text-sm"
            />
            <Button variant="outline" disabled={busy || confirmText.trim() !== phrase} onClick={clearData}>
              Clear {live ? "production" : "test"} data
            </Button>
          </div>
          {cleared ? <p className="text-sm text-emerald-800">{cleared}</p> : null}
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
