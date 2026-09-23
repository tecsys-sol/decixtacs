import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, buildQuery, errorMessage, type AuthTokens, type TokenStorage } from "@/lib/api";

function memoryStorage(initial: AuthTokens | null): TokenStorage & { value: AuthTokens | null } {
  const s = {
    value: initial,
    load: () => s.value,
    save: (t: AuthTokens) => {
      s.value = t;
    },
    clear: () => {
      s.value = null;
    },
  };
  return s;
}

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const NOW = 1_700_000_000_000;

describe("ApiClient token handling", () => {
  it("sends the bearer token and tenant header", async () => {
    const storage = memoryStorage({ accessToken: "A1", refreshToken: "R1", expiresAt: NOW + 600_000 });
    const fetchMock = vi.fn(async () => json(200, { ok: true }));
    const client = new ApiClient({ storage, fetch: fetchMock, now: () => NOW, getTenant: () => "acme" });

    await expect(client.get("/devices", { q: "edge", site_id: undefined })).resolves.toEqual({ ok: true });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/devices?q=edge");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer A1");
    expect(headers["X-Tenant"]).toBe("acme");
  });

  it("refreshes an expired access token before the request and stores the rotated refresh token", async () => {
    const storage = memoryStorage({ accessToken: "A1", refreshToken: "R1", expiresAt: NOW - 1 });
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/refresh")) {
        expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: "R1" });
        return json(200, { access_token: "A2", refresh_token: "R2", expires_in: 900 });
      }
      return json(200, { auth: (init?.headers as Record<string, string>).Authorization });
    });
    const client = new ApiClient({ storage, fetch: fetchMock as unknown as typeof fetch, now: () => NOW });

    await expect(client.get("/auth/me")).resolves.toEqual({ auth: "Bearer A2" });
    expect(storage.value).toEqual({ accessToken: "A2", refreshToken: "R2", expiresAt: NOW + 900_000 });
  });

  it("retries once with a new token after a 401 and shares a single refresh between concurrent requests", async () => {
    const storage = memoryStorage({ accessToken: "A1", refreshToken: "R1", expiresAt: NOW + 600_000 });
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/refresh")) {
        refreshCalls++;
        await new Promise((r) => setTimeout(r, 5));
        return json(200, { access_token: "A2", refresh_token: "R2", expires_in: 900 });
      }
      const auth = (init?.headers as Record<string, string>).Authorization;
      return auth === "Bearer A2" ? json(200, { url }) : json(401, { detail: "token revoked" });
    });
    const client = new ApiClient({ storage, fetch: fetchMock as unknown as typeof fetch, now: () => NOW });

    const [a, b] = await Promise.all([client.get("/devices"), client.get("/backups")]);
    expect(a).toEqual({ url: "/api/v1/devices" });
    expect(b).toEqual({ url: "/api/v1/backups" });
    expect(refreshCalls).toBe(1);
    expect(storage.value?.refreshToken).toBe("R2");
  });

  it("logs out when the refresh token is rejected", async () => {
    const storage = memoryStorage({ accessToken: "A1", refreshToken: "R1", expiresAt: NOW - 1 });
    const onSessionExpired = vi.fn();
    const fetchMock = vi.fn(async (url: string) =>
      url.endsWith("/auth/refresh")
        ? json(401, { detail: { code: "invalid_refresh", message: "refresh token reuse detected" } })
        : json(200, {}),
    );
    const client = new ApiClient({ storage, fetch: fetchMock as unknown as typeof fetch, now: () => NOW, onSessionExpired });

    const err = await client.get("/devices").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).code).toBe("invalid_refresh");
    expect(storage.value).toBeNull();
    expect(onSessionExpired).toHaveBeenCalledTimes(1);
    // the protected endpoint was never called with the stale token
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("surfaces mfa_required from login as an ApiError code without storing tokens", async () => {
    const storage = memoryStorage(null);
    const fetchMock = vi.fn(async () => json(401, { detail: { code: "mfa_required", message: "one-time password required" } }));
    const client = new ApiClient({ storage, fetch: fetchMock as unknown as typeof fetch, now: () => NOW });

    const err = (await client.login({ username: "alice", password: "pw" }).catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("mfa_required");
    expect(err.message).toBe("one-time password required");
    expect(storage.value).toBeNull();
    const headers = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("formats FastAPI validation errors", async () => {
    const storage = memoryStorage({ accessToken: "A1", refreshToken: "R1", expiresAt: NOW + 600_000 });
    const fetchMock = vi.fn(async () =>
      json(422, { detail: [{ loc: ["body", "hostname"], msg: "field required", type: "missing" }] }),
    );
    const client = new ApiClient({ storage, fetch: fetchMock as unknown as typeof fetch, now: () => NOW });
    await expect(client.post("/devices", {})).rejects.toThrow("hostname: field required");
  });
});

describe("buildQuery", () => {
  it("skips empty values and repeats arrays", () => {
    expect(buildQuery({ a: "x", b: "", c: null, d: undefined, e: false, f: [1, 2] })).toBe("?a=x&e=false&f=1&f=2");
    expect(buildQuery({})).toBe("");
  });
});

describe("errorMessage", () => {
  it("keeps messages that were already formatted (toast.error(title, errorMessage(e)) formats twice)", () => {
    const err = new ApiError(409, "four-eyes principle: requester cannot approve their own change");
    expect(errorMessage(errorMessage(err))).toBe("four-eyes principle: requester cannot approve their own change");
    expect(errorMessage(new Error("boom"))).toBe("boom");
    expect(errorMessage(42)).toBe("Unexpected error");
    expect(errorMessage("")).toBe("Unexpected error");
  });
});
