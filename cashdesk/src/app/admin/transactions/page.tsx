"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { TransactionTable, type TxnRow } from "@/components/transaction-table";
import { Card, CardContent } from "@/components/ui/card";

function AdminTransactions() {
  const [items, setItems] = useState<TxnRow[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const tx = await api<{ items: TxnRow[] }>("/api/staff/transactions?channel=all&sort_by=paid_at&sort_dir=desc");
      setItems(tx.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load transactions"));
  }, [refresh]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transactions"
        description="Every recorded payment. Open a row to resend an invoice."
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}
      <Card>
        <CardContent className="px-0 pb-0 pt-0">
          {loading && items.length === 0 ? (
            <p className="py-10 text-center text-sm text-stone-500">Loading transactions…</p>
          ) : (
            <TransactionTable items={items} onUpdated={refresh} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdminTransactionsPage() {
  return <RequireAuth role="admin">{() => <AdminTransactions />}</RequireAuth>;
}
