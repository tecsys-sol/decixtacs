import { DEMO, ADMIN, apiAs, collectErrors, expect, expectShell, loginAs, seed, test } from "./fixtures";

test("session replay plays an uploaded asciicast", async ({ page }) => {
  const s = seed();
  await loginAs(page, ADMIN);
  await page.goto("/sessions");
  await expectShell(page);
  const row = page.getByRole("row").filter({ hasText: s.tacacs_user }).first();
  await expect(row).toBeVisible();
  await row.getByRole("link", { name: "Replay" }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${s.recording_id}`));
  // the typed commands were extracted from the input events of the recording
  const cmd = page.getByRole("button", { name: /show version/ });
  await expect(cmd).toBeVisible();
  await expect(page.locator(".ap-player")).toBeVisible();
  await cmd.click(); // seeks and plays
  await expect(page.locator(".ap-player")).toContainText("E2E replay marker", { timeout: 20_000 });
  // replays are audited
  const api = await apiAs(ADMIN);
  const audit = await (await api.get("audit", { params: { action: "session.replay" } })).json();
  expect(audit.items.some((a: { target_id: string }) => a.target_id === s.recording_id)).toBe(true);
  await api.dispose();
});

test("network map renders the topology graph (demo tenant)", async ({ page }) => {
  const api = await apiAs(DEMO);
  const topo = (await (await api.get("topology")).json()) as { nodes: unknown[]; edges: unknown[] };
  await api.dispose();
  expect(topo.nodes.length).toBeGreaterThan(3);
  await loginAs(page, DEMO);
  await page.goto("/map");
  await expectShell(page);
  await expect(page.getByText(new RegExp(`${topo.edges.length} links? ·`))).toBeVisible();
  const graph = page.getByRole("img", { name: /graph/i }).first();
  await expect(graph.locator("canvas").first()).toBeVisible();
  const box = await graph.boundingBox();
  expect(box!.width).toBeGreaterThan(300);
  expect(box!.height).toBeGreaterThan(300);
});

test("IXP pages render the seeded members and route-server sessions", async ({ page }) => {
  const errors = collectErrors(page);
  await loginAs(page, DEMO);
  await page.goto("/ixp");
  await expectShell(page);
  const rows = page.locator("tbody tr");
  await expect.poll(() => rows.count()).toBeGreaterThanOrEqual(5);
  await expect(rows.first()).toContainText(/AS\d+|\d{3,}/);
  await expect(page.locator('[role="img"] canvas').first()).toBeVisible();
  await page.getByRole("textbox", { name: "Search members" }).fill("zzz-no-such-member");
  await expect(page.getByText(/No members|No IXP members|No results/i).first()).toBeVisible();

  await page.getByRole("tab", { name: /Route-server clients/ }).click();
  await expect.poll(() => page.locator("tbody tr").count()).toBeGreaterThanOrEqual(3);
  await expect(page.getByText("RPKI").first()).toBeVisible();
  expect(errors, errors.join("\n")).toEqual([]);
});

const MOBILE_PAGES = ["/dashboard", "/devices", "/backups", "/accounting", "/changes", "/tacacs", "/compliance", "/audit", "/ixp", "/map", "/settings"];

test.describe("mobile viewport (390px)", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("main pages render without horizontal overflow", async ({ page }) => {
    await loginAs(page, DEMO);
    for (const path of MOBILE_PAGES) {
      await page.goto(path);
      await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${path} overflows horizontally by ${overflow}px`).toBeLessThanOrEqual(1);
    }
  });

  test("mobile navigation drawer opens and navigates", async ({ page }) => {
    await loginAs(page, DEMO);
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("dialog").getByRole("link", { name: /^Devices\b/ }).first().click();
    await expect(page).toHaveURL(/\/devices/);
    await expect(page.getByRole("heading", { name: "Devices", exact: true }).first()).toBeVisible();
  });
});
