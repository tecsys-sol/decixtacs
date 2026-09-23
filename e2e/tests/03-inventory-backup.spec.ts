import { appendFileSync, readFileSync, writeFileSync } from "node:fs";

import { ADMIN, apiAs, expect, expectShell, loginAs, seed, selectOption, stack, test, unique } from "./fixtures";

interface Backup {
  id: string;
  status: string;
  changed: boolean;
  commit_sha: string | null;
  error: string | null;
}

test("create a site and a device in the UI, back it up twice, review history and diff", async ({ page }) => {
  const s = seed();
  const siteName = unique("UI Site");
  const hostname = unique("ui-linux");
  const cfgFile = s.device_config_file;
  const original = readFileSync(cfgFile, "utf8");
  const api = await apiAs(ADMIN);
  try {
    await loginAs(page, ADMIN);
    await page.goto("/devices");
    await expectShell(page);

    // --- site ---------------------------------------------------------------------------------
    await page.getByRole("button", { name: "Add site" }).click();
    const siteDialog = page.getByRole("dialog", { name: "Add site" });
    await siteDialog.getByLabel("Name").fill(siteName);
    await expect(siteDialog.getByLabel("Slug")).toHaveValue(siteName.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
    await siteDialog.getByRole("button", { name: "Create site" }).click();
    await expect(siteDialog).toBeHidden();

    // --- device -------------------------------------------------------------------------------
    await page.getByRole("button", { name: "Add device" }).click();
    const dlg = page.getByRole("dialog", { name: "Add device" });
    await dlg.getByLabel("Hostname").fill(hostname);
    await dlg.getByLabel("Management IP").fill("127.0.0.3");
    await selectOption(page, "Select site", siteName);
    await selectOption(page, "Select platform", "Linux");
    await selectOption(page, "Select credential", `${s.credential.name} (${s.credential.ssh_user})`);
    await dlg.getByLabel("SSH port").fill(String(stack.ssh.port));
    await dlg.getByRole("button", { name: "Create device" }).click();
    await expect(page).toHaveURL(/\/devices\/[0-9a-f-]{36}/);
    const deviceId = page.url().match(/devices\/([0-9a-f-]{36})/)![1];
    await expect(page.getByRole("heading", { name: hostname })).toBeVisible();
    await expect(page.getByText(siteName).first()).toBeVisible();

    const backups = async (): Promise<Backup[]> =>
      (await (await api.get("backups", { params: { device_id: deviceId } })).json()).items;

    // --- first backup via the UI (Celery worker -> SSH -> Git) --------------------------------
    await page.getByRole("button", { name: "Run backup" }).click();
    await expect.poll(async () => (await backups()).filter((b) => b.status === "success").length, { timeout: 60_000 }).toBe(1);

    // --- change the device, second backup ------------------------------------------------------
    const marker = `ntp server 198.51.100.${Math.floor(Math.random() * 200) + 20}`;
    appendFileSync(cfgFile, `${marker}\n`);
    await page.getByRole("button", { name: "Run backup" }).click();
    await expect.poll(async () => (await backups()).filter((b) => b.changed).length, { timeout: 60_000 }).toBe(2);

    // --- Backups page lists the device ---------------------------------------------------------
    await page.goto("/backups");
    await expect(page.getByRole("row").filter({ hasText: hostname }).first()).toBeVisible();

    // --- device History & diff tab: side-by-side rows ------------------------------------------
    await page.goto(`/devices/${deviceId}`);
    await page.getByRole("tab", { name: /History & diff/ }).click();
    const split = page.getByTestId("diff-split");
    await expect(split).toBeVisible();
    const added = split.locator('tr[data-type="added"]');
    await expect(added.filter({ hasText: marker })).toHaveCount(1);
    await expect(page.getByTestId("diff-added")).toContainText("1");
    await expect(page.getByRole("list", { name: "Configuration commits" }).getByRole("listitem")).toHaveCount(2);

    // Commits tab shows both revisions too
    await page.getByRole("tab", { name: /Commits/ }).click();
    await expect(page.getByText(/manual \(UI\)/).first()).toBeVisible();
  } finally {
    writeFileSync(cfgFile, original);
    await api.dispose();
  }
});
