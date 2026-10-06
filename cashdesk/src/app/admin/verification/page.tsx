"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Item = {
  id: number;
  bitrix_lead_id: number;
  customer_name: string | null;
  channel: string | null;
  amount: string;
  currency: string;
  status: string;
  created_at: string | null;
  decided_by_name: string | null;
};

function VerificationQueue() {
  const [enabled, setEnabled] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    const res = await api<{ enabled: boolean; items: Item[] }>("/api/staff/admin/verifications");
    setEnabled(res.enabled);
    setItems(res.items);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load"));
  }, [refresh]);

  async function decide(id: number, action: "approve" | "reject") {
    setBusyId(id);
    setError("");
    try {
      await api(`/api/staff/admin/verifications/${id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ note: null }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  const pending = items.filter((item) => item.status === "pending");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Finance check"
        description={
          enabled
            ? "The switch is on. Approve a payment to send the invoice and update Bitrix. Reject leaves the money recorded and skips those steps."
            : "The switch is off. New payments continue on their own. Anything already waiting still needs a decision."
        }
      />
      {error ? <p className="text-sm text-red-700">{error}</p> : null}
      <Badge variant={enabled ? "warning" : "muted"}>
        {enabled ? "Check required" : "Check off"} · {pending.length} waiting
      </Badge>
      <Card>
        <CardContent className="px-0 pb-0 pt-0">
          <Table>
            <THead>
              <TR>
                <TH>Customer</TH>
                <TH>Channel</TH>
                <TH>Amount</TH>
                <TH>Status</TH>
                <TH></TH>
              </TR>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <TR>
                  <TD colSpan={5} className="py-10 text-center text-stone-500">
                    Nothing in the finance check
                  </TD>
                </TR>
              ) : (
                items.map((row) => (
                  <TR key={row.id}>
                    <TD>
                      <div className="font-medium">{row.customer_name || "Customer"}</div>
                      <div className="text-xs text-stone-500">Lead #{row.bitrix_lead_id}</div>
                    </TD>
                    <TD className="capitalize">{row.channel || "online"}</TD>
                    <TD>{money(row.amount, row.currency)}</TD>
                    <TD>
                      <Badge
                        variant={
                          row.status === "approved"
                            ? "success"
                            : row.status === "rejected"
                              ? "muted"
                              : "warning"
                        }
                      >
                        {row.status}
                      </Badge>
                    </TD>
                    <TD className="text-right">
                      {row.status === "pending" ? (
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busyId === row.id}
                            onClick={() => decide(row.id, "reject")}
                          >
                            Reject
                          </Button>
                          <Button
                            size="sm"
                            disabled={busyId === row.id}
                            onClick={() => decide(row.id, "approve")}
                          >
                            {busyId === row.id ? "Working…" : "Approve"}
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-stone-500">{row.decided_by_name || ""}</span>
                      )}
                    </TD>
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

export default function AdminVerificationPage() {
  return (
    <RequireAuth role="manager">{() => <VerificationQueue />}</RequireAuth>
  );
}
