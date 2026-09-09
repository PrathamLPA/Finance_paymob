/** Build calendar date strings (YYYY-MM-DD) in the user's local timezone. */

export type DatePeriod = "all" | "day" | "week" | "month" | "custom";

export type DateRange = {
  dateFrom: string;
  dateTo: string;
};

function pad(n: number) {
  return String(n).padStart(2, "0");
}

export function toDateInputValue(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function startOfWeek(d: Date): Date {
  const copy = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const day = copy.getDay(); // 0 Sun … 6 Sat
  const diff = day === 0 ? -6 : 1 - day; // Monday start
  copy.setDate(copy.getDate() + diff);
  return copy;
}

export function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function rangeForPeriod(period: DatePeriod, custom?: DateRange): DateRange | null {
  if (period === "all") return null;
  const today = new Date();
  const to = toDateInputValue(today);
  if (period === "day") {
    return { dateFrom: to, dateTo: to };
  }
  if (period === "week") {
    return { dateFrom: toDateInputValue(startOfWeek(today)), dateTo: to };
  }
  if (period === "month") {
    return { dateFrom: toDateInputValue(startOfMonth(today)), dateTo: to };
  }
  // custom
  if (!custom?.dateFrom || !custom?.dateTo) return null;
  return custom;
}
