import { expect, test } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { logInWithPassword, PASSWORD, twoStepDeveloper } from "./support/two-step-account";

// P16-B fix round 1 (REQ-UX-02, REQ-UX-03): no route-level loading states. A signed-in page renders in one server pass,
// so a session still owing its second factor gets a real 307 to /auth/mfa; in-app navigation shows a small hint on the
// tapped link (LinkPending) while the next page is on its way.

test("a session still owing its second factor gets a 307 to the second-factor page", async ({ page, baseURL }) => {
  // Its own two-step account (P16-B review MINOR 1): the password alone leaves the session pending.
  const person = await twoStepDeveloper(page);
  await page.goto("/login");
  await logInWithPassword(page, person, PASSWORD);
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
  // Shown: it fades in, then pulses between full and half opacity (without reduced motion).
  await expect
    .poll(async () => Number(await hint.evaluate((el) => getComputedStyle(el).opacity)))
    .toBeGreaterThanOrEqual(0.45);
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

// P16-C1 (P16-B ux-review): after a client navigation, focus is on the new page's title, not on <body>.
test("after a tapped section loads, focus is on its page title", async ({ page }) => {
  await signUpDeveloper(page, "Chebet Rono");
  await page.getByRole("navigation", { name: "Developer" }).getByRole("link", { name: "My ideas" }).click();
  await expect(page).toHaveURL(/\/dev\/ideas$/, { timeout: 20_000 });
  const title = page.getByRole("heading", { level: 1 });
  await expect(title).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(title).not.toBeFocused();
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(false);
});

// P12-F re-review MINOR 4 (P16-C1): at 360 px the developer tabs never run into each other, with this machine's
// fallback font for the system stack, in English and in Swahili, with the longest label ("Engagements",
// "Ushirikiano") current and bold.
test("the developer tabs keep every label inside its own tab at 360 px, in English and Swahili", async ({ page, baseURL }) => {
  await signUpDeveloper(page, "Akinyi Odera");
  await page.setViewportSize({ width: 360, height: 780 }); // the tab bar, in both projects
  for (const locale of ["en", "sw"]) {
    await page.context().addCookies([{ name: "NEXT_LOCALE", value: locale, url: baseURL! }]);
    for (const path of ["/dev/engagements", "/dev/companies"]) {
      await page.goto(path);
      const nav = page.getByRole("navigation").filter({ has: page.locator("a[aria-current='page']") }).first();
      const boxes = await nav.locator("li").evaluateAll((items) =>
        items.map((li) => {
          const tab = li.getBoundingClientRect();
          const label = li.querySelector("a > span:not([aria-hidden])")!.getBoundingClientRect();
          return { tab: [tab.left, tab.right], label: [label.left, label.right], text: li.textContent };
        }),
      );
      expect(boxes).toHaveLength(5);
      for (const { tab, label, text } of boxes) {
        expect(label[0], `${locale} ${path} ${text}`).toBeGreaterThanOrEqual(tab[0] - 0.5);
        expect(label[1], `${locale} ${path} ${text}`).toBeLessThanOrEqual(tab[1] + 0.5);
      }
      for (let i = 1; i < boxes.length; i++) expect(boxes[i].tab[0]).toBeGreaterThanOrEqual(boxes[i - 1].tab[1] - 0.5);
    }
  }
});
