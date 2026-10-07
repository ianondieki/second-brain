import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { checkScreen, settled } from "./support/screen";

// Smoke: the stack serves the home page and the API health check through the same origin.
test("home page renders with no serious accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});

// P23-2 (REQ-UX-02, REQ-UX-03; D-65): the top bar reads as the product (no Prototype badge, no lattice band), and
// the hero's story settles on its last frame: the tracker at Agreement with "Your turn", the "before" layer gone.
test("the landing's top bar is clean and the hero's story settles, with nothing strict axe finds", async ({ page }) => {
  await page.goto("/");
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("link", { name: "Wazo" })).toBeVisible();
  await expect(banner.getByText("Prototype", { exact: true })).toHaveCount(0);
  await expect(banner.locator("[data-lattice]")).toHaveCount(0);
  await settled(page);
  const hero = page.locator("[data-hero-visual]");
  await expect(hero.getByRole("list", { name: "Stages" }).locator("[aria-current='step']")).toHaveAttribute("data-group", "agreement");
  await expect(hero.locator(".hero-before").first()).toBeHidden();
  await expect(hero.getByText("Your turn")).toBeVisible();
  await checkScreen(page, { strict: true });
});

test("API is reachable through the web origin", async ({ request }) => {
  const response = await request.get("/api/openapi.json");
  expect(response.ok()).toBeTruthy();
});

// P16-B: the signed-in portals stream (loading.tsx); proxy.ts sends a visit without a session cookie to /login with a
// real 307 before anything renders.
test("signed-out visits to signed-in routes answer 307 to /login", async ({ page, baseURL }) => {
  for (const path of ["/dev", "/org/inbox"]) {
    const response = await page.request.get(path, { maxRedirects: 0 });
    expect(response.status(), path).toBe(307);
    const location = new URL(response.headers()["location"] ?? "", baseURL);
    // With the page as its return path (P16-C1, lib/return-path.ts).
    expect(`${location.pathname}${location.search}`, path).toBe(`/login?${new URLSearchParams({ next: path })}`);
  }
});
