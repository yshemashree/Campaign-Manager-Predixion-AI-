// Thin fetch wrapper: adds the bearer token, turns problem+json responses into ApiError.

const TOKEN_KEY = "cm.token";
export const API_BASE = "/api/v1";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

// Called when the API rejects the token, so the app can send the user back to login.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  readonly errors: FieldError[];

  constructor(status: number, title: string, detail: string, errors: FieldError[] = []) {
    super(detail || title);
    this.name = "ApiError";
    this.status = status;
    this.title = title;
    this.detail = detail;
    this.errors = errors;
  }

  /** Field path -> first message, e.g. {"retry_policy.max_attempts": "..."}. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.errors) {
      if (!(e.field in out)) out[e.field] = e.message;
    }
    return out;
  }
}

// Pydantic prefixes custom validator messages; the prefix means nothing to a user.
function cleanMessage(message: string): string {
  return message.replace(/^(Value error|Assertion failed), /, "");
}

async function toApiError(res: Response): Promise<ApiError> {
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("json")) {
    try {
      const body = (await res.json()) as {
        title?: string;
        detail?: unknown;
        errors?: { field?: string; message?: string }[];
      };
      const detail = typeof body.detail === "string" ? body.detail : res.statusText;
      const errors = (body.errors ?? []).map((e) => ({
        field: e.field ?? "",
        message: cleanMessage(e.message ?? "Invalid value"),
      }));
      return new ApiError(res.status, body.title ?? res.statusText, detail, errors);
    } catch {
      // fall through to the generic message
    }
  }
  if (res.status >= 500) {
    return new ApiError(res.status, "Server error", "The server ran into a problem. Try again in a moment.");
  }
  return new ApiError(res.status, res.statusText, `Request failed (${res.status})`);
}

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  body?: unknown;
  form?: FormData;
  query?: Query;
  signal?: AbortSignal;
}

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function send(method: string, path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), { method, headers, body, signal: opts.signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "Network error", "Can't reach the server. Check your connection and try again.");
  }

  if (res.status === 401 && token && onUnauthorized) onUnauthorized();
  if (!res.ok) throw await toApiError(res);
  return res;
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await send(method, path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body, query }),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, { body }),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, { body }),
  delete: (path: string) => request<void>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
  /** GET a file with the auth header and return it as a Blob plus the server's file name. */
  async blob(path: string): Promise<{ blob: Blob; filename: string | null }> {
    const res = await send("GET", path, {});
    const disposition = res.headers.get("content-disposition") ?? "";
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    return { blob: await res.blob(), filename: match ? match[1] : null };
  },
};

/** Field errors from any thrown value (empty unless it is an ApiError). */
export function fieldErrorsOf(error: unknown): Record<string, string> {
  return error instanceof ApiError ? error.fieldErrors() : {};
}
