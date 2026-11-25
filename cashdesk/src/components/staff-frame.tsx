"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  getCachedUser,
  getToken,
  isAuthError,
  setCachedUser,
  setToken,
  type StaffUser,
} from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";

const StaffUserContext = createContext<StaffUser | null>(null);

/** The signed-in person, for pages rendered inside the staff frame. */
export function useStaffUser(): StaffUser | null {
  return useContext(StaffUserContext);
}

/**
 * One sidebar and header for every staff page.
 *
 * It lives in the shared layout, so moving between pages only swaps the content. The
 * sidebar is not rebuilt, the "test data" banner does not pop in again, and the person
 * is checked once instead of on every click.
 */
export function StaffFrame({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<StaffUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [failure, setFailure] = useState("");

  // Show the remembered person before the browser paints, so there is no "Loading" flash.
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
      // Network / server hiccup: keep the cached person on screen, else offer a retry.
      if (!getCachedUser()) {
        setFailure(err instanceof Error ? err.message : "Could not reach the server");
      }
    } finally {
      setChecking(false);
    }
  }, [router]);

  useEffect(() => {
    void verify();
  }, [verify]);

  if (user) {
    return (
      <StaffUserContext.Provider value={user}>
        <AppShell user={user}>{children}</AppShell>
      </StaffUserContext.Provider>
    );
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
              void verify();
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
