"use client";

import { money } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export type CollectionReceipt = {
  id: number;
  employee_id: number;
  employee_name: string;
  customer_name: string;
  amount: string;
  currency: string;
  collect_method: string;
  collected_at: string | null;
  course_title: string | null;
  bitrix_lead_id: number;
  installment_number: number;
};

export function CollectionReceipts({
  rows,
  highlightId,
}: {
  rows: CollectionReceipt[];
  highlightId?: number;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Who collected from whom</CardTitle>
        <CardDescription>
          Employee, customer, and amount for each desk payment.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        <Table>
          <THead>
            <TR>
              <TH>Collected by</TH>
              <TH>From</TH>
              <TH>Amount</TH>
              <TH>How</TH>
              <TH>When</TH>
            </TR>
          </THead>
          <TBody>
            {rows.length === 0 ? (
              <TR>
                <TD colSpan={5} className="py-8 text-center text-stone-500">
                  No collections recorded yet
                </TD>
              </TR>
            ) : (
              rows.map((row) => (
                <TR
                  key={row.id}
                  className={row.employee_id === highlightId ? "bg-teal-50/80" : undefined}
                >
                  <TD className="font-medium">
                    {row.employee_name}
                    {row.employee_id === highlightId ? (
                      <span className="ml-2 text-xs font-normal text-teal-800">You</span>
                    ) : null}
                  </TD>
                  <TD>
                    {row.customer_name}
                    <div className="text-xs text-stone-500">
                      Lead {row.bitrix_lead_id}
                      {row.installment_number > 1 ? ` · installment ${row.installment_number}` : ""}
                      {row.course_title ? ` · ${row.course_title}` : ""}
                    </div>
                  </TD>
                  <TD className="font-medium">{money(row.amount, row.currency)}</TD>
                  <TD>{row.collect_method === "pos" ? "POS" : "Cash"}</TD>
                  <TD className="text-stone-600">
                    {row.collected_at ? new Date(row.collected_at).toLocaleString() : "—"}
                  </TD>
                </TR>
              ))
            )}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export type CollectorRow = {
  employee_id: number;
  name: string;
  cash_collected: string;
  pos_collected: string;
  cash_count: number;
  pos_count: number;
  on_hand?: string;
};

export function CollectorsTable({
  rows,
  highlightId,
  showOnHand,
  emptyLabel = "No collections recorded yet",
}: {
  rows: CollectorRow[];
  highlightId?: number;
  showOnHand?: boolean;
  emptyLabel?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Who collected how much</CardTitle>
        <CardDescription>
          Cash adds to what that person still has to deposit. POS is the card machine and stays out of cash in hand.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        <Table>
          <THead>
            <TR>
              <TH>Employee</TH>
              <TH>Cash collected</TH>
              <TH>POS collected</TH>
              <TH>Cases</TH>
              {showOnHand ? <TH>Still on hand</TH> : null}
            </TR>
          </THead>
          <TBody>
            {rows.length === 0 ? (
              <TR>
                <TD colSpan={showOnHand ? 5 : 4} className="py-8 text-center text-stone-500">
                  {emptyLabel}
                </TD>
              </TR>
            ) : (
              rows.map((row) => (
                <TR
                  key={row.employee_id}
                  className={row.employee_id === highlightId ? "bg-teal-50/80" : undefined}
                >
                  <TD className="font-medium">
                    {row.name}
                    {row.employee_id === highlightId ? (
                      <span className="ml-2 text-xs font-normal text-teal-800">You</span>
                    ) : null}
                  </TD>
                  <TD>
                    {money(row.cash_collected)}
                    <div className="text-xs text-stone-500">{row.cash_count} cash</div>
                  </TD>
                  <TD>
                    {money(row.pos_collected)}
                    <div className="text-xs text-stone-500">{row.pos_count} POS</div>
                  </TD>
                  <TD>{row.cash_count + row.pos_count}</TD>
                  {showOnHand ? <TD className="font-medium">{money(row.on_hand)}</TD> : null}
                </TR>
              ))
            )}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}
