"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken, type StaffUser } from "@/lib/api";
import { AppShell } from "@/components/app-shell";

export function RequireAuth({
  role,
  children,
}: {
  role?: "manager" | "employee";
  children: (user: StaffUser) => React.ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<StaffUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!getToken()) {
        router.replace("/login");
        return;
      }
      try {
        const me = await api<StaffUser>("/api/staff/me");
        if (cancelled) return;
        if (role === "manager" && me.role !== "manager") {
          router.replace("/employee");
          return;
        }
        setUser(me);
      } catch {
        router.replace("/login");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [router, role]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-stone-50 text-stone-500">
        Loading…
      </div>
    );
  }

  return <AppShell user={user}>{children(user)}</AppShell>;
}
