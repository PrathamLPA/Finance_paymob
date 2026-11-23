"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getCachedUser, getToken, homeFor } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    const path = window.location.pathname.replace(/\/+$/, "");
    // Only the bare /finance address picks a home. Employee, manager, and admin
    // links must stay on the page that was opened.
    const onRoot = path.endsWith("/finance") || path === "";
    if (!onRoot) return;
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    router.replace(homeFor(getCachedUser()));
  }, [router]);
  return null;
}
