import { cn } from "@/lib/utils";

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  variant?: "default" | "success" | "warning" | "muted" | "cash" | "online";
}) {
  const styles = {
    default: "bg-stone-100 text-stone-700",
    success: "bg-emerald-100 text-emerald-800",
    warning: "bg-amber-100 text-amber-900",
    muted: "bg-stone-50 text-stone-500",
    cash: "bg-teal-100 text-teal-900",
    online: "bg-sky-100 text-sky-900",
  }[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        styles,
        className
      )}
      {...props}
    />
  );
}
