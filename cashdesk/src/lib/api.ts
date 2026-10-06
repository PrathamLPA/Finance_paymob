const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8001";
const TOKEN_KEY = "cashdesk_token";
const USER_KEY = "cashdesk_user";
/** Give up on a request after this long so pages never hang on "Loading…". */
const DEFAULT_TIMEOUT_MS = 40_000;
/** Uploads can be slow on mobile data; allow more time. */
const UPLOAD_TIMEOUT_MS = 120_000;

export type StaffUser = {
  id: number;
  email: string;
  name: string;
  role: "manager" | "employee" | string;
  is_active: boolean;
};

/** Thrown by api() for non-2xx responses. `status` is the HTTP status code. */
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isAuthError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 401 || err.status === 403);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  }
}

/** Last verified user, so pages can render instantly while /me re-checks in the background. */
export function getCachedUser(): StaffUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(USER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StaffUser;
    return parsed && typeof parsed.id === "number" && parsed.role ? parsed : null;
  } catch {
    return null;
  }
}

export function setCachedUser(user: StaffUser | null) {
  if (typeof window === "undefined") return;
  if (user) sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  else sessionStorage.removeItem(USER_KEY);
}

export function homeFor(user: StaffUser | null | undefined): string {
  return user?.role === "manager" ? "/manager" : "/employee";
}

function messageFromBody(data: unknown, fallback: string): string {
  const detail =
    data && typeof data === "object" && "detail" in data
      ? (data as { detail: unknown }).detail
      : undefined;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) =>
        d && typeof d === "object" && "msg" in d
          ? String((d as { msg: unknown }).msg)
          : JSON.stringify(d)
      )
      .join(", ");
  }
  return fallback;
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {});
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!headers.has("Content-Type") && options.body && !isFormData) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const controller = options.signal ? null : new AbortController();
  const timer = controller
    ? setTimeout(
        () => controller.abort(),
        isFormData ? UPLOAD_TIMEOUT_MS : DEFAULT_TIMEOUT_MS
      )
    : null;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      credentials: "include",
      signal: options.signal ?? controller?.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("The server took too long to respond. Please try again.");
    }
    throw new Error("Cannot reach the server. Check your connection and try again.");
  } finally {
    if (timer) clearTimeout(timer);
  }

  let data: unknown = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }

  if (!res.ok) {
    throw new ApiError(
      messageFromBody(data, res.statusText || "Request failed"),
      res.status
    );
  }
  return data as T;
}

/**
 * Download a private file (proof photo / receipt) with the staff token and
 * return an object URL the browser can show. Caller must revoke it.
 */
export async function fetchProtectedBlob(
  path: string,
  signal?: AbortSignal
): Promise<{ url: string; type: string }> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: "include",
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new Error("Cannot reach the server to load this file.");
  }
  if (!res.ok) {
    let message = "Could not load file";
    try {
      const body = await res.json();
      message = messageFromBody(body, message);
    } catch {
      /* keep default */
    }
    throw new ApiError(message, res.status);
  }
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type };
}

export { API_BASE };
