import { authenticator } from "otplib";

import { ADMIN, expect, expectShell, loginAs, seed, test } from "./fixtures";

async function fillLogin(page: import("@playwright/test").Page, username: string, password: string, tenant?: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  if (tenant) {
    await page.getByRole("button", { name: "Sign in to a specific organisation" }).click();
    await page.getByLabel("Organisation").fill(tenant);
  }
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("login with username and password lands on the dashboard", async ({ page }) => {
  await fillLogin(page, ADMIN.username, ADMIN.password, "e2e");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expectShell(page);
  await expect(page.getByRole("button", { name: /Account menu for/ })).toBeVisible();
});

test("wrong password shows an error and stays on the login page", async ({ page }) => {
  await fillLogin(page, ADMIN.username, "definitely-not-the-password", "e2e");
  await expect(page.locator("form [role=alert]")).toContainText(/invalid username or password/i);
  await expect(page).toHaveURL(/\/login/);
});

test("unauthenticated visit redirects to login with next=", async ({ page }) => {
  await page.goto("/devices");
  await expect(page).toHaveURL(/\/login\?next=%2Fdevices|\/login\?next=\/devices/);
});

test("MFA enrolment and TOTP login", async ({ page }) => {
  const user = seed().users.mfa;
  await loginAs(page, { ...user, tenant: "e2e" });
  await page.goto("/settings");
  await page.getByRole("button", { name: /Set up authenticator/ }).click();
  await expect(page.getByRole("img", { name: "QR code for your authenticator app" })).toBeVisible();
  const secret = (await page.locator("code").filter({ hasText: /^[A-Z2-7]{16,}$/ }).first().textContent())!.trim();
  await page.getByLabel("6-digit code").fill(authenticator.generate(secret));
  await page.getByRole("button", { name: "Verify & enable" }).click();
  await expect(page.getByText("Enabled", { exact: true })).toBeVisible();

  // sign out and back in: password first, then the one-time password
  await page.getByRole("button", { name: /Account menu for/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill(user.username);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Two-factor authentication" })).toBeVisible();

  const wrong = String((Number(authenticator.generate(secret)) + 1) % 1_000_000).padStart(6, "0");
  await page.getByLabel("One-time password").fill(wrong);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.locator("form [role=alert]")).toContainText(/invalid one-time password/i);
  await page.getByLabel("One-time password").fill(authenticator.generate(secret));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expectShell(page);
});
