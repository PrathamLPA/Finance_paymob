"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Deposit = {
  id: number;
  amount: string;
  currency: string;
  note: string | null;
  deposited_at: string | null;
};

type Summary = {
  on_hand: string;
  deposited: string;
  left_to_deposit: string;
  currency: string;
};

function DepositsPanel() {
  const [items, setItems] = useState<Deposit[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const [list, bal] = await Promise.all([
      api<{ items: Deposit[] }>("/api/staff/cash/deposits"),
      api<Summary>("/api/staff/cash/my-summary"),
    ]);
    setItems(list.items);
    setSummary(bal);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setOk("");
    setLoading(true);
    try {
      await api("/api/staff/cash/deposits", {
        method: "POST",
        body: JSON.stringify({ amount, note: note || null }),
      });
      setAmount("");
      setNote("");
      setOk("Deposit recorded");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deposit failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-serif text-3xl text-teal-950">Deposits</h1>
        <p className="mt-1 text-stone-600">
          Record cash you handed to the office or bank. On hand = collected − deposited.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Record deposit</CardTitle>
            <CardDescription>
              Available on hand: {money(summary?.on_hand, summary?.currency || "AED")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={onSubmit}>
              <div className="space-y-2">
                <Label htmlFor="amount">Amount (AED)</Label>
                <Input
                  id="amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="note">Note (optional)</Label>
                <Input id="note" value={note} onChange={(e) => setNote(e.target.value)} />
              </div>
              {error ? <p className="text-sm text-red-700">{error}</p> : null}
              {ok ? <p className="text-sm text-emerald-700">{ok}</p> : null}
              <Button type="submit" disabled={loading}>
                {loading ? "Saving…" : "Save deposit"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Balances</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-stone-500">On hand</span>
              <span className="font-medium">{money(summary?.on_hand)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-stone-500">Total deposited</span>
              <span className="font-medium">{money(summary?.deposited)}</span>
            </div>
            <div className="flex justify-between border-t border-stone-100 pt-3">
              <span className="text-stone-500">Left to deposit</span>
              <span className="font-semibold text-teal-900">
                {money(summary?.left_to_deposit)}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Deposit history</CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <Table>
            <THead>
              <TR>
                <TH>When</TH>
                <TH>Amount</TH>
                <TH>Note</TH>
              </TR>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <TR>
                  <TD colSpan={3} className="py-8 text-center text-stone-500">
                    No deposits yet
                  </TD>
                </TR>
              ) : (
                items.map((row) => (
                  <TR key={row.id}>
                    <TD>{row.deposited_at ? new Date(row.deposited_at).toLocaleString() : "—"}</TD>
                    <TD>{money(row.amount, row.currency)}</TD>
                    <TD>{row.note || "—"}</TD>
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

export default function DepositsPage() {
  return (
    <RequireAuth>
      {() => <DepositsPanel />}
    </RequireAuth>
  );
}
