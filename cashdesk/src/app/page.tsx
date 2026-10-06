"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getCachedUser, getToken, homeFor } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    router.replace(homeFor(getCachedUser()));
  }, [router]);
  return null;
}
