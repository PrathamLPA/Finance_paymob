"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { TransactionTable, type TxnRow } from "@/components/transaction-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

function TransactionsPage() {
  const [items, setItems] = useState<TxnRow[]>([]);
  const [channel, setChannel] = useState<"all" | "cash" | "online">("all");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({ channel });
    if (q.trim()) params.set("q", q.trim());
    const tx = await api<{ items: TxnRow[] }>(`/api/staff/transactions?${params}`);
    setItems(tx.items);
  }, [channel, q]);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transactions"
        description="Every payment recorded — see invoice status, create/resend Zoho + Bitrix + email, and filter cash vs online."
      >
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
          className="w-52"
          placeholder="Search customer, course…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </PageHeader>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
        <CardContent className="px-0 pb-0 pt-0">
          <TransactionTable items={items} onUpdated={refresh} />
        </CardContent>
      </Card>
    </div>
  );
}

export default function ManagerTransactionsPage() {
  return (
    <RequireAuth role="manager">{() => <TransactionsPage />}</RequireAuth>
  );
}
