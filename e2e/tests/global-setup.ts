import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

/** Seed users, TACACS traffic and a session recording through the real stack (idempotent per run). */
export default async function globalSetup() {
  const e2eRoot = resolve(__dirname, "..");
  const runDir = process.env.E2E_RUN ?? resolve(e2eRoot, ".run");
  if (!existsSync(resolve(runDir, "stack.json"))) {
    throw new Error(`${runDir}/stack.json not found - start the stack with e2e/scripts/stack-up.sh`);
  }
  const python = process.env.E2E_PYTHON ?? resolve(e2eRoot, ".venv/bin/python");
  execFileSync(python, [resolve(e2eRoot, "scripts/seed_ui.py")], {
    stdio: "inherit",
    env: { ...process.env, E2E_RUN: runDir },
    timeout: 240_000,
  });
}
