import { defineConfig, devices } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * Browser E2E against the running stack (e2e/scripts/stack-up.sh). The base URL comes from
 * $E2E_RUN/stack.json; global-setup seeds users and TACACS traffic via e2e/scripts/seed_ui.py.
 */
const runDir = process.env.E2E_RUN ?? resolve(__dirname, ".run");
let webUrl = process.env.E2E_WEB_URL ?? "http://127.0.0.1:3000";
try {
  webUrl = JSON.parse(readFileSync(resolve(runDir, "stack.json"), "utf8")).web_url;
} catch {
  /* global-setup reports a missing stack */
}

export default defineConfig({
  testDir: "./tests",
  globalSetup: "./tests/global-setup.ts",
  // specs share one tenant and one tac_plus-ng: run them one at a time, in file order
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }], ["junit", { outputFile: "test-results/junit.xml" }]],
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    locale: "en-GB",
    timezoneId: "UTC",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
