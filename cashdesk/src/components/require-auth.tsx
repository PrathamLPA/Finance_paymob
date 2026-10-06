"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  getCachedUser,
  getToken,
  homeFor,
  isAuthError,
  setCachedUser,
  setToken,
  type StaffUser,
} from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";

function roleAllowed(userRole: string, required?: "manager" | "employee" | "admin"): boolean {
  if (!required) return true;
  if (required === "admin") return userRole === "admin";
  // Developer admin can open the manager screens as well.
  if (required === "manager") return userRole === "manager" || userRole === "admin";
  return userRole === required;
}

export function RequireAuth({
  role,
  children,
}: {
  role?: "manager" | "employee" | "admin";
  children: (user: StaffUser) => React.ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<StaffUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [failure, setFailure] = useState("");

  // The static export is pre-rendered without a user, so read the cache after
  // mount. This makes moving between pages instant instead of waiting on /me.
  useEffect(() => {
    const cached = getCachedUser();
    if (cached) setUser(cached);
  }, []);

  const verify = useCallback(async () => {
    if (!getToken()) {
      setCachedUser(null);
      router.replace("/login");
      return;
    }
    setFailure("");
    try {
      const me = await api<StaffUser>("/api/staff/me");
      setCachedUser(me);
      if (!roleAllowed(me.role, role)) {
        router.replace(homeFor(me));
        return;
      }
      setUser(me);
    } catch (err) {
      if (isAuthError(err)) {
        // Token expired or account disabled: clear it so / does not bounce back here.
        setToken(null);
        router.replace("/login");
        return;
      }
      // Network / server hiccup: keep the cached user on screen, else show retry.
      if (!getCachedUser()) {
        setFailure(err instanceof Error ? err.message : "Could not reach the server");
      }
    } finally {
      setChecking(false);
    }
  }, [router, role]);

  useEffect(() => {
    verify();
  }, [verify]);

  // Cached user with the wrong role: send them to their own home right away.
  useEffect(() => {
    if (user && !roleAllowed(user.role, role)) {
      router.replace(homeFor(user));
    }
  }, [user, role, router]);

  if (user && roleAllowed(user.role, role)) {
    return <AppShell user={user}>{children(user)}</AppShell>;
  }

  if (failure && !checking) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-stone-50 px-4 text-center">
        <p className="text-sm text-stone-700">{failure}</p>
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={() => {
              setChecking(true);
              verify();
            }}
          >
            Try again
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setToken(null);
              router.replace("/login");
            }}
          >
            Sign in again
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-stone-50 text-stone-500">
      Loading…
    </div>
  );
}
