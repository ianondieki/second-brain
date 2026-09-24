import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Smoke: the stack serves the home page and the API health check through the same origin.
test("home page renders with no serious accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});

test("API is reachable through the web origin", async ({ request }) => {
  const response = await request.get("/api/openapi.json");
  expect(response.ok()).toBeTruthy();
});
