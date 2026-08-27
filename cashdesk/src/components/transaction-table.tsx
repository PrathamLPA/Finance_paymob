import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { money } from "@/lib/utils";

export type TxnRow = {
  id: number;
  channel: string;
  amount: string;
  currency: string;
  paid_at: string | null;
  bitrix_lead_id: number | null;
  customer_name: string | null;
  course_title: string | null;
  course_total: string | null;
  amount_paid: string | null;
  remaining_balance: string | null;
  employee_name: string | null;
  employee_email: string | null;
};

export function TransactionTable({ items }: { items: TxnRow[] }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>When</TH>
          <TH>Customer / course</TH>
          <TH>Channel</TH>
          <TH>Amount</TH>
          <TH>Paid / left</TH>
          <TH>Collector</TH>
        </TR>
      </THead>
      <TBody>
        {items.length === 0 ? (
          <TR>
            <TD colSpan={6} className="py-10 text-center text-stone-500">
              No transactions match your filters
            </TD>
          </TR>
        ) : (
          items.map((row) => (
            <TR key={row.id}>
              <TD className="whitespace-nowrap text-xs text-stone-600">
                {row.paid_at ? new Date(row.paid_at).toLocaleString() : "—"}
              </TD>
              <TD>
                <div className="font-medium text-stone-900">{row.customer_name || "—"}</div>
                <div className="text-xs text-stone-500">
                  Lead #{row.bitrix_lead_id ?? "—"} · {row.course_title || "—"}
                </div>
              </TD>
              <TD>
                <Badge variant={row.channel === "cash" ? "cash" : "online"}>{row.channel}</Badge>
              </TD>
              <TD className="font-semibold text-stone-900">{money(row.amount, row.currency)}</TD>
              <TD className="text-xs text-stone-600">
                <div>Total {money(row.course_total)}</div>
                <div>
                  {money(row.amount_paid)} paid · {money(row.remaining_balance)} left
                </div>
              </TD>
              <TD>
                <div className="text-sm">{row.employee_name || "—"}</div>
                <div className="text-xs text-stone-500">{row.employee_email || ""}</div>
              </TD>
            </TR>
          ))
        )}
      </TBody>
    </Table>
  );
}
