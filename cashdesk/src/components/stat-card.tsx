import { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  accent = "teal",
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  accent?: "teal" | "amber" | "sky" | "stone";
}) {
  const accents = {
    teal: "bg-teal-50 text-teal-800 ring-teal-100",
    amber: "bg-amber-50 text-amber-900 ring-amber-100",
    sky: "bg-sky-50 text-sky-900 ring-sky-100",
    stone: "bg-stone-100 text-stone-800 ring-stone-200",
  };
  return (
    <Card className="overflow-hidden border-stone-200/80 shadow-sm">
      <CardContent className="flex items-start gap-4 p-5">
        <div className={cn("rounded-xl p-3 ring-1", accents[accent])}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</p>
          <p className="mt-1 truncate text-2xl font-semibold text-stone-900">{value}</p>
          {hint ? <p className="mt-1 text-xs text-stone-500">{hint}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}
