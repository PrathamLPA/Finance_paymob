"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeftRight,
  Banknote,
  Coins,
  PiggyBank,
  Receipt,
  TrendingUp,
  Users,
  Wallet,
} from "lucide-react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Dashboard = {
  cash_on_hand: string;
  total_deposited: string;
  pending_collections: number;
  cash_collected: string;
  online_collected: string;
  employee_count: number;
};

const quickLinks = [
  { href: "/manager/transactions", label: "All transactions", icon: ArrowLeftRight },
  { href: "/manager/cash-queue", label: "Cash queue", icon: Banknote },
  { href: "/manager/bank-transfers", label: "Bank transfers", icon: Receipt },
  { href: "/manager/deposits", label: "Deposits", icon: Wallet },
  { href: "/manager/employees", label: "Team", icon: Users },
];

function ManagerOverview() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Dashboard>("/api/staff/dashboard")
      .then(setDash)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        description="High-level cash desk health. Drill into transactions, queue, deposits, or team from the sidebar."
      />

      {error ? <p className="text-sm text-red-700">{error}</p> : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard label="Cash on hand" value={money(dash?.cash_on_hand)} icon={Coins} accent="amber" />
        <StatCard label="Total deposited" value={money(dash?.total_deposited)} icon={PiggyBank} accent="teal" />
        <StatCard
          label="Pending collections"
          value={String(dash?.pending_collections ?? 0)}
          hint="Open or claimed, not yet collected"
          icon={Banknote}
          accent="stone"
        />
        <StatCard label="Cash collected" value={money(dash?.cash_collected)} icon={Wallet} accent="teal" />
        <StatCard label="Online collected" value={money(dash?.online_collected)} icon={TrendingUp} accent="sky" />
        <StatCard
          label="Active employees"
          value={String(dash?.employee_count ?? 0)}
          icon={Users}
          accent="stone"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Quick navigation</CardTitle>
          <CardDescription>Open a dedicated view instead of scrolling one long dashboard.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {quickLinks.map((link) => {
            const Icon = link.icon;
            return (
              <Button key={link.href} asChild variant="outline" className="h-auto justify-start py-4">
                <Link href={link.href} className="flex flex-col items-start gap-2">
                  <Icon className="h-5 w-5 text-teal-800" />
                  <span>{link.label}</span>
                </Link>
              </Button>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ManagerPage() {
  return (
    <RequireAuth role="manager">{() => <ManagerOverview />}</RequireAuth>
  );
}
