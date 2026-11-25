import { api } from "@/lib/api";

export type JobState = "running" | "done" | "problem" | "failed" | "unknown";

export type JobStatus = {
  key: string;
  label: string;
  state: JobState;
  problems: string[];
  seconds: number;
};

const FIRST_POLL_MS = 500;
const POLL_MS = 1000;
const GIVE_UP_MS = 120_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Follow work the server is finishing in the background (invoice, Bitrix, email).
 * Resolves with the final state. "unknown" means the server has no record of it,
 * which is normal once it finished a while ago, so it counts as finished.
 */
export async function followJob(
  key: string,
  onTick?: (status: JobStatus) => void
): Promise<JobStatus> {
  const startedAt = Date.now();
  let wait = FIRST_POLL_MS;
  for (;;) {
    await sleep(wait);
    wait = POLL_MS;
    let status: JobStatus;
    try {
      status = await api<JobStatus>(`/api/staff/jobs/${encodeURIComponent(key)}`);
    } catch {
      // A network blip while polling must not look like a failed payment.
      if (Date.now() - startedAt > GIVE_UP_MS) {
        return { key, label: "", state: "unknown", problems: [], seconds: 0 };
      }
      continue;
    }
    onTick?.(status);
    if (status.state !== "running") return status;
    if (Date.now() - startedAt > GIVE_UP_MS) return status;
  }
}
