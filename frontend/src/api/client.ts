// Fetch wrapper: in-memory access token, transparent refresh via httpOnly cookie.
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

let accessToken: string | null = null;
let refreshing: Promise<string | null> | null = null;
let onLogout: (() => void) | null = null;

export function setAccessToken(t: string | null) {
  accessToken = t;
}
export function setLogoutHandler(fn: () => void) {
  onLogout = fn;
}

export class ApiError extends Error {
  status: number;
  errors: Record<string, string>;
  constructor(status: number, message: string, errors: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

export async function refreshToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/api/auth/refresh`, { method: "POST", credentials: "include" })
      .then(async (r) => (r.ok ? ((await r.json()).access_token as string) : null))
      .catch(() => null)
      .then((t) => {
        accessToken = t;
        refreshing = null;
        return t;
      });
  }
  return refreshing;
}

async function parseError(r: Response): Promise<ApiError> {
  let msg = `Request failed (${r.status})`;
  let errors: Record<string, string> = {};
  try {
    const body = await r.json();
    const d = body.detail;
    if (typeof d === "string") msg = d;
    else if (d && typeof d === "object") {
      msg = d.message ?? msg;
      errors = d.errors ?? {};
    }
    if (body.errors) errors = body.errors;
  } catch {
    /* not JSON */
  }
  if (r.status === 429 && msg.startsWith("Request failed")) msg = "Too many requests. Please wait and try again.";
  return new ApiError(r.status, msg, errors);
}

type Opts = { method?: string; body?: unknown; form?: FormData; auth?: boolean; raw?: boolean };

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const { method = "GET", body, form, auth = true, raw = false } = opts;
  const doFetch = () => {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
    return fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: "include",
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  };
  let r = await doFetch();
  if (r.status === 401 && auth) {
    const t = await refreshToken();
    if (t) r = await doFetch();
    else onLogout?.();
  }
  if (!r.ok) throw await parseError(r);
  if (raw) return r as unknown as T;
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

/** Download an authenticated file (e.g. Excel) via blob. */
export async function download(path: string, fallbackName: string) {
  const r = await api<Response>(path, { raw: true });
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Open a short-lived signed URL returned by the API (ID documents, receipts). */
export async function openSigned(path: string) {
  // Open the window synchronously so mobile browsers don't block it as a popup.
  const w = window.open("", "_blank");
  try {
    const { url } = await api<{ url: string }>(path);
    const full = url.startsWith("/") ? `${BASE}${url}` : url;
    if (w) w.location.href = full;
    else window.location.href = full;
  } catch (e) {
    w?.close();
    throw e;
  }
}
