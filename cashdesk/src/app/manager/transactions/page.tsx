"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { rangeForPeriod, toDateInputValue, type DatePeriod } from "@/lib/date-range";
import { downloadExcelSheet } from "@/lib/excel-export";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { ListFilterBar } from "@/components/list-filter-bar";
import { TransactionTable, type TxnRow } from "@/components/transaction-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const SORT_OPTIONS = [
  { value: "paid_at", label: "Paid date" },
  { value: "amount", label: "Amount" },
  { value: "customer_name", label: "Customer" },
  { value: "channel", label: "Channel" },
  { value: "course_title", label: "Course" },
];

function TransactionsPage() {
  const [items, setItems] = useState<TxnRow[]>([]);
  const [channel, setChannel] = useState<"all" | "cash" | "pos" | "online">("all");
  const [q, setQ] = useState("");
  const [period, setPeriod] = useState<DatePeriod>("month");
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    return toDateInputValue(new Date(d.getFullYear(), d.getMonth(), 1));
  });
  const [dateTo, setDateTo] = useState(() => toDateInputValue(new Date()));
  const [sortBy, setSortBy] = useState("paid_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [error, setError] = useState("");

  const activeRange = useMemo(
    () => rangeForPeriod(period, { dateFrom, dateTo }),
    [period, dateFrom, dateTo]
  );

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({ channel, sort_by: sortBy, sort_dir: sortDir });
    if (q.trim()) params.set("q", q.trim());
    if (activeRange?.dateFrom) params.set("date_from", activeRange.dateFrom);
    if (activeRange?.dateTo) params.set("date_to", activeRange.dateTo);
    const tx = await api<{ items: TxnRow[] }>(`/api/staff/transactions?${params}`);
    setItems(tx.items);
  }, [channel, q, activeRange, sortBy, sortDir]);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  function handlePeriodChange(next: DatePeriod) {
    setPeriod(next);
    if (next === "custom" && (!dateFrom || !dateTo)) {
      const today = toDateInputValue(new Date());
      setDateFrom(today);
      setDateTo(today);
    }
  }

  function exportExcel() {
    downloadExcelSheet({
      filename: `transactions-${activeRange?.dateFrom || "all"}-${activeRange?.dateTo || "all"}`,
      sheetName: "Transactions",
      headers: [
        "Paid at",
        "Customer",
        "Email",
        "Lead ID",
        "Course",
        "Channel",
        "Amount",
        "Currency",
        "Course total",
        "Amount paid",
        "Remaining",
        "Collector",
        "Txn ref",
        "Zoho invoice",
        "Invoice synced",
      ],
      rows: items.map((row) => [
        row.paid_at ? new Date(row.paid_at).toLocaleString() : "",
        row.customer_name || "",
        row.customer_email || "",
        row.bitrix_lead_id ?? "",
        row.course_title || "",
        row.channel,
        row.amount,
        row.currency,
        row.course_total || "",
        row.amount_paid || "",
        row.remaining_balance || "",
        row.employee_name || "",
        row.transaction_id || `#${row.id}`,
        row.zoho_invoice_id || "",
        row.invoice_synced ? "Yes" : "No",
      ]),
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transactions"
        description="Filter by day, week, month, or custom dates. Sort and export the current view to Excel."
      >
        {(["all", "cash", "pos", "online"] as const).map((c) => (
          <Button
            key={c}
            size="sm"
            variant={channel === c ? "default" : "outline"}
            onClick={() => setChannel(c)}
          >
            {c === "pos" ? "POS" : c}
          </Button>
        ))}
        <Input
          className="w-52"
          placeholder="Search customer, course…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </PageHeader>

      <ListFilterBar
        period={period}
        onPeriodChange={handlePeriodChange}
        dateFrom={dateFrom}
        dateTo={dateTo}
        onDateFromChange={setDateFrom}
        onDateToChange={setDateTo}
        sortBy={sortBy}
        sortDir={sortDir}
        sortOptions={SORT_OPTIONS}
        onSortByChange={setSortBy}
        onSortDirChange={setSortDir}
        onExport={exportExcel}
        exportDisabled={items.length === 0}
        exportLabel={`Export Excel (${items.length})`}
      />

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
