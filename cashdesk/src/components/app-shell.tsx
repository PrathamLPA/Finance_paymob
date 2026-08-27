"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Banknote, LayoutDashboard, LogOut, Users, Wallet } from "lucide-react";
import { api, setToken, type StaffUser } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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

  const links = isManager
    ? [
        { href: "/manager", label: "Dashboard", icon: LayoutDashboard },
        { href: "/manager/employees", label: "Employees", icon: Users },
        { href: "/employee", label: "Cash queue", icon: Banknote },
      ]
    : [
        { href: "/employee", label: "Collections", icon: Banknote },
        { href: "/employee/deposits", label: "Deposits", icon: Wallet },
      ];

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
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_#ecfdf5_0%,_#fafaf9_45%,_#f5f5f4_100%)]">
      <header className="border-b border-stone-200/80 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-6">
            <div>
              <p className="font-serif text-xl tracking-tight text-teal-950">Cash Desk</p>
              <p className="text-xs text-stone-500">Learners Point finance</p>
            </div>
            <nav className="hidden items-center gap-1 sm:flex">
              {links.map((link) => {
                const Icon = link.icon;
                const active = pathname === link.href;
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
                      active
                        ? "bg-teal-900 text-white"
                        : "text-stone-600 hover:bg-stone-100"
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {link.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <p className="text-sm font-medium text-stone-900">{user.name}</p>
              <p className="text-xs capitalize text-stone-500">{user.role}</p>
            </div>
            <Button variant="outline" size="sm" onClick={logout}>
              <LogOut className="h-4 w-4" />
              Logout
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
