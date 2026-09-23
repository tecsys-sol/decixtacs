import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { ADMIN, apiAs, expect, expectShell, loginAs, selectOption, stack, test, toast, unique } from "./fixtures";

test("TACACS+: group, user, NAS, policy and mapping via the UI -> preview -> deploy -> agent installs it", async ({ page }) => {
  const group = unique("ui-ops");
  const user = unique("ui-eng");
  const nas = unique("ui-nas");
  const policy = unique("ui-policy");
  const octet = Math.floor(Math.random() * 200) + 20;
  await loginAs(page, ADMIN);

  // platform group and user
  await page.goto("/users?tab=groups");
  await expectShell(page);
  await page.getByRole("button", { name: "Create group" }).click();
  let dlg = page.getByRole("dialog", { name: "Create group" });
  await dlg.getByLabel("Name").fill(group);
  await dlg.getByRole("button", { name: "Create group" }).click();
  await expect(dlg).toBeHidden();
  await expect(page.getByRole("cell", { name: group, exact: true })).toBeVisible();

  await page.goto("/users?tab=users");
  await page.getByRole("button", { name: "Create user" }).click();
  dlg = page.getByRole("dialog", { name: "Create user" });
  await dlg.getByLabel("Username").fill(user);
  await dlg.getByLabel("Initial password").fill("Ui-Engineer-Pa55!");
  await dlg.getByRole("checkbox", { name: group }).check();
  await dlg.getByRole("button", { name: "Create user" }).click();
  await expect(dlg).toBeHidden();

  // NAS client
  await page.goto("/tacacs?tab=nas");
  await page.getByRole("button", { name: "Add NAS" }).click();
  dlg = page.getByRole("dialog", { name: "Add NAS device" });
  await dlg.getByLabel("Name").fill(nas);
  await dlg.getByLabel("Address / prefix").fill(`10.250.${octet}.1`);
  await selectOption(page, "Vendor", "Arista");
  await dlg.getByLabel("Shared key").fill(`ui-shared-key-${octet}`);
  await dlg.getByRole("button", { name: "Add NAS" }).click();
  await expect(dlg).toBeHidden();
  await expect(page.getByRole("cell", { name: nas, exact: true })).toBeVisible();

  // policy with a command rule
  await page.getByRole("tab", { name: /Policies/ }).click();
  await page.getByRole("button", { name: "New policy" }).click();
  dlg = page.getByRole("dialog", { name: "New TACACS+ policy" });
  await dlg.getByLabel("Name").fill(policy);
  await selectOption(page, "Select group", group);
  await dlg.getByLabel("Arista role").fill("network-operator");
  await dlg.getByRole("button", { name: "Add rule" }).click();
  await dlg.getByRole("textbox", { name: "Pattern" }).fill("^show ");
  await dlg.getByRole("button", { name: "Create policy" }).click();
  await expect(dlg).toBeHidden();
  await expect(page.getByText(policy).first()).toBeVisible();

  // user mapping with a device password
  await page.getByRole("tab", { name: /Users/ }).click();
  await page.getByRole("button", { name: "Map user" }).click();
  dlg = page.getByRole("dialog", { name: "Map user to TACACS+" });
  await selectOption(page, "Select user", new RegExp(user));
  await dlg.getByLabel("Device password", { exact: true }).fill("Ui-Tacacs-Pa55word!");
  await dlg.getByLabel("Confirm password").fill("Ui-Tacacs-Pa55word!");
  await dlg.getByRole("button", { name: "Create mapping" }).click();
  await expect(dlg).toBeHidden();

  // config preview shows the new objects (keys redacted)
  await page.getByRole("tab", { name: /Config preview/ }).click();
  await selectOption(page, "Server", "e2e-tac");
  const preview = page.locator("main");
  await expect(preview.getByText(`device ${nas} {`)).toBeVisible();
  await expect(preview.getByText(`profile ${policy} {`)).toBeVisible();
  await expect(preview.getByText(`user ${user} {`)).toBeVisible();
  await expect(preview.getByText(`ui-shared-key-${octet}`)).toHaveCount(0);

  // deploy -> new revision -> the agent validates (tac_plus-ng -P) and installs it
  const api = await apiAs(ADMIN);
  const server = async () =>
    ((await (await api.get("tacacs/servers")).json()) as { id: string; config_version: number; config_sha256: string }[]).find(
      (s) => s.id === stack.tacacs.server_id,
    )!;
  const before = (await server()).config_version;
  await page.getByRole("tab", { name: /Servers/ }).click();
  const row = page.getByRole("row").filter({ hasText: "e2e-tac" });
  await row.getByRole("button", { name: "Deploy" }).click();
  await page.getByRole("dialog", { name: /Deploy configuration to e2e-tac/ }).getByRole("button", { name: "Deploy" }).click();
  await toast(page, `Deployed v${before + 1} to e2e-tac`);
  await expect(row.getByText(`v${before + 1}`)).toBeVisible();
  await row.getByRole("button", { name: "Revisions" }).click();
  await expect(page.getByRole("dialog", { name: /Revisions/ }).getByText(`v${before + 1}`).first()).toBeVisible();
  await page.keyboard.press("Escape");

  const deployed = await server();
  const sha = () => createHash("sha256").update(readFileSync(stack.tacacs.config_path)).digest("hex");
  await expect.poll(sha, { timeout: 30_000, message: "agent installs the deployed revision" }).toBe(deployed.config_sha256);
  expect(readFileSync(stack.tacacs.config_path, "utf8")).toContain(`key = "ui-shared-key-${octet}"`);
  await api.dispose();
});

test("compliance run from the UI shows the score gauge", async ({ page }) => {
  const api = await apiAs(ADMIN);
  const runs = async () => ((await (await api.get("compliance/runs")).json()) as { id: string; score: number | null }[]);
  const before = (await runs()).length;
  await loginAs(page, ADMIN);
  await page.goto("/compliance");
  await expectShell(page);
  await page.getByRole("button", { name: "Run now" }).click();
  await toast(page, "Compliance run finished");
  await expect.poll(async () => (await runs()).length).toBe(before + 1);
  const latest = (await runs())[0];
  // ECharts' aria module describes the chart ("... type Gauge ... is 68.4")
  const shown = Number((latest.score ?? 0).toFixed(1)); // 68.42 -> 68.4, 88.0 -> 88
  const gauge = page.getByRole("img", { name: new RegExp(`type Gauge.* is ${shown}\\b`) }).first();
  await expect(gauge).toBeVisible();
  await expect(gauge.locator("canvas")).toBeVisible();
  await api.dispose();
});
