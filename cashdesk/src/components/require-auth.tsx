"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { type StaffUser } from "@/lib/api";
import { useStaffUser } from "@/components/staff-frame";

type Role = "manager" | "employee" | "admin";

function RoleLogin({ role }: { role?: Role }) {
  const router = useRouter();
  useEffect(() => {
    router.replace(role ? `/login?as=${role}` : "/login");
  }, [role, router]);
  return <div className="py-16 text-center text-stone-500">Sign in…</div>;
}

function roleAllowed(userRole: string, required?: Role): boolean {
  if (!required) return true;
  if (required === "admin") return userRole === "admin";
  // Developer admin can open the manager screens as well.
  if (required === "manager") return userRole === "manager" || userRole === "admin";
  return userRole === required;
}

/**
 * Page-level role check. The sidebar, header and sign-in check live once in the shared
 * staff frame (see StaffFrame); this only decides whether this person may see this page.
 */
export function RequireAuth({
  role,
  children,
}: {
  role?: Role;
  children: (user: StaffUser) => React.ReactNode;
}) {
  const user = useStaffUser();
  if (!user) return null;
  if (!roleAllowed(user.role, role)) return <RoleLogin role={role} />;
  return <>{children(user)}</>;
}
