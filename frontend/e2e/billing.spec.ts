import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { waitForSignInLink } from "./support/mailpit";
import { apiPost, PASSWORD, publishIdea, runTag } from "./support/pitch-scene";
import { checkScreen } from "./support/screen";
import { totp } from "./support/totp";
import { makeD1, OWNER_DATABASE_URL } from "./support/verification";

// REQ-BIL-08 (P14-F) against the seeded stack with the simulated M-Pesa checkout (PAYMENT_PROVIDER=fake, a few
// seconds' delay): Plan & billing with the plan ladder and "Sample prices, not final" (D-44), the account menu entry,
// the M2 walkthrough step "402 → fake M-Pesa upgrade → publish" (AC-SUB-1 re-run through the screens), failed and
// cancelled simulated payments, and an organisation's owner paying for its plan. axe, one primary action and no
// horizontal scroll on every screen (AC-UX-1, AC-UX-2, AC-UX-4), in both projects (360 px and desktop).

const SERVER_STEP = { timeout: 20_000 };
// The fake provider answers after FAKE_PAYMENT_DELAY_SECONDS (4 by default); the page polls at 2 s, 3 s, 4.5 s, …
const PAYMENT_STEP = { timeout: 45_000 };

/** A complete draft, ready to publish from the editor's review step (the developer on `request` must be D1). */
async function completeDraft(request: APIRequestContext, title: string): Promise<string> {
  const niches = (await (await request.get("/api/directory/niches")).json()) as Array<{
    id: string;
    children?: Array<{ id: string }>;
  }>;
  const niche = niches.find((n) => n.children?.length)?.children?.[0]?.id ?? niches[0].id;
  const draft = await apiPost<{ id: string }>(
    request,
    "/api/me/proposals",
    {
      teaser: {
        title,
        niche_id: niche,
        county_code: "KE-47",
        maturity: "prototype",
        ask: "pilot",
        problem_statement: "Boda riders lose a day's earnings when a bike breaks down far from a mechanic.",
        summary: "Roadside repair booked by USSD, paid per job.",
      },
      confidential: { approach: "A mechanic roster by ward with a USSD booking queue." },
      new_problem: { title: `${title}: breakdowns`, statement: "Riders wait hours for help on rural roads." },
    },
    201,
  );
  return draft.id;
}

/** Ticks the three ownership statements on the editor's review step and presses Publish. */
async function publishFromReview(page: Page) {
  await expect(page.getByRole("checkbox")).toHaveCount(3, SERVER_STEP);
  // The step settles (hydration, the statements' text) before ticking, so a late render cannot untick a box.
  await page.waitForLoadState("networkidle");
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  for (const box of await page.getByRole("checkbox").all()) await expect(box).toBeChecked();
  await page.getByRole("button", { name: "Publish", exact: true }).click();
}

test.describe("a developer on the Free plan", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL raises the test developer to D1 so they can publish").toBeTruthy();
  });

  test("sees the plan ladder from the account menu", async ({ page }) => {
    await signUpDeveloper(page, "Wanjiku Kamau");
    await page.getByRole("button", { name: "Account" }).click();
    await page.getByRole("link", { name: "Plan & billing" }).click();
    await expect(page).toHaveURL(/\/billing$/, SERVER_STEP);

    await expect(page.getByRole("heading", { level: 1, name: "Plan & billing" })).toBeVisible();
    await expect(page.getByText("You are on the Free plan.")).toBeVisible();
    await expect(page.locator("[data-sample-prices]")).toHaveText("Sample prices, not final");
    const ladder = page.locator("[data-ladder] > li");
    await expect(ladder).toHaveCount(4);
    const free = page.locator("[data-plan='dev_free']");
    await expect(free).toHaveAttribute("aria-current", "true");
    await expect(free.locator("[data-your-plan]")).toHaveText("Your plan");
    await expect(free).toContainText("3 published ideas at a time");
    await expect(free).toContainText("Pitch each idea to up to 5 companies");
    const pro = page.locator("[data-plan='dev_pro_monthly']");
    await expect(pro).toContainText("KES 499 a month");
    await expect(pro).toContainText("Unlimited published ideas");
    await expect(page.locator("[data-plan='dev_pro_yearly']")).toContainText("KES 4,990 a year");
    await expect(page.locator("[data-plan='dev_student']")).toContainText("Not available to buy here yet");
    await expect(page.locator("[data-primary]")).toHaveText("Upgrade to Pro (monthly)");
    await expect(page.locator("[data-primary]")).toHaveAttribute("href", "/billing/upgrade?plan=dev_pro_monthly");
    await expect(page.getByRole("link", { name: "Choose Pro (yearly)" })).toBeVisible();
    await checkScreen(page);
  });

  test("hits the limit on the 4th publish, upgrades through the simulated M-Pesa checkout, then publishes", async ({
    page,
  }) => {
    const email = await signUpDeveloper(page, "Otieno Barasa");
    makeD1(email);
    for (let i = 1; i <= 3; i++) await publishIdea(page.request, `Boda ${i} ${runTag()}`);
    const fourth = await completeDraft(page.request, `Boda 4 ${runTag()}`);

    // AC-SUB-1 through the screens: the 4th publish is refused with the way to the next plan up.
    await page.goto(`/dev/ideas/${fourth}/edit?step=3`);
    await publishFromReview(page);
    const refusal = page.getByRole("alert").filter({ hasText: "Published ideas your plan allows: 3." });
    await expect(refusal).toBeVisible(SERVER_STEP);
    await refusal.getByRole("link", { name: "Upgrade your plan" }).click();
    await expect(page).toHaveURL(/\/billing\/upgrade\?plan=dev_pro_monthly&next=/, SERVER_STEP);

    // Confirm: plan, price, labels, one primary action.
    await expect(page.getByRole("heading", { level: 1, name: "Upgrade to Pro (monthly)" })).toBeVisible();
    await expect(page.locator("[data-simulated]")).toHaveText("Simulated M-Pesa");
    await expect(page.locator("[data-price]")).toHaveText("KES 499 a month");
    await expect(page.locator("[data-sample-prices]")).toHaveText("Sample prices, not final");
    await expect(page.getByRole("list", { name: "Payment steps" }).locator("[aria-current='step']")).toHaveText(
      "Confirm",
    );
    await expect(page.getByRole("radio", { name: "The payment is confirmed" })).toBeChecked();
    await checkScreen(page);
    await page.getByRole("button", { name: "Start the simulated payment" }).click();

    // Waiting (a simulated checkout says so instead of "Check your phone"), then the fake provider's answer.
    await expect(page.getByRole("heading", { name: "Waiting for the simulated payment" })).toBeVisible(SERVER_STEP);
    await expect(page.getByRole("status").filter({ hasText: "Waiting for the payment to be confirmed" })).toBeVisible();
    await expect(page).toHaveURL(/checkout=[0-9a-f-]{36}/);
    await checkScreen(page);
    await expect(page.getByRole("heading", { name: "Payment confirmed" })).toBeVisible(PAYMENT_STEP);
    await expect(page.getByText("You are now on Pro (monthly).")).toBeVisible();
    await checkScreen(page);

    // Back where the refusal was: the 4th idea publishes on Pro.
    await page.getByRole("link", { name: "Continue where you left off" }).click();
    await expect(page).toHaveURL(new RegExp(`/dev/ideas/${fourth}/edit\\?step=3$`), SERVER_STEP);
    await publishFromReview(page);
    await expect(page).toHaveURL(new RegExp(`/dev/ideas/${fourth}\\?published=1$`), SERVER_STEP);

    // Plan & billing now shows Pro as the plan, with no upgrade offered and no way down.
    await page.goto("/billing");
    await expect(page.getByText("You are on the Pro (monthly) plan.")).toBeVisible();
    await expect(page.locator("[data-plan='dev_pro_monthly']")).toHaveAttribute("aria-current", "true");
    await expect(page.locator("[data-primary]")).toHaveCount(0);
    await expect(page.locator("[data-plan='dev_free'] a")).toHaveCount(0);
    // Buying the same plan again is not offered.
    await page.goto("/billing/upgrade?plan=dev_pro_monthly");
    await expect(page.locator("[data-empty-state] p")).toHaveText("You are already on Pro (monthly).");
    // Nor is the free plan, which costs nothing.
    await page.goto("/billing/upgrade?plan=dev_free");
    await expect(page.locator("[data-empty-state] p")).toHaveText(
      "The Free plan costs nothing, so there is nothing to buy.",
    );
  });

  test("keeps the Free plan when the simulated payment fails or is cancelled", async ({ page }) => {
    await signUpDeveloper(page, "Akinyi Njoroge");
    await page.goto("/billing/upgrade?plan=dev_pro_yearly");
    await expect(page.locator("[data-price]")).toHaveText("KES 4,990 a year", SERVER_STEP);

    await page.getByRole("radio", { name: "There is too little money" }).check();
    await page.getByRole("button", { name: "Start the simulated payment" }).click();
    await expect(page.getByRole("heading", { name: "Payment not completed" })).toBeVisible(PAYMENT_STEP);
    await expect(page.locator("main").getByRole("alert")).toHaveText(
      "The M-Pesa account had too little money, so your plan has not changed.",
    );
    await expect(page.locator("[data-primary]")).toHaveText("Try again");
    await expect(page.getByRole("link", { name: "Back to Plan & billing" })).toHaveAttribute("href", "/billing");
    await checkScreen(page);

    await page.getByRole("button", { name: "Try again" }).click();
    await page.getByRole("radio", { name: "The payment is cancelled" }).check();
    await page.getByRole("button", { name: "Start the simulated payment" }).click();
    await expect(page.getByRole("heading", { name: "Payment cancelled" })).toBeVisible(PAYMENT_STEP);
    await checkScreen(page);

    await page.goto("/billing");
    await expect(page.getByText("You are on the Free plan.")).toBeVisible();
  });

  test("gets one sentence and one action for a plan that cannot be bought here", async ({ page }) => {
    await signUpDeveloper(page, "Chebet Rotich");
    for (const [path, sentence] of [
      ["/billing/upgrade?plan=dev_free", "You are already on Free."],
      ["/billing/upgrade?plan=dev_student", "Student cannot be bought here yet."],
      ["/billing/upgrade?plan=org_starter", "This plan is not on the list."],
      ["/billing/upgrade?plan=..%2Fadmin", "This plan is not on the list."],
    ] as const) {
      await page.goto(path);
      await expect(page.locator("[data-empty-state] p"), path).toHaveText(sentence);
      await expect(page.locator("[data-empty-state] a"), path).toHaveText(
        path.endsWith("dev_free") ? "Back to Plan & billing" : "See all plans",
      );
      // The empty state's action is the one way on: no page back link beside it.
      await expect(page.locator("[data-page-back]"), path).toHaveCount(0);
      await expect(page.locator("main a"), path).toHaveCount(1);
    }
    await checkScreen(page);
  });
});

/** A new organisation's owner with two-step sign-in on and fresh, signed in in a browser context of its own. */
async function orgOwner(browser: Browser, baseURL: string) {
  const context = await browser.newContext({ baseURL });
  const request = context.request;
  const id = runTag();
  const email = `amina-${id}@buyer-${id}.example.com`;
  const orgName = `Maji ${id} Limited`;
  const csrf = async () => ((await (await request.get("/api/auth/csrf")).json()) as { csrf_token: string }).csrf_token;
  const signup = await request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": await csrf() },
    data: {
      email,
      password: PASSWORD,
      accept_terms: true,
      display_name: "Amina Hassan",
      side: "org",
      org: { legal_name: orgName, kind: "company" },
    },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  const link = await waitForSignInLink(request, email);
  await apiPost(request, "/api/auth/magic-link/consume", { token: new URL(link).hash.replace(/^#token=/, "") });
  const { secret } = await apiPost<{ secret: string }>(request, "/api/auth/totp/enrol", { password: PASSWORD });
  await apiPost(request, "/api/auth/totp/confirm", { code: totp(secret) });
  const me = (await (await request.get("/api/auth/me")).json()) as {
    memberships: Array<{ org_id: string; org_name: string }>;
  };
  const orgId = me.memberships.find((m) => m.org_name === orgName)?.org_id;
  expect(orgId, "the new organisation").toBeTruthy();
  return { page: await context.newPage(), orgId: orgId!, orgName, close: () => context.close() };
}

test("an organisation's owner upgrades its plan to Starter", async ({ browser, baseURL }) => {
  const owner = await orgOwner(browser, baseURL!);
  try {
    const { page } = owner;
    await page.goto("/billing");
    await expect(page.getByText(`For ${owner.orgName}`)).toBeVisible(SERVER_STEP);
    await expect(page.getByText("You are on the Claimed (Free) plan.")).toBeVisible();
    await expect(page.locator("[data-plan='org_starter']")).toContainText("KES 15,000 a month");
    await expect(page.locator("[data-plan='org_growth']")).toContainText("5 Scout Agents");
    await expect(page.locator("[data-plan='org_enterprise']")).toContainText("Not available to buy here yet");
    await checkScreen(page);
    await page.locator("[data-primary]").click();
    await expect(page).toHaveURL(new RegExp(`/billing/upgrade\\?plan=org_starter&org=${owner.orgId}$`), SERVER_STEP);
    await page.getByRole("button", { name: "Start the simulated payment" }).click();
    await expect(page.getByRole("heading", { name: "Payment confirmed" })).toBeVisible(PAYMENT_STEP);
    await expect(page.getByText("You are now on Starter.")).toBeVisible();
    await page.getByRole("link", { name: "See your plan" }).click();
    await expect(page).toHaveURL(new RegExp(`/billing\\?org=${owner.orgId}$`), SERVER_STEP);
    await expect(page.getByText("You are on the Starter plan.")).toBeVisible(SERVER_STEP);
    await expect(page.locator("[data-primary]")).toHaveText("Upgrade to Growth");
    // Another organisation's id never switches the page to it.
    await page.goto("/billing?org=0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f");
    await expect(page.locator("[data-empty-state] p")).toHaveText("This organisation is not one of yours.");
  } finally {
    await owner.close();
  }
});
