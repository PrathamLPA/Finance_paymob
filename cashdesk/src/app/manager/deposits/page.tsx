"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { rangeForPeriod, toDateInputValue, type DatePeriod } from "@/lib/date-range";
import { downloadExcelSheet } from "@/lib/excel-export";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { ListFilterBar } from "@/components/list-filter-bar";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Deposit = {
  id: number;
  employee_name: string | null;
  amount: string;
  currency: string;
  note: string | null;
  deposited_at: string | null;
  recorded_by_name: string | null;
};

const SORT_OPTIONS = [
  { value: "deposited_at", label: "Deposit date" },
  { value: "amount", label: "Amount" },
  { value: "employee_name", label: "Employee" },
];

function DepositsPage() {
  const [items, setItems] = useState<Deposit[]>([]);
  const [period, setPeriod] = useState<DatePeriod>("month");
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    return toDateInputValue(new Date(d.getFullYear(), d.getMonth(), 1));
  });
  const [dateTo, setDateTo] = useState(() => toDateInputValue(new Date()));
  const [sortBy, setSortBy] = useState("deposited_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [error, setError] = useState("");

  const activeRange = useMemo(
    () => rangeForPeriod(period, { dateFrom, dateTo }),
    [period, dateFrom, dateTo]
  );

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({ sort_by: sortBy, sort_dir: sortDir });
    if (activeRange?.dateFrom) params.set("date_from", activeRange.dateFrom);
    if (activeRange?.dateTo) params.set("date_to", activeRange.dateTo);
    const res = await api<{ items: Deposit[] }>(`/api/staff/cash/deposits?${params}`);
    setItems(res.items);
  }, [activeRange, sortBy, sortDir]);

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
      filename: `deposits-${activeRange?.dateFrom || "all"}-${activeRange?.dateTo || "all"}`,
      sheetName: "Deposits",
      headers: ["Deposited at", "Employee", "Amount", "Currency", "Note", "Recorded by"],
      rows: items.map((row) => [
        row.deposited_at ? new Date(row.deposited_at).toLocaleString() : "",
        row.employee_name || "",
        row.amount,
        row.currency,
        row.note || "",
        row.recorded_by_name || "",
      ]),
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Deposits"
        description="Cash handed to the office or bank. Filter by period, sort, and export to Excel."
      />

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
          <Table>
            <THead>
              <TR>
                <TH>When</TH>
                <TH>Employee</TH>
                <TH>Amount</TH>
                <TH>Note</TH>
                <TH>Recorded by</TH>
              </TR>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <TR>
                  <TD colSpan={5} className="py-10 text-center text-stone-500">
                    No deposits in this period
                  </TD>
                </TR>
              ) : (
                items.map((row) => (
                  <TR key={row.id}>
                    <TD className="whitespace-nowrap text-xs">
                      {row.deposited_at ? new Date(row.deposited_at).toLocaleString() : " - "}
                    </TD>
                    <TD>{row.employee_name || "-"}</TD>
                    <TD className="font-medium">{money(row.amount, row.currency)}</TD>
                    <TD className="text-stone-600">{row.note || "-"}</TD>
                    <TD>{row.recorded_by_name || "-"}</TD>
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

export default function ManagerDepositsPage() {
  return (
    <RequireAuth role="manager">{() => <DepositsPage />}</RequireAuth>
  );
}
