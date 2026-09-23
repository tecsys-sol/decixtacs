import { readFileSync } from "node:fs";

import { ADMIN, DEMO, OPERATOR, apiAs, expect, expectShell, loginAs, seed, test } from "./fixtures";

test("read-only user: no write actions in the UI and 403 on direct API writes", async ({ page }) => {
  const s = seed();
  const viewer = { ...s.users.viewer, tenant: "e2e" };
  await loginAs(page, viewer);
  await page.goto("/devices");
  await expectShell(page);
  await expect(page.getByRole("link", { name: s.devices.dev1.hostname })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add device" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add site" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Back up .* now$/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "New change" })).toHaveCount(0);

  await page.goto(`/devices/${s.devices.dev1.id}`);
  await expect(page.getByRole("heading", { name: s.devices.dev1.hostname })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run backup" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: /Restore/ })).toHaveCount(0);

  await page.goto("/compliance");
  await expect(page.getByRole("heading", { name: "Compliance", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Run now" })).toHaveCount(0);

  const api = await apiAs(viewer);
  expect((await api.get("devices")).status()).toBe(200);
  expect((await api.post("devices", { data: { hostname: "viewer-sneaky", management_ip: "192.0.2.99" } })).status()).toBe(403);
  expect((await api.post("backups/run", { data: { device_ids: [s.devices.dev1.id] } })).status()).toBe(403);
  expect((await api.post(`tacacs/servers/${"00000000-0000-0000-0000-000000000000"}/deploy`)).status()).toBe(403);
  expect((await api.delete(`devices/${s.devices.dev1.id}`)).status()).toBe(403);
  expect((await api.get("audit")).status()).toBe(403);
  await api.dispose();
});

test("tenancy: another tenant sees nothing of tenant e2e", async ({ page }) => {
  const s = seed();
  const host = s.devices.dev1.hostname;
  await loginAs(page, OPERATOR);
  await page.goto("/devices");
  await expectShell(page);
  await expect(page.getByText("No devices match")).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByPlaceholder(/Search devices, IPs, sites/).fill(host);
  await expect(page.getByText("No results.")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/accounting");
  await expect(page.getByText("No commands found")).toBeVisible();

  const op = await apiAs(OPERATOR);
  expect((await (await op.get("devices", { params: { q: host } })).json()).total).toBe(0);
  expect((await op.get(`devices/${s.devices.dev1.id}`)).status()).toBe(404);
  expect((await (await op.get("accounting/commands", { params: { user: s.tacacs_user } })).json()).total).toBe(0);
  const audit = (await (await op.get("audit", { params: { limit: 500 } })).json()) as { items: { target_name: string | null }[] };
  expect(audit.items.some((a) => a.target_name === host)).toBe(false);
  await op.dispose();

  // a non-operator cannot switch tenants with X-Tenant
  const demo = await apiAs(DEMO);
  expect((await demo.get("devices", { headers: { "X-Tenant": "e2e" } })).status()).toBe(403);
  expect((await (await demo.get("devices", { params: { q: host } })).json()).total).toBe(0);
  await demo.dispose();
});

test("reports download as CSV, XLSX and PDF", async ({ page }, testInfo) => {
  await loginAs(page, ADMIN);
  await page.goto("/reports");
  await expectShell(page);
  const magic: Record<string, (b: Buffer) => boolean> = {
    csv: (b) => b.toString("utf8").split("\n").length >= 2 && b.toString("utf8").includes(","),
    xlsx: (b) => b.subarray(0, 2).toString() === "PK",
    pdf: (b) => b.subarray(0, 5).toString() === "%PDF-",
  };
  for (const fmt of ["csv", "xlsx", "pdf"] as const) {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: fmt.toUpperCase(), exact: true }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${fmt}$`));
    const file = testInfo.outputPath(download.suggestedFilename());
    await download.saveAs(file);
    const body = readFileSync(file);
    expect(body.length, `${fmt} is not empty`).toBeGreaterThan(100);
    expect(magic[fmt](body), `${fmt} has the right format`).toBe(true);
  }
});
