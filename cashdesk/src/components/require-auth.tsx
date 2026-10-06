"use client";

import { useCallback, useEffect, useLayoutEffect, useState } from "react";
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

  // Apply the signed-in user before the browser paints, so a click does not
  // flash the full-screen "Loading…" placeholder.
  useLayoutEffect(() => {
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

  if (user && !roleAllowed(user.role, role)) {
    const needed =
      role === "admin" ? "a developer admin" : role === "manager" ? "a finance manager" : "an employee";
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-stone-50 px-4 text-center">
        <p className="max-w-md text-sm text-stone-700">
          This page is for {needed}. You are signed in as {user.name}, {user.role === "employee" ? "an employee" : `a ${user.role}`}.
        </p>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => router.replace(homeFor(user))}>
            Go to my page
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setToken(null);
              router.replace("/login");
            }}
          >
            Sign in as someone else
          </Button>
        </div>
      </div>
    );
  }

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
