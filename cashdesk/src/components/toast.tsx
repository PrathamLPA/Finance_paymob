"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import { followJob } from "@/lib/jobs";

type Tone = "progress" | "success" | "warning" | "error" | "info";

type Toast = {
  id: number;
  tone: Tone;
  title: string;
  detail?: string;
  leaving?: boolean;
};

type ToastInput = Omit<Toast, "id" | "leaving">;

type TrackOptions = {
  /** Shown while the server finishes the work. */
  runningTitle: string;
  runningDetail?: string;
  doneTitle: string;
  /** Called when the job ends, whatever the result, so the screen can refresh. */
  onFinished?: () => void;
};

type ToastApi = {
  show: (toast: ToastInput) => number;
  update: (id: number, toast: Partial<ToastInput>) => void;
  dismiss: (id: number) => void;
  /** Follow a background job and report its result in one toast. */
  trackJob: (jobKey: string | null | undefined, options: TrackOptions) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const AUTO_CLOSE_MS: Partial<Record<Tone, number>> = {
  success: 4500,
  info: 4500,
  warning: 12000,
  error: 12000,
};

const ICONS = {
  progress: Loader2,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertTriangle,
  info: Info,
};

const TONE_STYLES: Record<Tone, string> = {
  progress: "border-sky-200 bg-white text-stone-800",
  success: "border-emerald-200 bg-emerald-50 text-emerald-950",
  warning: "border-amber-200 bg-amber-50 text-amber-950",
  error: "border-red-200 bg-red-50 text-red-950",
  info: "border-stone-200 bg-white text-stone-800",
};

const ICON_STYLES: Record<Tone, string> = {
  progress: "animate-spin text-sky-700",
  success: "text-emerald-700",
  warning: "text-amber-700",
  error: "text-red-700",
  info: "text-stone-600",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const remove = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
    // Play the exit animation, then drop it from the list.
    setToasts((list) => list.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 220);
  }, []);

  const arm = useCallback(
    (id: number, tone: Tone) => {
      const existing = timers.current.get(id);
      if (existing) clearTimeout(existing);
      const delay = AUTO_CLOSE_MS[tone];
      if (delay) timers.current.set(id, setTimeout(() => remove(id), delay));
    },
    [remove]
  );

  const show = useCallback(
    (toast: ToastInput) => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-3), { ...toast, id }]);
      arm(id, toast.tone);
      return id;
    },
    [arm]
  );

  const update = useCallback(
    (id: number, patch: Partial<ToastInput>) => {
      setToasts((list) => list.map((t) => (t.id === id ? { ...t, ...patch } : t)));
      if (patch.tone) arm(id, patch.tone);
    },
    [arm]
  );

  const trackJob = useCallback(
    (jobKey: string | null | undefined, options: TrackOptions) => {
      if (!jobKey) {
        // Everything already ran before the reply (or the payment is waiting for approval).
        show({ tone: "success", title: options.doneTitle });
        options.onFinished?.();
        return;
      }
      const id = show({
        tone: "progress",
        title: options.runningTitle,
        detail: options.runningDetail,
      });
      followJob(jobKey)
        .then((status) => {
          if (status.state === "problem" || status.state === "failed") {
            update(id, {
              tone: "warning",
              title: "Saved, but a follow-up step did not finish",
              detail: `${status.problems.join(" · ") || "See the server log."} Use "Create & send invoice" on the payment to retry.`,
            });
          } else {
            update(id, { tone: "success", title: options.doneTitle, detail: undefined });
          }
        })
        .catch(() => update(id, { tone: "info", title: options.doneTitle, detail: undefined }))
        .finally(() => options.onFinished?.());
    },
    [show, update]
  );

  useEffect(() => {
    const live = timers.current;
    return () => live.forEach((timer) => clearTimeout(timer));
  }, []);

  const api = useMemo<ToastApi>(
    () => ({ show, update, dismiss: remove, trackJob }),
    [show, update, remove, trackJob]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[1100] flex flex-col items-center gap-2 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:items-end sm:px-5 sm:pb-5"
        aria-live="polite"
      >
        {toasts.map((toast) => {
          const Icon = ICONS[toast.tone];
          return (
            <div
              key={toast.id}
              role={toast.tone === "error" ? "alert" : "status"}
              className={`cashdesk-toast pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-lg ${TONE_STYLES[toast.tone]} ${toast.leaving ? "cashdesk-toast-out" : ""}`}
            >
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${ICON_STYLES[toast.tone]}`} />
              <div className="min-w-0 flex-1">
                <p className="font-medium leading-snug">{toast.title}</p>
                {toast.detail ? (
                  <p className="mt-0.5 text-xs leading-relaxed opacity-80">{toast.detail}</p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => remove(toast.id)}
                aria-label="Dismiss"
                className="-mr-1 rounded-md p-1 opacity-60 transition hover:opacity-100"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
