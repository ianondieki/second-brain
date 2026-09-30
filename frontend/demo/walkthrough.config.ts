import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// The recorded walkthrough of the demo story (P16-W; REQ-FND-02): its own config, apart from the E2E suite
// (playwright.config.ts has testDir ./e2e and never reads this folder). One worker, no retries, generous timeouts, a
// 1280 x 720 video of the desktop part into docs/demo/video/ (gitignored). Run it from a fresh demo:
// `make demo-reset`, `python infra/demo/demo.py e2e-env`, then `make demo-walkthrough` (or, without make,
// `cd frontend && npx playwright test -c demo/walkthrough.config.ts`). See demo/walkthrough.spec.ts and docs/demo/README.md.

/** frontend/.env.e2e (written by `python infra/demo/demo.py e2e-env`), for variables the shell has not set. */
function loadE2eEnv() {
  const file = join(__dirname, "..", ".env.e2e");
  if (!existsSync(file)) return;
  for (const line of readFileSync(file, "utf-8").split(/\r?\n/)) {
    const at = line.indexOf("=");
    if (at <= 0 || line.trimStart().startsWith("#")) continue;
    const name = line.slice(0, at).trim();
    if (process.env[name] === undefined) process.env[name] = line.slice(at + 1).trim();
  }
}

loadE2eEnv();

export default defineConfig({
  testDir: ".",
  testMatch: "walkthrough.spec.ts",
  outputDir: join(__dirname, "..", "..", "docs", "demo", "video"),
  timeout: 20 * 60_000,
  expect: { timeout: 20_000 },
  retries: 0,
  workers: 1,
  fullyParallel: false,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1440, height: 900 },
    video: { mode: "on", size: { width: 1280, height: 720 } },
    actionTimeout: 30_000,
    navigationTimeout: 45_000,
    trace: "off",
    screenshot: "off",
  },
});
