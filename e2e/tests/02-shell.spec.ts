import { ADMIN, collectErrors, expect, expectShell, loginAs, seed, test } from "./fixtures";

test("dashboard renders ECharts charts without console errors", async ({ page }) => {
  const errors = collectErrors(page);
  await loginAs(page, ADMIN);
  await page.goto("/dashboard");
  await expectShell(page);
  // ECharts draws into <canvas> inside role="img" containers
  await expect.poll(async () => page.locator('[role="img"] canvas').count(), { timeout: 20_000 }).toBeGreaterThanOrEqual(4);
  await expect(page.getByText("Compliance score").first()).toBeVisible();
  await expect(page.getByText("TACACS+ activity").first()).toBeVisible();
  // let lazy queries settle, then require a clean console
  await page.waitForLoadState("networkidle");
  expect(errors, errors.join("\n")).toEqual([]);
});

test("design theme Aurora <-> Meridian and colour mode persist across reloads", async ({ page }) => {
  await loginAs(page, ADMIN);
  await page.goto("/dashboard");
  await expectShell(page);
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-design", "aurora");

  await page.getByRole("button", { name: /^Appearance: .* theme$/ }).click();
  await page.getByRole("menuitemradio", { name: /Meridian/ }).click();
  await page.keyboard.press("Escape");
  await expect(html).toHaveAttribute("data-design", "meridian");
  await page.getByRole("button", { name: /^Appearance: .* theme$/ }).click();
  await page.getByRole("menuitemradio", { name: "Dark" }).click();
  await expect(html).toHaveClass(/\bdark\b/);

  await page.reload();
  await expectShell(page);
  await expect(html).toHaveAttribute("data-design", "meridian");
  await expect(html).toHaveClass(/\bdark\b/);
  // Meridian has its own shell: top pill navigation instead of the sidebar
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();

  await page.getByRole("button", { name: /^Appearance: .* theme$/ }).click();
  await page.getByRole("menuitemradio", { name: /Aurora/ }).click();
  await expect(html).toHaveAttribute("data-design", "aurora");
  // the design switch swaps the whole shell (sidebar layout), which closes the menu
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /^Appearance: .* theme$/ }).click();
  await page.getByRole("menuitemradio", { name: "Light" }).click();
  await expect(html).not.toHaveClass(/\bdark\b/);
  await page.reload();
  await expectShell(page);
  await expect(html).toHaveAttribute("data-design", "aurora");
  await expect(html).not.toHaveClass(/\bdark\b/);
});

test("command palette (Ctrl/Cmd+K) finds a device and navigates to it", async ({ page }) => {
  const dev = seed().devices.dev1;
  await loginAs(page, ADMIN);
  await page.goto("/dashboard");
  await expectShell(page);
  await page.keyboard.press("ControlOrMeta+k");
  const input = page.getByPlaceholder(/Search devices, IPs, sites/);
  await expect(input).toBeFocused();
  await input.fill(dev.hostname);
  const item = page.getByRole("option", { name: new RegExp(dev.hostname) });
  await expect(item).toBeVisible();
  await item.click();
  await expect(page).toHaveURL(new RegExp(`/devices/${dev.id}`));
  await expect(page.getByRole("heading", { name: dev.hostname })).toBeVisible();
});
