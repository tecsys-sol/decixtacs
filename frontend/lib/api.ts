/**
 * Typed HTTP client for the NetworkOps Manager API.
 *
 * - Bearer access tokens with transparent refresh (refresh-token rotation: the new refresh
 *   token returned by /auth/refresh always replaces the old one).
 * - Refreshes are single-flight within a tab and serialised across tabs with the Web Locks
 *   API when available, so a rotated refresh token is never presented twice.
 * - Superusers can act inside another tenant via the X-Tenant header.
 */
import type { LoginIn, TokenOut } from "@/lib/types";

export const API_PREFIX = "/api/v1";

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  /** epoch milliseconds */
  expiresAt: number;
}

export interface TokenStorage {
  load(): AuthTokens | null;
  save(tokens: AuthTokens): void;
  clear(): void;
}

const STORAGE_KEY = "nom.auth";
const TENANT_KEY = "nom.tenant";
/** refresh this many ms before the access token expires */
const EXPIRY_SKEW_MS = 30_000;

function safeStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export const localTokenStorage: TokenStorage = {
  load() {
    const raw = safeStorage()?.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
      const t = JSON.parse(raw) as Partial<AuthTokens>;
      if (typeof t.accessToken === "string" && typeof t.refreshToken === "string" && typeof t.expiresAt === "number") {
        return t as AuthTokens;
      }
    } catch {
      /* corrupted entry */
    }
    return null;
  },
  save(tokens) {
    safeStorage()?.setItem(STORAGE_KEY, JSON.stringify(tokens));
  },
  clear() {
    safeStorage()?.removeItem(STORAGE_KEY);
  },
};

export const tenantStorage = {
  get(): string | null {
    return safeStorage()?.getItem(TENANT_KEY) || null;
  },
  set(slug: string | null) {
    const s = safeStorage();
    if (!s) return;
    if (slug) s.setItem(TENANT_KEY, slug);
    else s.removeItem(TENANT_KEY);
  },
};

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

/** Turn a FastAPI error body ({detail: string | {code,message} | ValidationError[]}) into an ApiError. */
export function toApiError(status: number, body: unknown, fallback: string): ApiError {
  const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : body;
  if (typeof detail === "string") return new ApiError(status, detail, detail);
  if (Array.isArray(detail)) {
    const msg = detail
      .map((d) => {
        if (d && typeof d === "object" && "msg" in d) {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc)
            ? (d as { loc: unknown[] }).loc.filter((p) => p !== "body").join(".")
            : "";
          return loc ? `${loc}: ${(d as { msg: string }).msg}` : (d as { msg: string }).msg;
        }
        return String(d);
      })
      .join("; ");
    return new ApiError(status, msg || fallback, detail);
  }
  if (detail && typeof detail === "object") {
    const d = detail as { code?: unknown; message?: unknown };
    const message = typeof d.message === "string" ? d.message : fallback;
    return new ApiError(status, message, detail, typeof d.code === "string" ? d.code : undefined);
  }
  return new ApiError(status, fallback, detail);
}

export type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue | QueryValue[]>;

export function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    const values = Array.isArray(value) ? value : [value];
    for (const v of values) {
      if (v === undefined || v === null || v === "") continue;
      params.append(key, String(v));
    }
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Query;
  body?: unknown;
  headers?: Record<string, string>;
  /** how to read a successful response body (default: json, 204 -> undefined) */
  responseType?: "json" | "text" | "blob";
  /** set false for endpoints that must not carry a bearer token (login/refresh) */
  auth?: boolean;
  signal?: AbortSignal;
}

export interface ApiClientOptions {
  baseUrl?: string;
  storage?: TokenStorage;
  fetch?: typeof fetch;
  getTenant?: () => string | null;
  /** called once when the session cannot be refreshed any more */
  onSessionExpired?: () => void;
  now?: () => number;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly storage: TokenStorage;
  private readonly fetchImpl: typeof fetch;
  private readonly getTenant: () => string | null;
  private readonly onSessionExpired?: () => void;
  private readonly now: () => number;
  private refreshing: Promise<AuthTokens> | null = null;

  constructor(opts: ApiClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? "").replace(/\/$/, "");
    this.storage = opts.storage ?? localTokenStorage;
    this.fetchImpl = opts.fetch ?? ((...args: Parameters<typeof fetch>) => globalThis.fetch(...args));
    this.getTenant = opts.getTenant ?? (() => null);
    this.onSessionExpired = opts.onSessionExpired;
    this.now = opts.now ?? Date.now;
  }

  url(path: string, query?: Query): string {
    const p = path.startsWith("/api/") ? path : `${API_PREFIX}${path.startsWith("/") ? path : `/${path}`}`;
    return `${this.baseUrl}${p}${buildQuery(query)}`;
  }

  isAuthenticated(): boolean {
    return this.storage.load() !== null;
  }

  /** Persist a token pair returned by login, refresh or the OIDC callback. */
  setSession(t: TokenOut): AuthTokens {
    const tokens: AuthTokens = {
      accessToken: t.access_token,
      refreshToken: t.refresh_token,
      expiresAt: this.now() + t.expires_in * 1000,
    };
    this.storage.save(tokens);
    return tokens;
  }

  async login(body: LoginIn): Promise<AuthTokens> {
    const out = await this.request<TokenOut>("/auth/login", { method: "POST", body, auth: false });
    return this.setSession(out);
  }

  async logout(): Promise<void> {
    const tokens = this.storage.load();
    this.storage.clear();
    if (!tokens) return;
    try {
      await this.request<void>("/auth/logout", {
        method: "POST",
        body: { refresh_token: tokens.refreshToken },
        auth: false,
        headers: { Authorization: `Bearer ${tokens.accessToken}` },
      });
    } catch {
      /* best effort - the session is gone locally either way */
    }
  }

  /** Exchange the refresh token for a new token pair. Concurrent callers share one request. */
  refresh(): Promise<AuthTokens> {
    if (!this.refreshing) {
      const staleRefreshToken = this.storage.load()?.refreshToken;
      this.refreshing = this.withCrossTabLock(() => this.doRefresh(staleRefreshToken)).finally(() => {
        this.refreshing = null;
      });
    }
    return this.refreshing;
  }

  private async withCrossTabLock<T>(fn: () => Promise<T>): Promise<T> {
    const locks = typeof navigator !== "undefined" ? (navigator as Navigator & { locks?: LockManager }).locks : undefined;
    if (locks?.request) return locks.request("nom-token-refresh", fn) as Promise<T>;
    return fn();
  }

  private async doRefresh(staleRefreshToken: string | undefined): Promise<AuthTokens> {
    const current = this.storage.load();
    if (!current) {
      this.expire();
      throw new ApiError(401, "Not signed in", null, "not_authenticated");
    }
    // Another tab rotated the pair while we were waiting for the lock.
    if (staleRefreshToken && current.refreshToken !== staleRefreshToken && current.expiresAt - EXPIRY_SKEW_MS > this.now()) {
      return current;
    }
    try {
      const out = await this.request<TokenOut>("/auth/refresh", {
        method: "POST",
        body: { refresh_token: current.refreshToken },
        auth: false,
      });
      return this.setSession(out);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        this.storage.clear();
        this.expire();
      }
      throw e;
    }
  }

  private expire() {
    this.onSessionExpired?.();
  }

  private async accessToken(): Promise<string | null> {
    const t = this.storage.load();
    if (!t) return null;
    if (t.expiresAt - EXPIRY_SKEW_MS <= this.now()) {
      return (await this.refresh()).accessToken;
    }
    return t.accessToken;
  }

  private async send(path: string, opts: RequestOptions, token: string | null): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
    let body: BodyInit | undefined;
    if (opts.body instanceof FormData) {
      body = opts.body;
    } else if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    if (token) headers.Authorization = `Bearer ${token}`;
    const tenant = this.getTenant();
    if (tenant && opts.auth !== false) headers["X-Tenant"] = tenant;
    return this.fetchImpl(this.url(path, opts.query), {
      method: opts.method ?? "GET",
      headers,
      body,
      signal: opts.signal,
      credentials: "same-origin",
    });
  }

  async request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const useAuth = opts.auth !== false;
    let token = useAuth ? await this.accessToken() : null;
    let res = await this.send(path, opts, token);

    if (res.status === 401 && useAuth && token) {
      // The access token was rejected (revoked, clock skew...) - refresh once and retry.
      const refreshed = await this.refresh();
      token = refreshed.accessToken;
      res = await this.send(path, opts, token);
      if (res.status === 401) {
        this.storage.clear();
        this.expire();
      }
    }

    if (!res.ok) {
      let payload: unknown = null;
      const text = await res.text().catch(() => "");
      try {
        payload = text ? JSON.parse(text) : null;
      } catch {
        payload = text;
      }
      throw toApiError(res.status, payload, res.statusText || `Request failed (${res.status})`);
    }

    if (res.status === 204) return undefined as T;
    switch (opts.responseType ?? "json") {
      case "text":
        return (await res.text()) as T;
      case "blob":
        return (await res.blob()) as T;
      default: {
        const text = await res.text();
        return (text ? JSON.parse(text) : undefined) as T;
      }
    }
  }

  get<T>(path: string, query?: Query, opts: Omit<RequestOptions, "method" | "query"> = {}) {
    return this.request<T>(path, { ...opts, method: "GET", query });
  }

  post<T>(path: string, body?: unknown, opts: Omit<RequestOptions, "method" | "body"> = {}) {
    return this.request<T>(path, { ...opts, method: "POST", body });
  }

  put<T>(path: string, body?: unknown, opts: Omit<RequestOptions, "method" | "body"> = {}) {
    return this.request<T>(path, { ...opts, method: "PUT", body });
  }

  patch<T>(path: string, body?: unknown, opts: Omit<RequestOptions, "method" | "body"> = {}) {
    return this.request<T>(path, { ...opts, method: "PATCH", body });
  }

  delete<T = void>(path: string, opts: Omit<RequestOptions, "method"> = {}) {
    return this.request<T>(path, { ...opts, method: "DELETE" });
  }

  /** Fetch a binary/text resource with auth headers and trigger a browser download. */
  async download(path: string, query: Query | undefined, filename: string): Promise<void> {
    const blob = await this.request<Blob>(path, { query, responseType: "blob", headers: { Accept: "*/*" } });
    const href = URL.createObjectURL(blob);
    try {
      const a = document.createElement("a");
      a.href = href;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    }
  }
}

type ExpiredListener = () => void;
const expiredListeners = new Set<ExpiredListener>();

export function onSessionExpired(listener: ExpiredListener): () => void {
  expiredListeners.add(listener);
  return () => expiredListeners.delete(listener);
}

/** App-wide client instance. */
export const api = new ApiClient({
  baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "",
  getTenant: () => tenantStorage.get(),
  onSessionExpired: () => expiredListeners.forEach((l) => l()),
});

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Unexpected error";
}
