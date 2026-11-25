import { StaffFrame } from "@/components/staff-frame";

// Every staff page (admin, manager, employee, collected) shares this one frame.
export default function StaffLayout({ children }: { children: React.ReactNode }) {
  return <StaffFrame>{children}</StaffFrame>;
}
