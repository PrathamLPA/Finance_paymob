"use client";

import type { ReactNode } from "react";
import { Download } from "lucide-react";
import type { DatePeriod } from "@/lib/date-range";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type SortOption = { value: string; label: string };

const PERIODS: { value: DatePeriod; label: string }[] = [
  { value: "all", label: "All time" },
  { value: "day", label: "Today" },
  { value: "week", label: "This week" },
  { value: "month", label: "This month" },
  { value: "custom", label: "Custom dates" },
];

export function ListFilterBar({
  period,
  onPeriodChange,
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  sortBy,
  sortDir,
  sortOptions,
  onSortByChange,
  onSortDirChange,
  onExport,
  exportDisabled,
  exportLabel = "Export Excel",
  children,
}: {
  period: DatePeriod;
  onPeriodChange: (period: DatePeriod) => void;
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  sortBy: string;
  sortDir: "asc" | "desc";
  sortOptions: SortOption[];
  onSortByChange: (value: string) => void;
  onSortDirChange: (value: "asc" | "desc") => void;
  onExport: () => void;
  exportDisabled?: boolean;
  exportLabel?: string;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-stone-200/90 bg-white/80 p-3 sm:p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-stone-500">
          Filter
        </span>
        {PERIODS.map((p) => (
          <Button
            key={p.value}
            size="sm"
            variant={period === p.value ? "default" : "outline"}
            onClick={() => onPeriodChange(p.value)}
          >
            {p.label}
          </Button>
        ))}
      </div>

      {period === "custom" ? (
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1">
            <span className="block text-[11px] font-medium uppercase tracking-wide text-stone-500">
              From
            </span>
            <Input
              type="date"
              className="w-[11.5rem]"
              value={dateFrom}
              onChange={(e) => onDateFromChange(e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="block text-[11px] font-medium uppercase tracking-wide text-stone-500">
              To
            </span>
            <Input
              type="date"
              className="w-[11.5rem]"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => onDateToChange(e.target.value)}
            />
          </label>
        </div>
      ) : null}

      <div className="flex flex-wrap items-end gap-3 border-t border-stone-200/80 pt-3">
        <label className="space-y-1">
          <span className="block text-[11px] font-medium uppercase tracking-wide text-stone-500">
            Sort by
          </span>
          <select
            className="h-10 min-w-[10rem] rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-900 outline-none focus-visible:ring-2 focus-visible:ring-teal-700"
            value={sortBy}
            onChange={(e) => onSortByChange(e.target.value)}
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block text-[11px] font-medium uppercase tracking-wide text-stone-500">
            Order
          </span>
          <select
            className="h-10 min-w-[8rem] rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-900 outline-none focus-visible:ring-2 focus-visible:ring-teal-700"
            value={sortDir}
            onChange={(e) => onSortDirChange(e.target.value as "asc" | "desc")}
          >
            <option value="desc">Newest / high first</option>
            <option value="asc">Oldest / low first</option>
          </select>
        </label>

        {children}

        <div className="ml-auto flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={exportDisabled}
            onClick={onExport}
            className="gap-1.5"
          >
            <Download className="h-4 w-4" />
            {exportLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
