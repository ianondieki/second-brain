import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkWidths, shot } from "./support/discover-scene";
import { signUpOrgMember } from "./support/org-scene";
import { publishIdea } from "./support/pitch-scene";
import { OWNER_DATABASE_URL, makeD1 } from "./support/verification";

// REQ-DEV-03 (D-58, D-62; docs/platform/tasks/P22.md C7) against the demo stack, in both projects: two new developers
// in the same county who like the same niches turn on Visible to peers in Settings › Profile; A finds B on Home and on
// /dev/peers and invites B to team up on a published problem; B accepts from /dev/teams; they exchange a message
// each; A credits B as a contributor on A's published idea, and the idea page and its certificate sheet say
// "Contributors: <B>"; B blocks A, after which A's peers no longer list B and the thread reads closed. An organisation
// member's Home has no Peers section and /dev/peers sends them home as every developer route does. Strict axe, one
// primary action and no sideways scroll on every state, at 360 and 375 px (mobile-360) and 1440 px (desktop).
// E2E_SHOTS_DIR saves screenshots.
//
// Each project uses its own county, and both developers turn Visible to peers off at the end, so reruns never crowd
// each other's lists.

const SERVER_STEP = { timeout: 20_000 };
const COUNTY: Record<string, string> = { "mobile-360": "KE-21", desktop: "KE-22" };

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function newPage(browser: Browser, baseURL: string | undefined, width: number) {
  const context = await browser.newContext({ baseURL, viewport: { width, height: 800 } });
  return context.newPage();
}

/** Three leaf niches both developers like (PUT /api/me/niches; the niche picker has its own tests). */
async function likedNiches(request: APIRequestContext): Promise<string[]> {
  const tree = (await (await request.get("/api/directory/niches")).json()) as Array<{ id: string; children?: Array<{ id: string }> }>;
  const leaves = tree.flatMap((parent) => (parent.children?.length ? parent.children.map((child) => child.id) : [parent.id]));
  return leaves.slice(-3);
}

async function like(request: APIRequestContext, niches: string[]) {
  const response = await request.put("/api/me/niches", { headers: { "X-CSRF-Token": await csrf(request) }, data: { liked: niches } });
  expect(response.status(), await response.text()).toBe(200);
}

async function handleOf(request: APIRequestContext): Promise<string> {
  return ((await (await request.get("/api/me/profile")).json()) as { handle: string }).handle;
}

async function visible(request: APIRequestContext, on: boolean) {
  await request.patch("/api/me/profile", { headers: { "X-CSRF-Token": await csrf(request) }, data: { peers_visible: on } });
}

/** Settings › Profile through the screen: the county, a headline and Visible to peers on, then Save. */
async function turnOnPeers(page: Page, county: string, headline: string) {
  await page.goto("/settings/profile");
  await expect(page.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: "Profile" })).toHaveAttribute("aria-current", "page");
  await page.locator('form[data-hydrated="true"]').waitFor(SERVER_STEP);
  await page.getByLabel("County").selectOption(county);
  await page.getByLabel("Headline").fill(headline);
  const toggle = page.getByRole("switch", { name: "Visible to peers" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await page.locator("[data-primary]").click();
  const status = page.getByRole("status").filter({ hasText: "Profile saved." });
  await expect(status).toBeFocused(SERVER_STEP);
}

test.describe("Peers and team up", () => {
  test.setTimeout(300_000);

  test("two developers near each other team up, write, credit and block", async ({ page, browser, baseURL }, info) => {
    test.skip(!OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL makes A a D1 developer who can publish an idea");
    const width = page.viewportSize()!.width;
    const county = COUNTY[info.project.name] ?? COUNTY.desktop;
    const emailA = await signUpDeveloper(page, "Akinyi Odhiambo");
    const pageB = await newPage(browser, baseURL, width);
    try {
      await signUpDeveloper(pageB, "Baraka Mwangi");
      const niches = await likedNiches(page.request);
      await like(page.request, niches);
      await like(pageB.request, niches);
      const handleB = await handleOf(pageB.request);
      const handleA = await handleOf(page.request);

      // Not visible yet: Home's Peers says so in one sentence and links Settings; /dev/peers says the same.
      await page.goto("/dev");
      const section = page.locator("[data-home=peers]");
      await expect(section.getByRole("heading", { name: "Peers", level: 2 })).toBeVisible();
      await expect(section.getByRole("link", { name: "Turn on in Settings" })).toHaveAttribute("href", "/settings/profile");
      await expect(page.locator("[data-primary]")).toHaveCount(1);
      await checkWidths(page, info);
      await page.goto("/dev/peers");
      await expect(page.locator("[data-peers=off]")).toBeVisible();
      await checkWidths(page, info);

      // Both turn on Visible to peers in Settings › Profile.
      await turnOnPeers(page, county, "Fuel sensors and alerting");
      await checkWidths(page, info);
      await shot(page, info, "teams-profile");
      await turnOnPeers(pageB, county, "Dashboards for field teams");

      // A finds B on Home, then on Peers.
      await page.goto("/dev");
      const homeRow = section.locator(`[data-peer="${handleB}"]`);
      await expect(homeRow).toContainText("Same county");
      await expect(homeRow).toContainText("3 shared niches");
      await checkWidths(page, info);
      await section.getByRole("link", { name: "See all" }).click();
      await expect(page).toHaveURL(/\/dev\/peers$/, SERVER_STEP);
      const row = page.locator(`[data-peer="${handleB}"]`);
      await expect(row).toContainText("Dashboards for field teams");
      await expect(row).toContainText("Same county");
      await checkWidths(page, info);
      await shot(page, info, "teams-peers");

      // A invites B on a published problem, found by its words.
      const problems = (await (await page.request.get("/api/problems?limit=1")).json()) as { items: Array<{ id: string; title: string }> };
      const problem = problems.items[0];
      await row.getByRole("button", { name: "Team up" }).click();
      const sheet = page.getByRole("dialog", { name: `Team up with ${handleB}` });
      await expect(sheet).toBeVisible();
      await sheet.getByLabel("Problem or Brief").fill(problem.title.split(" ").slice(0, 3).join(" "));
      await sheet.getByRole("radio", { name: problem.title }).check(SERVER_STEP);
      await sheet.getByLabel("Note (optional)").fill("I build fuel sensors; would you take the dashboard?");
      await checkWidths(page, info);
      await shot(page, info, "teams-sheet");
      await sheet.getByRole("button", { name: "Send invitation" }).click();
      const sent = row.locator("[data-invited-line]");
      await expect(sent).toContainText(`Invitation sent to ${handleB}.`, SERVER_STEP);
      await expect(sent).toBeFocused();
      await expect(row.getByRole("button", { name: "Team up" })).toHaveCount(0);
      await checkWidths(page, info);

      // B accepts from /dev/teams and opens the thread.
      await pageB.goto("/dev/teams");
      const card = pageB.getByRole("article", { name: `${handleA} invited you` });
      await expect(card).toContainText(problem.title);
      await expect(card.locator("[data-note]")).toHaveText("I build fuel sensors; would you take the dashboard?");
      await expect(pageB.locator("[data-primary]")).toHaveCount(0);
      await checkWidths(pageB, info);
      await shot(pageB, info, "teams-invitations");
      await card.getByRole("button", { name: "Accept" }).click();
      const accepted = pageB.getByRole("status").filter({ hasText: `Your thread with ${handleA} is open.` });
      await expect(accepted).toBeFocused(SERVER_STEP);
      await checkWidths(pageB, info);
      await accepted.getByRole("link", { name: "Open the thread" }).click();
      await expect(pageB).toHaveURL(/\/dev\/teams\/[0-9a-f-]{36}$/, SERVER_STEP);
      const threadPath = new URL(pageB.url()).pathname;
      await expect(pageB.getByRole("heading", { name: handleA, level: 1 })).toBeVisible();
      await expect(pageB.locator("[data-attach]")).toHaveCount(0);
      await pageB.locator('[data-thread][data-hydrated="true"]').waitFor(SERVER_STEP);
      await pageB.getByLabel("Your message").fill("Yes. I will start the dashboard this week.");
      await pageB.locator("[data-primary]").click();
      await expect(pageB.locator('[data-message][data-mine="true"]')).toContainText("I will start the dashboard", SERVER_STEP);
      await checkWidths(pageB, info);

      // A sees the thread, reads B's message and answers.
      await page.goto("/dev/teams");
      const threadRow = page.locator("[data-thread]").filter({ hasText: handleB });
      await expect(threadRow).toContainText(problem.title);
      await checkWidths(page, info);
      await threadRow.getByRole("link", { name: handleB }).click();
      await expect(page).toHaveURL(new RegExp(`${threadPath}$`), SERVER_STEP);
      await expect(page.locator('[data-message][data-mine="false"]')).toContainText("I will start the dashboard");
      await page.locator('[data-thread][data-hydrated="true"]').waitFor(SERVER_STEP);
      await page.getByLabel("Your message").fill("Great. The sensor feed is ready for you.");
      await page.locator("[data-primary]").click();
      await expect(page.locator('[data-message][data-mine="true"]')).toContainText("sensor feed is ready", SERVER_STEP);
      await checkWidths(page, info);
      await shot(page, info, "teams-thread");
      await pageB.reload();
      await expect(pageB.locator('[data-message][data-mine="false"]')).toContainText("sensor feed is ready");

      // A credits B on A's published idea; the idea page and its certificate say so.
      makeD1(emailA);
      const idea = await publishIdea(page.request, `Fuel alerts ${Date.now().toString(36)}`);
      await page.reload();
      await page.getByRole("button", { name: "Add as contributor on an idea" }).click();
      const credit = page.getByRole("dialog", { name: `Add ${handleB} as a contributor` });
      await credit.getByRole("radio", { name: idea.title }).check();
      await checkWidths(page, info);
      await credit.getByRole("button", { name: "Add contributor" }).click();
      const added = page.getByRole("status").filter({ hasText: `Added as contributor on ${idea.title}.` });
      await expect(added).toBeFocused(SERVER_STEP);
      await page.goto(`/dev/ideas/${idea.id}`);
      await expect(page.locator("[data-contributors]")).toContainText(`Contributors: ${handleB}`);
      await expect(page.locator("[data-certificate-contributors]")).toHaveText(`Contributors: ${handleB}`);
      await checkWidths(page, info);
      await shot(page, info, "teams-idea");

      // B blocks A from the thread's menu: A's peers no longer list B and A's thread reads closed.
      await pageB.locator("[data-thread-menu] summary").click();
      await pageB.getByRole("button", { name: `Block ${handleA}` }).click();
      const block = pageB.getByRole("dialog", { name: `Block ${handleA}?` });
      await checkWidths(pageB, info);
      await block.getByRole("button", { name: "Block" }).click();
      await expect(pageB.getByRole("status").filter({ hasText: `${handleA} is blocked.` })).toBeFocused(SERVER_STEP);
      await expect(pageB.locator("[data-thread-closed=blocked]")).toBeVisible(SERVER_STEP);
      await checkWidths(pageB, info);

      await page.goto("/dev/peers");
      await expect(page.getByRole("heading", { name: "Peers", level: 1 })).toBeVisible();
      await expect(page.locator(`[data-peer="${handleB}"]`)).toHaveCount(0);
      await checkWidths(page, info);
      await page.goto(threadPath);
      await expect(page.locator("[data-thread-closed]")).toBeVisible();
      await expect(page.locator("[data-composer]")).toHaveCount(0);
      await expect(page.locator("[data-primary]")).toHaveCount(0);
      await checkWidths(page, info);
      await shot(page, info, "teams-closed");
    } finally {
      await visible(page.request, false);
      await visible(pageB.request, false);
      await pageB.context().close();
    }
  });

  test("an organisation member has no Peers and is sent home from them", async ({ page }, info) => {
    test.skip(!OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL is needed for the organisation's scene");
    await signUpOrgMember(page.request, "Viewer");
    await page.goto("/dev");
    await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
    await expect(page.locator("[data-home=peers]")).toHaveCount(0);
    for (const path of ["/dev/peers", "/dev/teams", "/settings/profile"]) {
      await page.goto(path);
      await expect(page).toHaveURL(path === "/settings/profile" ? /\/settings\/security$/ : /\/org$/, SERVER_STEP);
    }
    expect((await page.request.get("/api/me/peers")).status()).toBe(404);
    expect((await page.request.get("/api/me/teams")).status()).toBe(404);
    await checkWidths(page, info);
  });
});
