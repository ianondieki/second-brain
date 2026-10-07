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
  await checkScreen(page, { strict: true }); // an item caught mid-reveal is read under reduced motion (screen.ts)

  // Scrolled through, How it works rests fully opaque (globals.css .reveal), and the page passes with its motion on.
  // P24: How it works is three numbered cards (the five stages are the hero panel's stepper and the stats row).
  const reveal = page.locator(".reveal");
  await expect(reveal).toHaveCount(3);
  for (const item of await reveal.all()) {
    await item.scrollIntoViewIfNeeded();
    await expect(item).toHaveCSS("opacity", "1");
  }
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  for (const item of await reveal.all()) await expect(item).toHaveCSS("opacity", "1");
  // The strictest rest: the last stage just wholly on screen (its bottom at the viewport's bottom) is fully opaque.
  for (const size of [{ width: 375, height: 800 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(size);
    await page.evaluate(() => {
      const last = [...document.querySelectorAll(".reveal")].at(-1)!;
      window.scrollTo(0, window.scrollY + last.getBoundingClientRect().bottom - window.innerHeight);
    });
    await expect(reveal.last()).toHaveCSS("opacity", "1");
  }
  await checkScreen(page, { strict: true });
});

// P24 (REQ-UX-03, REQ-UX-04; D-66): the landing's new sections say only product constants and label example data; the
// county strip leads to Explore; Explore (its tiles, or its empty state while the summary cannot be read) and Credits
// pass strict axe; the manifest makes the site installable.
test("the landing's P24 sections, Explore, Credits and the manifest", async ({ page, request }) => {
  await page.goto("/");
  for (const name of ["Built for Kenya's counties", "From an idea to a signed agreement, in three steps", "Every recommendation names its reason"]) {
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  }
  await expect(page.locator("[data-hero-visual] .demo-label")).toHaveText("Demo data");
  await expect(page.locator(".terminal .demo-label")).toHaveText("Seeded example");
  await expect(page.locator("[data-count-up] dd .sr-only")).toHaveText(["5", "47", "16", "0"]);
  // The strip's first copy is the one the keyboard reaches; the second is hidden from it.
  const kisumu = page.locator(".pan-row").first().getByRole("link", { name: "Kisumu" });
  await expect(kisumu).toHaveAttribute("href", "/explore#kisumu");
  await expect(page.locator(".pan-row").nth(1)).toHaveAttribute("aria-hidden", "true");
  // What's happening is there when the feed answers, labelled when seeded; the page stands without it.
  const activity = page.locator("[data-activity]");
  if (await activity.count()) await expect(activity.getByRole("region")).toHaveAttribute("tabindex", "0");
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await checkScreen(page, { strict: true });

  await page.goto("/explore");
  await expect(page.getByRole("heading", { level: 1, name: "Problems across Kenya" })).toBeVisible();
  await expect(page.locator("[data-primary]")).toHaveText("Create an account");
  await expect(page.locator("[data-explore='empty'], [data-explore='none'], #explore-counties")).toHaveCount(1);
  await checkScreen(page, { strict: true });

  await page.goto("/credits");
  const credits = page.locator("[data-credits='photos'] li");
  expect(await credits.count()).toBeGreaterThanOrEqual(6);
  for (const item of await credits.all()) await expect(item).toContainText("via Wikimedia Commons");
  await checkScreen(page, { strict: true });

  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBeTruthy();
  expect(await manifest.json()).toMatchObject({ short_name: "Wazo", display: "standalone", start_url: "/" });
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
