"use client";

import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, HandCoins, PiggyBank, Wallet, X } from "lucide-react";
import { API_BASE, api, getToken } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Collection = {
  id: number;
  bitrix_lead_id: number;
  installment_number: number;
  course_title: string | null;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  due_amount: string;
  collected_amount?: string;
  currency: string;
  status: string;
  claimed_by_id: number | null;
  collected_at?: string | null;
  course_total: string;
  amount_paid: string;
  remaining_balance: string;
  has_proof?: boolean;
  proof_url?: string | null;
  proof_original_name?: string | null;
  details_ready?: boolean;
  details_ready_at?: string | null;
};

type Summary = {
  on_hand: string;
  deposited: string;
  left_to_deposit: string;
  collected: string;
  currency: string;
};

type TabKey = "open" | "claimed" | "collected";

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.75rem_1fr] gap-x-3 gap-y-1 border-b border-stone-200/70 py-2 last:border-b-0 sm:grid-cols-[7.5rem_1fr]">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="break-words text-sm text-stone-900">{value || "—"}</dd>
    </div>
  );
}

function CollectionDetailModal({
  row,
  busy,
  proofFile,
  proofPreviewUrl,
  proofLoading,
  onProofChange,
  onClose,
  onClaim,
  onCollect,
}: {
  row: Collection;
  busy: boolean;
  proofFile: File | null;
  proofPreviewUrl: string | null;
  proofLoading: boolean;
  onProofChange: (file: File | null) => void;
  onClose: () => void;
  onClaim: () => void;
  onCollect: () => void;
}) {
  const titleId = useId();
  const [mounted, setMounted] = useState(false);

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

  const isOpen = row.status === "open";
  const isClaimed = row.status === "claimed";
  const isCollected = row.status === "collected";
  const detailsReady = Boolean(row.details_ready);

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
              Cash collection
            </p>
            <h2
              id={titleId}
              className="mt-1 truncate text-xl font-semibold tracking-tight text-stone-900"
            >
              {row.customer_name || "Customer"}
            </h2>
            <p className="mt-1 text-sm text-stone-500">
              Lead #{row.bitrix_lead_id} · {row.course_title || "No course title"}
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
              <Badge
                variant={
                  isCollected ? "success" : isClaimed ? "warning" : "muted"
                }
              >
                {row.status}
              </Badge>
              {detailsReady ? (
                <Badge variant="success">Form completed</Badge>
              ) : (
                <Badge variant="warning">Waiting for customer form</Badge>
              )}
              {row.has_proof ? <Badge variant="cash">Photo on file</Badge> : null}
            </div>
            {!detailsReady && !isCollected ? (
              <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                Customer must open the email link, fill name / email / phone, and accept
                Terms before you can claim or collect cash.
              </p>
            ) : null}
            <dl>
              <DetailRow label="Installment" value={`I${row.installment_number}`} />
              <DetailRow
                label={isCollected ? "Collected" : "Due"}
                value={money(
                  isCollected ? row.collected_amount || row.due_amount : row.due_amount,
                  row.currency
                )}
              />
              <DetailRow label="Course total" value={money(row.course_total, row.currency)} />
              <DetailRow label="Amount paid" value={money(row.amount_paid, row.currency)} />
              <DetailRow label="Remaining" value={money(row.remaining_balance, row.currency)} />
              <DetailRow label="Phone" value={row.customer_phone || "—"} />
              <DetailRow label="Email" value={row.customer_email || "—"} />
              {isCollected ? (
                <DetailRow
                  label="Collected at"
                  value={
                    row.collected_at ? new Date(row.collected_at).toLocaleString() : "—"
                  }
                />
              ) : null}
            </dl>
          </section>

          {isClaimed && detailsReady ? (
            <section className="txn-modal-panel">
              <h3 className="text-sm font-semibold text-stone-900">Collection photo</h3>
              <p className="mt-1 text-sm leading-relaxed text-stone-600">
                Upload a handover screenshot or photo before confirming cash received.
              </p>
              <label className="mt-3 block space-y-1.5">
                <span className="sr-only">Collection photo</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp,application/pdf"
                  className="block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-teal-800 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white"
                  onChange={(e) => onProofChange(e.target.files?.[0] || null)}
                />
                <span className="text-xs text-stone-500">
                  {proofFile
                    ? proofFile.name
                    : "JPG, PNG, WEBP, or PDF — max 8MB. Required before confirming."}
                </span>
              </label>
            </section>
          ) : null}

          {isCollected && row.has_proof ? (
            <section className="txn-modal-panel">
              <h3 className="text-sm font-semibold text-stone-900">Proof on file</h3>
              <p className="mt-1 text-xs text-stone-500">
                {row.proof_original_name || "Attached photo"}
              </p>
              {proofLoading ? (
                <p className="mt-3 text-sm text-stone-500">Loading photo…</p>
              ) : proofPreviewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={proofPreviewUrl}
                  alt="Collection proof"
                  className="mt-3 max-h-56 w-full rounded-lg border border-stone-200 object-contain bg-stone-50"
                />
              ) : (
                <a
                  className="mt-3 inline-block text-sm font-medium text-teal-800 underline"
                  href={`${API_BASE}${row.proof_url}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open proof file
                </a>
              )}
            </section>
          ) : null}
        </div>

        <footer className="txn-modal-footer">
          <Button variant="outline" onClick={onClose} className="min-w-[6.5rem]">
            Close
          </Button>
          {isOpen ? (
            <Button
              disabled={busy || !detailsReady}
              onClick={onClaim}
              className="min-w-[10rem]"
            >
              {busy
                ? "Claiming…"
                : detailsReady
                  ? "Claim this collection"
                  : "Waiting for form"}
            </Button>
          ) : null}
          {isClaimed ? (
            <Button
              disabled={busy || !proofFile || !detailsReady}
              onClick={onCollect}
              className="min-w-[10rem]"
            >
              {busy
                ? "Saving…"
                : detailsReady
                  ? "Confirm cash received"
                  : "Waiting for form"}
            </Button>
          ) : null}
        </footer>
      </div>
    </div>,
    document.body
  );
}

function CollectionCard({
  row,
  accent,
  onOpen,
}: {
  row: Collection;
  accent?: "amber" | "teal";
  onOpen: () => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition hover:border-teal-300/80 hover:shadow-sm ${
        accent === "amber"
          ? "border-amber-200/80 bg-amber-50/30"
          : accent === "teal"
            ? "border-teal-200/80 bg-teal-50/20"
            : ""
      }`}
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-lg">{row.customer_name || "Customer"}</CardTitle>
            <CardDescription>
              Lead #{row.bitrix_lead_id} · {row.course_title || "Course"}
            </CardDescription>
          </div>
          <Badge
            variant={
              row.status === "collected"
                ? "success"
                : row.status === "claimed"
                  ? "warning"
                  : "muted"
            }
          >
            {row.status}
          </Badge>
        </div>
        {!row.details_ready && row.status !== "collected" ? (
          <p className="mt-2 text-xs font-medium text-amber-800">Waiting for customer form</p>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-stone-500">Installment</p>
            <p className="font-medium">I{row.installment_number}</p>
          </div>
          <div>
            <p className="text-stone-500">
              {row.status === "collected" ? "Collected" : "Amount due"}
            </p>
            <p className="font-semibold text-teal-900">
              {money(
                row.status === "collected"
                  ? row.collected_amount || row.due_amount
                  : row.due_amount,
                row.currency
              )}
            </p>
          </div>
        </div>
        <p className="text-xs text-stone-500">Tap to open details</p>
      </CardContent>
    </Card>
  );
}

function EmployeeDesk({ userId }: { userId: number }) {
  const [items, setItems] = useState<Collection[]>([]);
  const [collectedItems, setCollectedItems] = useState<Collection[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tab, setTab] = useState<TabKey>("open");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Collection | null>(null);
  const [proofFile, setProofFile] = useState<File | null>(null);
  const [proofPreviewUrl, setProofPreviewUrl] = useState<string | null>(null);
  const [proofLoading, setProofLoading] = useState(false);

  const refresh = useCallback(async () => {
    const [queue, collected, bal] = await Promise.all([
      api<{ items: Collection[] }>("/api/staff/cash/queue"),
      api<{ items: Collection[] }>("/api/staff/cash/collected?limit=50"),
      api<Summary>("/api/staff/cash/my-summary"),
    ]);
    setItems(queue.items);
    setCollectedItems(collected.items);
    setSummary(bal);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;

    async function loadProof() {
      setProofPreviewUrl(null);
      if (!selected?.has_proof || !selected.proof_url || selected.status !== "collected") {
        setProofLoading(false);
        return;
      }
      setProofLoading(true);
      try {
        const token = getToken();
        const res = await fetch(`${API_BASE}${selected.proof_url}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: "include",
        });
        if (!res.ok) throw new Error("Could not load proof");
        const blob = await res.blob();
        if (cancelled) return;
        if (!blob.type.startsWith("image/")) {
          setProofLoading(false);
          return;
        }
        const url = URL.createObjectURL(blob);
        revoked = url;
        setProofPreviewUrl(url);
      } catch {
        if (!cancelled) setProofPreviewUrl(null);
      } finally {
        if (!cancelled) setProofLoading(false);
      }
    }

    loadProof();
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [selected]);

  function openRow(row: Collection) {
    setSelected(row);
    setProofFile(null);
    setError("");
  }

  async function claim(id: number) {
    setBusyId(id);
    setError("");
    setSuccess("");
    try {
      await api(`/api/staff/cash/${id}/claim`, { method: "POST" });
      setSuccess("Case claimed. Upload a photo, then confirm cash received.");
      await refresh();
      setTab("claimed");
      const queue = await api<{ items: Collection[] }>("/api/staff/cash/queue");
      const updated = queue.items.find((i) => i.id === id) || null;
      setSelected(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Claim failed");
    } finally {
      setBusyId(null);
    }
  }

  async function collect(id: number) {
    if (!proofFile) {
      setError("Please attach a photo or screenshot before confirming cash received.");
      return;
    }
    setBusyId(id);
    setError("");
    setSuccess("");
    try {
      const body = new FormData();
      body.append("proof", proofFile);
      await api(`/api/staff/cash/${id}/collect`, { method: "POST", body });
      setSuccess("Cash recorded with photo. Bitrix lead timeline and assigned agent were notified.");
      setProofFile(null);
      setSelected(null);
      setTab("collected");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collect failed");
    } finally {
      setBusyId(null);
    }
  }

  const open = items.filter((i) => i.status === "open");
  const mine = items.filter((i) => i.status === "claimed" && i.claimed_by_id === userId);

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "open", label: "Open", count: open.length },
    { key: "claimed", label: "Claimed", count: mine.length },
    { key: "collected", label: "Collected", count: collectedItems.length },
  ];

  const list =
    tab === "open" ? open : tab === "claimed" ? mine : collectedItems;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Collections"
        description="Cases appear when Bitrix is cash. Customer must fill the email link and accept Terms before you can claim or collect."
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Cash in hand" value={money(summary?.on_hand, summary?.currency)} icon={HandCoins} accent="amber" />
        <StatCard label="Deposited" value={money(summary?.deposited, summary?.currency)} icon={PiggyBank} accent="teal" />
        <StatCard label="Left to deposit" value={money(summary?.left_to_deposit, summary?.currency)} icon={Wallet} accent="stone" />
      </div>

      {error ? <p className="text-sm text-red-700">{error}</p> : null}
      {success ? (
        <p className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {success}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
              tab === t.key
                ? "bg-teal-900 text-white"
                : "bg-stone-100 text-stone-600 hover:bg-stone-200"
            }`}
          >
            {t.label}
            <span className="ml-1.5 opacity-70">{t.count}</span>
          </button>
        ))}
      </div>

      <section className="space-y-3">
        {list.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-stone-500">
              {tab === "open"
                ? "No open cash cases right now"
                : tab === "claimed"
                  ? "No claimed cases — claim one from Open"
                  : "No collected cases yet"}
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {list.map((row) => (
              <CollectionCard
                key={row.id}
                row={row}
                accent={
                  row.status === "claimed"
                    ? "amber"
                    : row.status === "collected"
                      ? "teal"
                      : undefined
                }
                onOpen={() => openRow(row)}
              />
            ))}
          </div>
        )}
      </section>

      {selected ? (
        <CollectionDetailModal
          row={selected}
          busy={busyId === selected.id}
          proofFile={proofFile}
          proofPreviewUrl={proofPreviewUrl}
          proofLoading={proofLoading}
          onProofChange={setProofFile}
          onClose={() => {
            setSelected(null);
            setProofFile(null);
          }}
          onClaim={() => claim(selected.id)}
          onCollect={() => collect(selected.id)}
        />
      ) : null}
    </div>
  );
}

export default function EmployeePage() {
  return (
    <RequireAuth>
      {(user) => <EmployeeDesk userId={user.id} />}
    </RequireAuth>
  );
}
