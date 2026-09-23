import { ADMIN, apiAs, expect, expectShell, loginAs, seed, test, toast, unique } from "./fixtures";

test("accounting shows commands from tac_plus-ng, flags dangerous ones and filters by regex", async ({ page }) => {
  const s = seed();
  await loginAs(page, ADMIN);
  await page.goto("/accounting");
  await expectShell(page);
  await page.getByRole("textbox", { name: "User" }).fill(s.tacacs_user);
  const rows = page.locator("tbody tr");
  // accounted (show bgp summary, request system reboot, configure terminal) + denied authorizations
  await expect(rows.filter({ hasText: "show bgp summary" }).first()).toBeVisible();
  const reboot = rows.filter({ hasText: "request system reboot" }).filter({ hasText: /Accounted/i }).first();
  await expect(reboot).toBeVisible();
  await expect(reboot.getByText(/Dangerous · Reboot\/zeroize/)).toBeVisible();
  await expect(reboot).toContainText(s.devices.dev1.hostname); // correlated with the inventory device
  await expect(reboot).toContainText("from 203.0.113.9");
  await expect(rows.filter({ hasText: "show running-config" }).filter({ hasText: /denied/i }).first()).toBeVisible();

  // regex filter (PostgreSQL ~): only the reboot records remain
  await page.getByRole("textbox", { name: "Command" }).fill("~^request system (reboot|halt)$");
  await expect(rows.filter({ hasText: "show bgp summary" })).toHaveCount(0);
  await expect(rows.first()).toContainText("request system reboot");
  const n = await rows.count();
  for (let i = 0; i < n; i++) await expect(rows.nth(i)).toContainText("request system reboot");
  await expect(page.getByText(/dangerous on this page/)).toBeVisible();
});

test("change request four-eyes workflow with two users", async ({ page, browser }) => {
  const s = seed();
  const title = unique("UI change");
  await loginAs(page, { ...s.users.requester, tenant: "e2e" });
  await page.goto("/changes");
  await expectShell(page);
  await page.getByRole("link", { name: "New change" }).first().click();
  const dlg = page.getByRole("dialog", { name: "New change request" });
  await dlg.getByLabel("Title").fill(title);
  await dlg.getByLabel("Description").fill("Raise NTP redundancy on the E2E lab devices");
  await dlg.getByRole("button", { name: /Create|Save/ }).click();
  await toast(page, /CHG-\d+ created/);
  await expect(page).toHaveURL(/\/changes\/[0-9a-f-]{36}/); // the dialog opens the new change
  await expect(page.getByRole("heading", { name: new RegExp(title) })).toBeVisible();
  const changeUrl = page.url();

  await page.getByRole("button", { name: "Submit for approval", exact: true }).click();
  await page.getByTestId("transition-confirm").click();
  await toast(page, /is now pending approval/i);
  await expect(page.getByRole("dialog")).toBeHidden();

  // the requester holds changes:approve but cannot approve their own change
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByTestId("transition-confirm").click();
  await toast(page, /four-eyes principle: requester cannot approve their own change/);
  await page.getByRole("dialog").getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();

  // a second user (change manager) approves
  const ctx2 = await browser.newContext();
  const approver = await ctx2.newPage();
  await loginAs(approver, { ...s.users.approver, tenant: "e2e" });
  await approver.goto(changeUrl);
  await expect(approver.getByRole("heading", { name: new RegExp(title) })).toBeVisible();
  await approver.getByRole("button", { name: "Approve", exact: true }).click();
  await approver.getByRole("dialog").getByLabel(/Comment/).fill("Looks good - four eyes");
  await approver.getByTestId("transition-confirm").click();
  await toast(approver, /is now approved/i);
  await ctx2.close();

  // requester implements and closes
  await page.reload();
  await page.getByRole("button", { name: "Mark implemented", exact: true }).click();
  await page.getByTestId("transition-confirm").click();
  await toast(page, /is now implemented/i);
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByTestId("transition-confirm").click();
  await toast(page, /is now closed/i);

  const api = await apiAs(ADMIN);
  const { change } = (await (await api.get(`changes/${changeUrl.split("/").pop()}`)).json()) as {
    change: { state: string; approved_by: string | null; requested_by: string };
  };
  expect(change.state).toBe("closed");
  expect(change.approved_by).toBe(s.users.approver.id);
  expect(change.requested_by).toBe(s.users.requester.id);
  await api.dispose();
});

test("audit log lists the actions and the hash chain verifies intact", async ({ page }) => {
  await loginAs(page, ADMIN);
  await page.goto("/audit");
  await expectShell(page);
  for (const action of ["tacacs.deploy", "device.create", "change.approve"]) {
    await page.getByRole("textbox", { name: "Action" }).fill(action);
    await expect(page.locator("tbody tr").filter({ hasText: action }).first()).toBeVisible();
  }
  await page.getByRole("button", { name: "Verify chain" }).click();
  const status = page.getByRole("status").filter({ hasText: /Chain intact/ });
  await expect(status).toBeVisible();
  await expect(status).toContainText(/\d+ events verified/);
});
