import { TD, TR } from "@/components/ui/table";

/**
 * Placeholder table rows shown while data loads. They keep the table the same height as
 * real rows, so the page does not jump when the data arrives, and they avoid showing a
 * wrong "nothing here yet" message for a moment.
 */
export function SkeletonRows({ cols, rows = 4 }: { cols: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <TR key={r} aria-hidden="true">
          {Array.from({ length: cols }).map((__, c) => (
            <TD key={c}>
              <div
                className="cashdesk-skeleton h-4"
                style={{ width: `${c === 0 ? 70 : 45 + ((r * 7 + c * 13) % 40)}%` }}
              />
              {c === 0 ? <div className="cashdesk-skeleton mt-1.5 h-3 w-1/3" /> : null}
            </TD>
          ))}
        </TR>
      ))}
    </>
  );
}

/** A block of soft placeholder lines for cards and lists that are not tables. */
export function SkeletonBlock({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2 py-6" aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="cashdesk-skeleton h-4"
          style={{ width: `${90 - i * 18}%` }}
        />
      ))}
    </div>
  );
}
