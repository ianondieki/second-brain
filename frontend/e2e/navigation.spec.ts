import { expect, test } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { DEMO_PASSWORD } from "./support/moderation-scene";

// P16-B fix round 1 (REQ-UX-02, REQ-UX-03): no route-level loading states. A signed-in page renders in one server pass,
// so a session still owing its second factor gets a real 307 to /auth/mfa; in-app navigation shows a small hint on the
// tapped link (LinkPending) while the next page is on its way.

test("a session still owing its second factor gets a 307 to the second-factor page", async ({ page, baseURL }) => {
  // Every demo account has two-step sign-in: the password alone leaves the session pending.
  await page.goto("/login");
  await page.locator('form[data-hydrated="true"]').first().waitFor({ timeout: 20_000 });
  await page.getByLabel("Email address").fill("amina@developers.example");
  await page.getByLabel("Password", { exact: true }).fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/mfa$/, { timeout: 20_000 });
  const response = await page.request.get("/dev", { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  const location = new URL(response.headers()["location"] ?? "", baseURL);
  expect(location.pathname).toBe("/auth/mfa");
});

test("a tapped section shows its pending hint until the next page arrives", async ({ page }) => {
  await signUpDeveloper(page, "Wairimu Njeri");
  const nav = page.getByRole("navigation", { name: "Developer" });
  const discover = nav.getByRole("link", { name: "Discover" });
  const hint = discover.locator("[data-link-pending]");
  await expect(hint).toHaveAttribute("data-link-pending", "false");
  await expect(hint).toHaveCSS("opacity", "0");

  // Hold the navigation's page request (not a prefetch) so the pending state can be seen.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route(
    (url) => url.pathname === "/dev/discover",
    async (route) => {
      const headers = route.request().headers();
      if (headers["rsc"] && !headers["next-router-prefetch"]) await held;
      await route.continue();
    },
  );
  await discover.click();
  await expect(hint).toHaveAttribute("data-link-pending", "true");
  await expect(hint).toHaveCSS("opacity", "1");
  release();
  await expect(page).toHaveURL(/\/dev\/discover$/, { timeout: 20_000 });
  await expect(discover).toHaveAttribute("aria-current", "page");
  await expect(hint).toHaveAttribute("data-link-pending", "false");
  await expect(hint).toHaveCSS("opacity", "0");
});

test("the Discover view tabs fit the width without scrolling sideways", async ({ page }) => {
  await signUpDeveloper(page, "Otieno Wafula");
  await page.goto("/dev/discover");
  const strip = page.getByRole("navigation", { name: "Lists" }).getByRole("list");
  const { scrollWidth, clientWidth } = await strip.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});
