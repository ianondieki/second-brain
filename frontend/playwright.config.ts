import { defineConfig, devices } from "@playwright/test";

// E2E against the running compose stack (`make dev`). Mobile first: Pixel 5 at 360 px wide, plus desktop
// (docs/spec/04 principle 6, docs/spec/08 Testing).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  // One worker locally: signups and logins hash passwords with argon2id (64 MiB, t=3) in the API's single process,
  // and parallel local workers queue behind each other until tests time out. CI keeps Playwright's default (half
  // the runner's cores) and its retry. Override with `npm run e2e -- --workers=2`.
  workers: process.env.CI ? undefined : 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    // The first-login tour (components/tour) is remembered as done (the storage key the client reads and the cookie
    // the server reads), so it never sits over a screen under test; e2e/tour.spec.ts clears both for its own run.
    storageState: {
      cookies: [
        {
          name: "wazo-tour",
          value: "done",
          domain: new URL(process.env.E2E_BASE_URL ?? "http://localhost:3000").hostname,
          path: "/",
          expires: -1,
          httpOnly: false,
          secure: false,
          sameSite: "Lax",
        },
      ],
      origins: [{ origin: process.env.E2E_BASE_URL ?? "http://localhost:3000", localStorage: [{ name: "wazo-tour:v1", value: "done" }] }],
    },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "mobile-360", use: { ...devices["Pixel 5"], viewport: { width: 360, height: 780 } } },
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
});
