"use client";

import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
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

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.75rem_1fr] gap-x-3 gap-y-1 border-b border-stone-200/70 py-2 last:border-b-0 sm:grid-cols-[7.5rem_1fr]">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="break-words text-sm text-stone-900">{value || "-"}</dd>
    </div>
  );
}

function BankTransferDetailModal({
  row,
  note,
  busy,
  error,
  proofUrl,
  onNoteChange,
  onClose,
  onApprove,
  onReject,
  onFullscreen,
}: {
  row: Submission;
  note: string;
  busy: boolean;
  error: string;
  proofUrl: string | null;
  onNoteChange: (value: string) => void;
  onClose: () => void;
  onApprove: () => void;
  onReject: () => void;
  onFullscreen: () => void;
}) {
  const titleId = useId();
  const [mounted, setMounted] = useState(false);
  const isPdf = row.proof_content_type === "application/pdf";
  const displayName = row.registrant_name || row.customer_name || "Customer";
  const isPending = row.status === "pending_review";

  useEffect(() => {
    setMounted(true);
    const prevOverflow = document.body.style.overflow;
    const prevPadding = document.body.style.paddingRight;
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbar > 0) document.body.style.paddingRight = `${scrollbar}px`;

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      document.body.style.paddingRight = prevPadding;
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  if (!mounted) return null;

  return createPortal(
    <div className="txn-modal" role="presentation">
      <button
        type="button"
        className="txn-modal-backdrop"
        aria-label="Close details"
        onClick={onClose}
      />
      <div
        className="txn-modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="txn-modal-header">
          <div className="min-w-0 pr-2">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-teal-800/70">
              Bank transfer details
            </p>
            <h2
              id={titleId}
              className="mt-1 truncate text-xl font-semibold tracking-tight text-stone-900"
            >
              {displayName}
            </h2>
            <p className="mt-1 text-sm text-stone-500">
              Lead #{row.bitrix_lead_id}
              {row.bitrix_estimate_id ? ` · Est #${row.bitrix_estimate_id}` : ""} ·{" "}
              {row.course_title || "No course title"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg border border-stone-200 bg-white/80 p-2 text-stone-600 transition hover:bg-white hover:text-stone-900"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="txn-modal-body">
          <section className="txn-modal-panel">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge variant="online">bank_transfer</Badge>
              <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
              {row.has_proof ? <Badge variant="cash">Receipt on file</Badge> : null}
            </div>
            <dl>
              <DetailRow
                label="Submitted"
                value={row.created_at ? new Date(row.created_at).toLocaleString() : " - "}
              />
              <DetailRow label="Installment" value={`I${row.installment_number}`} />
              <DetailRow label="Amount" value={money(row.due_amount, row.currency)} />
              <DetailRow label="Course total" value={money(row.course_total, row.currency)} />
              <DetailRow label="Amount paid" value={money(row.amount_paid, row.currency)} />
              <DetailRow label="Remaining" value={money(row.remaining_balance, row.currency)} />
              <DetailRow
                label="Email"
                value={row.registrant_email || row.customer_email || "-"}
              />
              <DetailRow
                label="Phone"
                value={row.registrant_phone || row.customer_phone || "-"}
              />
              {row.registrant_name &&
              row.customer_name &&
              row.registrant_name !== row.customer_name ? (
                <DetailRow label="Customer" value={row.customer_name} />
              ) : null}
              {row.review_note && !isPending ? (
                <DetailRow label="Review note" value={row.review_note} />
              ) : null}
            </dl>
          </section>

          <section className="txn-modal-panel">
            <h3 className="text-sm font-semibold text-stone-900">Transfer receipt</h3>
            <p className="mt-1 text-sm leading-relaxed text-stone-600">
              Review the uploaded bank receipt before approving or rejecting this payment.
            </p>
            {row.has_proof ? (
              <div className="mt-3 space-y-2">
                <div className="overflow-hidden rounded-lg border border-stone-200 bg-stone-50">
                  {isPdf ? (
                    <a
                      className="block px-4 py-6 text-center text-sm text-teal-800 underline"
                      href={proofUrl || "#"}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open PDF receipt
                      {row.proof_original_name ? ` (${row.proof_original_name})` : ""}
                    </a>
                  ) : proofUrl ? (
                    <button
                      type="button"
                      className="group relative block w-full cursor-zoom-in text-left"
                      onClick={onFullscreen}
                      aria-label="View receipt full screen"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={proofUrl}
                        alt="Bank transfer receipt"
                        className="max-h-56 w-full object-contain transition group-hover:opacity-95"
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
                    onClick={onFullscreen}
                  >
                    <Expand className="mr-2 h-4 w-4" />
                    View full screen
                  </Button>
                ) : null}
              </div>
            ) : (
              <p className="mt-3 text-sm text-stone-500">No receipt uploaded yet.</p>
            )}

            <label className="mt-4 block text-sm">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-stone-500">
                Note (optional)
              </span>
              <textarea
                className="min-h-20 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none ring-teal-700/30 focus:ring-2"
                value={note}
                onChange={(e) => onNoteChange(e.target.value)}
                disabled={row.status === "approved"}
                placeholder="Add a review note for approve or reject…"
              />
            </label>
            {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
          </section>
        </div>

        <footer className="txn-modal-footer">
          <Button variant="outline" onClick={onClose} className="min-w-[6.5rem]">
            Close
          </Button>
          {isPending ? (
            <>
              <Button
                disabled={busy}
                variant="outline"
                onClick={onReject}
                className="min-w-[6.5rem]"
              >
                {busy ? "Working…" : "Reject"}
              </Button>
              <Button disabled={busy} onClick={onApprove} className="min-w-[8rem]">
                {busy ? "Working…" : "Approve"}
              </Button>
            </>
          ) : null}
        </footer>
      </div>
    </div>,
    document.body
  );
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
    if (!selected) return;
    const fresh = items.find((item) => item.id === selected.id);
    if (fresh && fresh !== selected) setSelected(fresh);
  }, [items, selected]);

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
      if (e.key === "Escape") {
        e.stopPropagation();
        setFullscreen(false);
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
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

      {error && !selected ? <p className="text-sm text-red-700">{error}</p> : null}

      <Card>
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
                    className="cursor-pointer hover:bg-teal-50/60"
                    onClick={() => {
                      setSelected(row);
                      setNote(row.review_note || "");
                      setError("");
                    }}
                  >
                    <TD>
                      <div className="font-medium">
                        {row.registrant_name || row.customer_name || "-"}
                      </div>
                      <div className="text-xs text-stone-500">
                        Lead #{row.bitrix_lead_id}
                        {row.bitrix_estimate_id ? ` · Est #${row.bitrix_estimate_id}` : ""}
                      </div>
                      <div className="text-xs text-stone-500">{row.course_title || "-"}</div>
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

      {selected ? (
        <BankTransferDetailModal
          row={selected}
          note={note}
          busy={busy}
          error={error}
          proofUrl={proofUrl}
          onNoteChange={setNote}
          onClose={() => {
            setSelected(null);
            setError("");
            setFullscreen(false);
          }}
          onApprove={() => act("approve")}
          onReject={() => act("reject")}
          onFullscreen={() => setFullscreen(true)}
        />
      ) : null}

      {fullscreen && proofUrl && !isPdf ? (
        <div
          className="fixed inset-0 z-[1100] bg-stone-950/92 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Receipt full screen"
        >
          <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-white/10 bg-stone-950/80 px-4 py-3 backdrop-blur">
            <p className="truncate text-sm text-white/80">
              {selected?.proof_original_name || "Receipt"} - scroll to see full image
            </p>
            <button
              type="button"
              className="shrink-0 rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
              onClick={() => setFullscreen(false)}
              aria-label="Close full screen"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          <div
            className="h-[calc(100vh-3.5rem)] overflow-auto overscroll-contain p-4"
            onClick={() => setFullscreen(false)}
          >
            <div className="mx-auto flex min-h-full w-full max-w-5xl justify-center py-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={proofUrl}
                alt="Bank transfer receipt full screen"
                className="h-auto w-full max-w-full rounded-md object-contain shadow-2xl"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          </div>
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
