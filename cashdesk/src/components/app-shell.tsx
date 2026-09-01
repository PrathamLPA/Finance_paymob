"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowLeftRight,
  Banknote,
  LayoutDashboard,
  LogOut,
  Receipt,
  Users,
  Wallet,
} from "lucide-react";
import { api, setToken, type StaffUser } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ComponentType<{ className?: string }> };

export function AppShell({
  user,
  children,
}: {
  user: StaffUser;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const isManager = user.role === "manager";

  const managerLinks: NavItem[] = [
    { href: "/manager", label: "Overview", icon: LayoutDashboard },
    { href: "/manager/transactions", label: "Transactions", icon: ArrowLeftRight },
    { href: "/manager/cash-queue", label: "Cash queue", icon: Banknote },
    { href: "/manager/bank-transfers", label: "Bank transfers", icon: Receipt },
    { href: "/manager/deposits", label: "Deposits", icon: Wallet },
    { href: "/manager/employees", label: "Employees", icon: Users },
  ];

  const employeeLinks: NavItem[] = [
    { href: "/employee", label: "Collections", icon: Banknote },
    { href: "/employee/deposits", label: "Deposits", icon: Receipt },
  ];

  const links = isManager ? managerLinks : employeeLinks;

  function isActive(href: string) {
    if (href === "/manager" || href === "/employee") return pathname === href;
    return pathname.startsWith(href);
  }

  async function logout() {
    try {
      await api("/api/staff/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    setToken(null);
    router.replace("/login");
  }

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#f0fdfa_0%,#fafaf9_28%,#f5f5f4_100%)]">
      <div className="mx-auto flex min-h-screen max-w-7xl">
        <aside className="hidden w-64 shrink-0 border-r border-stone-200/80 bg-white/70 p-4 backdrop-blur md:flex md:flex-col">
          <div className="mb-8 px-2">
            <p className="font-serif text-2xl text-teal-950">Cash Desk</p>
            <p className="text-xs text-stone-500">Learners Point finance</p>
          </div>
          <nav className="flex flex-1 flex-col gap-1">
            {links.map((link) => {
              const Icon = link.icon;
              const active = isActive(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-teal-900 text-white shadow-sm"
                      : "text-stone-600 hover:bg-stone-100 hover:text-stone-900"
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="mt-4 border-t border-stone-200 pt-4">
            <p className="px-2 text-sm font-medium text-stone-900">{user.name}</p>
            <p className="px-2 text-xs capitalize text-stone-500">{user.role}</p>
            <Button variant="outline" size="sm" className="mt-3 w-full" onClick={logout}>
              <LogOut className="mr-2 h-4 w-4" />
              Logout
            </Button>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b border-stone-200/80 bg-white/80 px-4 py-3 backdrop-blur md:hidden">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-serif text-lg text-teal-950">Cash Desk</p>
                <p className="text-xs text-stone-500">{user.name}</p>
              </div>
              <Button variant="outline" size="sm" onClick={logout}>
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
            <nav className="mt-3 flex gap-1 overflow-x-auto pb-1">
              {links.map((link) => {
                const active = isActive(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={cn(
                      "whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium",
                      active ? "bg-teal-900 text-white" : "bg-stone-100 text-stone-600"
                    )}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
          </header>
          <main className="flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
