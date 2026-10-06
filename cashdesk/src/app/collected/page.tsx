"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useDebounced } from "@/lib/use-debounced";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { CollectionReceipts, type CollectionReceipt, type CollectorRow } from "@/components/collectors-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type MethodFilter = "all" | "cash" | "pos";

function CollectedFromPage({ userId }: { userId: number }) {
  const [rows, setRows] = useState<CollectionReceipt[]>([]);
  const [people, setPeople] = useState<CollectorRow[]>([]);
  const [q, setQ] = useState("");
  const [method, setMethod] = useState<MethodFilter>("all");
  const [employeeId, setEmployeeId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const debouncedQ = useDebounced(q.trim(), 350);

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({ limit: "200" });
    if (debouncedQ) params.set("q", debouncedQ);
    if (method !== "all") params.set("method", method);
    if (employeeId) params.set("employee_id", employeeId);
    const res = await api<{ items: CollectionReceipt[] }>(`/api/staff/cash/receipts?${params}`);
    setRows(res.items);
  }, [debouncedQ, method, employeeId]);

  useEffect(() => {
    api<{ items: CollectorRow[] }>("/api/staff/cash/collectors")
      .then((res) => setPeople(res.items))
      .catch(() => setPeople([]));
  }, []);

  useEffect(() => {
    setLoading(true);
    refresh()
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load"))
      .finally(() => setLoading(false));
  }, [refresh]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Collected from"
        description="Each line is one desk payment: the employee, the customer, and the amount."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <div className="space-y-3 rounded-xl border border-stone-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-stone-500">How</span>
          {(
            [
              ["all", "All"],
              ["cash", "Cash"],
              ["pos", "POS"],
            ] as const
          ).map(([value, label]) => (
            <Button
              key={value}
              type="button"
              size="sm"
              variant={method === value ? "default" : "outline"}
              onClick={() => setMethod(value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[12rem] flex-1 space-y-1">
            <span className="block text-[11px] font-medium uppercase tracking-wide text-stone-500">
              Search
            </span>
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Customer, employee, or course"
            />
          </label>
          <label className="min-w-[12rem] space-y-1">
            <span className="block text-[11px] font-medium uppercase tracking-wide text-stone-500">
              Employee
            </span>
            <select
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
              className="flex h-10 w-full rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-900"
            >
              <option value="">Everyone</option>
              {people.map((person) => (
                <option key={person.employee_id} value={String(person.employee_id)}>
                  {person.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="text-xs text-stone-500">
          {loading ? "Loading…" : `${rows.length} payment${rows.length === 1 ? "" : "s"}`}
        </p>
      </div>

      <CollectionReceipts rows={rows} highlightId={userId} />
    </div>
  );
}

export default function CollectedPage() {
  return <RequireAuth>{(user) => <CollectedFromPage userId={user.id} />}</RequireAuth>;
}
