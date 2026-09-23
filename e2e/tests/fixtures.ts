import { test as base, expect, type APIRequestContext, type Page, request as pwRequest } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export const RUN_DIR = process.env.E2E_RUN ?? resolve(__dirname, "..", ".run");

export interface Stack {
  api_url: string;
  web_url: string;
  tacacs: { server_id: string; agent_token: string; config_path: string };
  ssh: { port: number; password: string; users: string[]; config_files: Record<string, string> };
  tenants: Record<string, { username: string; password: string }>;
}

export interface Account {
  username: string;
  password: string;
  tenant?: string;
}

export interface Seed {
  suffix: string;
  devices: Record<string, { id: string; hostname: string }>;
  site: string;
  tacacs_user: string;
  credential: { id: string; name: string; ssh_user: string };
  device_config_file: string;
  recording_id: string;
  users: Record<"viewer" | "requester" | "approver" | "mfa", Account & { id: string }>;
}

export const stack: Stack = JSON.parse(readFileSync(resolve(RUN_DIR, "stack.json"), "utf8"));
export const seed = (): Seed => JSON.parse(readFileSync(resolve(RUN_DIR, "ui-seed.json"), "utf8"));

export const ADMIN: Account = { ...stack.tenants.e2e, tenant: "e2e" };
export const OPERATOR: Account = { ...stack.tenants.acme, tenant: "acme" };
export const DEMO: Account = { ...stack.tenants.demo, tenant: "demo" };

export function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export async function apiLogin(who: Account, otp?: string): Promise<Tokens> {
  const ctx = await pwRequest.newContext();
  try {
    const r = await ctx.post(`${stack.api_url}/api/v1/auth/login`, {
      data: { username: who.username, password: who.password, tenant: who.tenant ?? "e2e", otp: otp ?? null },
    });
    if (!r.ok()) throw new Error(`login ${who.username} failed: ${r.status()} ${await r.text()}`);
    return (await r.json()) as Tokens;
  } finally {
    await ctx.dispose();
  }
}

/** Authenticated API client (directly against the API, like a script or SDK would). */
export async function apiAs(who: Account): Promise<APIRequestContext> {
  const t = await apiLogin(who);
  return pwRequest.newContext({
    baseURL: `${stack.api_url}/api/v1/`,
    extraHTTPHeaders: { Authorization: `Bearer ${t.access_token}` },
  });
}

/**
 * Log the browser in without the login form: tokens from the API are put where the app keeps them
 * (localStorage "nom.auth") before any page script runs. Existing (e.g. rotated) tokens are kept.
 */
export async function loginAs(page: Page, who: Account): Promise<void> {
  const t = await apiLogin(who);
  const auth = { accessToken: t.access_token, refreshToken: t.refresh_token, expiresAt: Date.now() + t.expires_in * 1000 };
  await page.addInitScript((value) => {
    try {
      if (!window.localStorage.getItem("nom.auth")) window.localStorage.setItem("nom.auth", value);
    } catch {
      /* ignore */
    }
  }, JSON.stringify(auth));
}

/** Collects console errors and uncaught exceptions of a page. */
export function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  return errors;
}

/** The app shell rendered (not the login page / a crash screen). */
export async function expectShell(page: Page): Promise<void> {
  await expect(page.getByRole("button", { name: /Search devices, ASNs, changes and users/ })).toBeVisible();
}

/** Pick an option of a Radix select identified by its accessible name. */
export async function selectOption(page: Page, name: string | RegExp, option: string | RegExp): Promise<void> {
  await page.getByRole("combobox", { name }).click();
  await page.getByRole("option", { name: option, exact: typeof option === "string" }).click();
}

export async function toast(page: Page, text: string | RegExp) {
  // Radix toasts are <li> items of the viewport <ol>; not role-based: a modal dialog marks the
  // notifications region aria-hidden while it is open
  await expect(page.locator("ol > li").filter({ hasText: text }).first()).toBeVisible();
}

export const test = base;
export { expect };
