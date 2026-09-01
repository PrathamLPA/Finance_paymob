"use client";

import { useCallback, useEffect, useState } from "react";
import { Expand, X } from "lucide-react";
import { API_BASE, api, getToken } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Submission = {
  id: number;
  bitrix_lead_id: number;
  bitrix_estimate_id: number | null;
  installment_number: number;
  course_title: string | null;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  registrant_name: string | null;
  registrant_email: string | null;
  registrant_phone: string | null;
  course_for: string | null;
  due_amount: string;
  currency: string;
  status: string;
  has_proof: boolean;
  proof_url: string | null;
  proof_original_name: string | null;
  proof_content_type: string | null;
  review_note: string | null;
  course_total: string;
  amount_paid: string;
  remaining_balance: string;
  created_at: string | null;
};

function statusVariant(status: string) {
  if (status === "pending_review") return "warning" as const;
  if (status === "approved") return "success" as const;
  if (status === "rejected") return "default" as const;
  return "muted" as const;
}

function BankTransfersPage() {
  const [items, setItems] = useState<Submission[]>([]);
  const [selected, setSelected] = useState<Submission | null>(null);
  const [proofUrl, setProofUrl] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const refresh = useCallback(async () => {
    const res = await api<{ items: Submission[] }>("/api/staff/bank-transfers");
    setItems(res.items);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    async function loadProof() {
      setProofUrl(null);
      setFullscreen(false);
      if (!selected?.proof_url) return;
      try {
        const token = getToken();
        const res = await fetch(`${API_BASE}${selected.proof_url}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: "include",
        });
        if (!res.ok) throw new Error("Could not load receipt image");
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setProofUrl(objectUrl);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Proof load failed");
      }
    }

    loadProof();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selected]);

  useEffect(() => {
    if (!fullscreen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setFullscreen(false);
    }
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [fullscreen]);

  async function act(action: "approve" | "reject") {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Submission>(`/api/staff/bank-transfers/${selected.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ note: note || null }),
      });
      setSelected(updated);
      setNote("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const pending = items.filter((i) => i.status === "pending_review").length;
  const isPdf = selected?.proof_content_type === "application/pdf";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bank transfers"
        description="Review candidate receipts, then approve or reject payments."
      />

      <div className="flex gap-3 text-sm">
        <Badge variant="warning">{pending} pending review</Badge>
        <Badge variant="muted">{items.length} in queue</Badge>
      </div>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardContent className="px-0 pb-0 pt-0">
            <Table>
              <THead>
                <TR>
                  <TH>Customer</TH>
                  <TH>Installment</TH>
                  <TH>Amount</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {items.length === 0 ? (
                  <TR>
                    <TD colSpan={4} className="py-10 text-center text-stone-500">
                      No bank transfer submissions
                    </TD>
                  </TR>
                ) : (
                  items.map((row) => (
                    <TR
                      key={row.id}
                      className={
                        selected?.id === row.id
                          ? "cursor-pointer bg-teal-50"
                          : "cursor-pointer hover:bg-stone-50"
                      }
                      onClick={() => {
                        setSelected(row);
                        setNote(row.review_note || "");
                        setError("");
                      }}
                    >
                      <TD>
                        <div className="font-medium">
                          {row.registrant_name || row.customer_name || "—"}
                        </div>
                        <div className="text-xs text-stone-500">
                          Lead #{row.bitrix_lead_id}
                          {row.bitrix_estimate_id ? ` · Est #${row.bitrix_estimate_id}` : ""}
                        </div>
                        <div className="text-xs text-stone-500">{row.course_title || "—"}</div>
                      </TD>
                      <TD>I{row.installment_number}</TD>
                      <TD className="font-medium">{money(row.due_amount, row.currency)}</TD>
                      <TD>
                        <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
                      </TD>
                    </TR>
                  ))
                )}
              </TBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardContent className="space-y-4 pt-6">
            {!selected ? (
              <p className="text-sm text-stone-500">Select a submission to review the receipt.</p>
            ) : (
              <>
                <div>
                  <p className="font-medium text-stone-900">
                    {selected.registrant_name || selected.customer_name || "—"}
                  </p>
                  <p className="text-xs text-stone-500">
                    {selected.registrant_email || selected.customer_email || "—"}
                    {selected.registrant_phone || selected.customer_phone
                      ? ` · ${selected.registrant_phone || selected.customer_phone}`
                      : ""}
                  </p>
                  <p className="mt-1 text-sm">
                    {money(selected.due_amount, selected.currency)} · Installment{" "}
                    {selected.installment_number}
                  </p>
                  <p className="text-xs text-stone-500">
                    Paid {money(selected.amount_paid, selected.currency)} /{" "}
                    {money(selected.course_total, selected.currency)} · Left{" "}
                    {money(selected.remaining_balance, selected.currency)}
                  </p>
                </div>

                {selected.has_proof ? (
                  <div className="space-y-2">
                    <div className="overflow-hidden rounded-lg border border-stone-200 bg-stone-50">
                      {isPdf ? (
                        <a
                          className="block px-4 py-6 text-center text-sm text-teal-800 underline"
                          href={proofUrl || "#"}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open PDF receipt
                          {selected.proof_original_name
                            ? ` (${selected.proof_original_name})`
                            : ""}
                        </a>
                      ) : proofUrl ? (
                        <button
                          type="button"
                          className="group relative block w-full cursor-zoom-in text-left"
                          onClick={() => setFullscreen(true)}
                          aria-label="View receipt full screen"
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={proofUrl}
                            alt="Bank transfer receipt"
                            className="max-h-80 w-full object-contain transition group-hover:opacity-95"
                          />
                          <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-stone-900/50 to-transparent px-3 py-2 text-center text-xs font-medium text-white opacity-0 transition group-hover:opacity-100">
                            Click to view full screen
                          </span>
                        </button>
                      ) : (
                        <p className="px-4 py-6 text-center text-sm text-stone-500">
                          Loading receipt…
                        </p>
                      )}
                    </div>
                    {proofUrl && !isPdf ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={() => setFullscreen(true)}
                      >
                        <Expand className="mr-2 h-4 w-4" />
                        View full screen
                      </Button>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-sm text-stone-500">No receipt uploaded yet.</p>
                )}

                <label className="block text-sm">
                  <span className="mb-1 block text-stone-600">Note (optional)</span>
                  <textarea
                    className="min-h-20 w-full rounded-md border border-stone-300 px-3 py-2 text-sm"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    disabled={selected.status === "approved"}
                  />
                </label>

                {selected.status === "pending_review" ? (
                  <div className="flex gap-2">
                    <Button disabled={busy} onClick={() => act("approve")} className="flex-1">
                      Approve
                    </Button>
                    <Button
                      disabled={busy}
                      variant="outline"
                      onClick={() => act("reject")}
                      className="flex-1"
                    >
                      Reject
                    </Button>
                  </div>
                ) : (
                  <Badge variant={statusVariant(selected.status)}>{selected.status}</Badge>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {fullscreen && proofUrl && !isPdf ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-stone-950/90 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Receipt full screen"
          onClick={() => setFullscreen(false)}
        >
          <button
            type="button"
            className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
            onClick={() => setFullscreen(false)}
            aria-label="Close full screen"
          >
            <X className="h-5 w-5" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={proofUrl}
            alt="Bank transfer receipt full screen"
            className="max-h-[92vh] max-w-[96vw] rounded-md object-contain shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
          <p className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-white/70">
            Press Esc or click outside to close
          </p>
        </div>
      ) : null}
    </div>
  );
}

export default function ManagerBankTransfersPage() {
  return (
    <RequireAuth role="manager">{() => <BankTransfersPage />}</RequireAuth>
  );
}
