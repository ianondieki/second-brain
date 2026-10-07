// The JS budget per route (docs/spec/07 item 5, REQ-UX-05): at most 150 KB of gzipped JavaScript, where
// 1 KB = 1,000 bytes, so 150,000 bytes. Counted: every script the route fetches in a real browser until the network
// is idle, lazily loaded chunks included, each at its gzip-compressed size (the server's gzip, or gzip at the default
// level when a response is not compressed). With --first-edit the count continues through the first keystroke in the
// page's first text field (chunks that load on the first edit, such as the idea editor's save calls, count too). With
// --press=<name> it then presses the button of that accessible name and counts the chunks that load with it (the idea
// editor's writing assistant panel: --press="Suggest a clearer teaser").
// Response headers are printed alongside (their HTTP/1.1 size), since Lighthouse's transfer size includes them
// (DECISIONS-NEEDED D-28).
//
// Usage, against a production build (the `make dev` web container, or `npm run build && npm run start`):
//   npm run budget                                        the default routes: / /explore /credits /login /signup /settings/security
//   npm run budget -- /dev/ideas/new --first-edit         named routes (the leading slash is optional)
//   npm run budget -- /org --allow-skip                   a redirect is a skip, not a failure
//   npm run budget -- /dev/ideas/<id>/edit --press="Suggest a clearer teaser"   after pressing a button
// BUDGET_BASE_URL  the web app (default http://localhost:3000; http or https).
// BUDGET_COOKIE    a Cookie header for signed-in routes, e.g. "__Host-bridge_session=<token>" of a test account.
// Needs Playwright's Chromium (PLAYWRIGHT_BROWSERS_PATH where it is installed). --first-edit types into the page, so
// it changes the account's data (a new idea's first keystroke creates a draft): test accounts only.
// Exits 1 when a route is over the budget, fails to load, or is skipped because it redirects (a signed-in route
// without BUDGET_COOKIE) unless --allow-skip is given.
import { chromium } from "@playwright/test";
import { gzipSync } from "node:zlib";

const BUDGET_BYTES = 150_000;
const DEFAULT_ROUTES = ["/", "/explore", "/credits", "/login", "/signup", "/settings/security"];
const SETTLE_MS = 1500; // after "networkidle", for chunks requested by effects that run once the page is idle

const base = new URL(process.env.BUDGET_BASE_URL ?? "http://localhost:3000");
const cookie = process.env.BUDGET_COOKIE;
const args = process.argv.slice(2);
const allowSkip = args.includes("--allow-skip");
const firstEdit = args.includes("--first-edit");
const press = args.find((arg) => arg.startsWith("--press="))?.slice("--press=".length);
const named = args.filter((arg) => !arg.startsWith("--")).map((arg) => (arg.startsWith("/") ? arg : `/${arg}`));
const routes = named.length > 0 ? named : DEFAULT_ROUTES;

function cookies() {
  if (!cookie) return [];
  return cookie.split(/;\s*/).filter(Boolean).map((pair) => {
    const at = pair.indexOf("=");
    const name = pair.slice(0, at);
    // __Host- cookies must be Secure; Chromium treats http://localhost as a secure context.
    return { name, value: pair.slice(at + 1), domain: base.hostname, path: "/", secure: true, sameSite: "Lax" };
  });
}

async function measure(browser, route) {
  const context = await browser.newContext({ viewport: { width: 360, height: 640 } });
  await context.addCookies(cookies());
  const page = await context.newPage();
  const scripts = new Map();
  const reads = [];
  page.on("response", (response) => {
    const type = response.headers()["content-type"] ?? "";
    if (response.request().resourceType() !== "script" && !type.includes("javascript")) return;
    reads.push(
      (async () => {
        const body = await response.body().catch(() => null);
        if (!body) return;
        const encoded = response.headers()["content-encoding"] === "gzip";
        const sizes = await response.request().sizes().catch(() => null);
        const gz = encoded && sizes ? sizes.responseBodySize : gzipSync(body).length;
        const headerBytes = sizes ? sizes.responseHeadersSize : 0;
        scripts.set(response.url(), { gz, headerBytes });
      })(),
    );
  });
  try {
    const response = await page.goto(new URL(route, base).href, { waitUntil: "networkidle" });
    const landed = new URL(page.url());
    if (`${landed.pathname}${landed.search}` !== route) return { skipped: `redirected to ${landed.pathname}` };
    if (!response || response.status() !== 200) return { failed: `the page answered ${response?.status()}` };
    await page.waitForTimeout(SETTLE_MS);
    if (firstEdit) {
      const field = page.locator("main input[type=text]:enabled, main textarea:enabled").first();
      if (await field.count()) {
        await field.focus();
        await page.keyboard.type("x");
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(SETTLE_MS + 1500); // the editor saves 1.2 s after typing stops
      }
    }
    if (press) {
      const button = page.getByRole("button", { name: press, exact: true });
      if ((await button.count()) === 0) return { failed: `no button named "${press}"` };
      await button.first().click();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(SETTLE_MS);
    }
    await Promise.all(reads);
    const values = [...scripts.values()];
    return {
      bytes: values.reduce((sum, s) => sum + s.gz, 0),
      headerBytes: values.reduce((sum, s) => sum + s.headerBytes, 0),
      count: values.length,
    };
  } catch (error) {
    return { failed: error instanceof Error ? error.message : String(error) };
  } finally {
    await context.close();
  }
}

const browser = await chromium.launch();
let failed = false;
for (const route of routes) {
  const result = await measure(browser, route);
  if (result.skipped) {
    console.log(`${route}: skipped (${result.skipped})`);
    if (!allowSkip) failed = true;
    continue;
  }
  if (result.failed) {
    console.log(`${route}: FAILED (${result.failed})`);
    failed = true;
    continue;
  }
  const over = result.bytes > BUDGET_BYTES;
  if (over) failed = true;
  const when = [firstEdit ? " through the first edit" : "", press ? ` after pressing "${press}"` : ""].join("");
  console.log(
    `${route}: ${result.bytes} bytes of gzipped JS in ${result.count} scripts${when} (budget ${BUDGET_BYTES}): ` +
      `${over ? "OVER" : "ok"}; ${result.bytes + result.headerBytes} with response headers`,
  );
}
await browser.close();
process.exit(failed ? 1 : 0);
