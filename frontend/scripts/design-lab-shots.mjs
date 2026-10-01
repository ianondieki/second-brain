// Screenshots of the design lab (P18 step 1): every screen under every direction, light and dark, at 375 and 1440 px,
// into docs/demo/directions/<direction>/. Needs `npm run dev` on port 3000 (the lab is a development-only route) and
// Playwright's Chromium (PLAYWRIGHT_CHROMIUM, default /opt/pw-browsers/chromium or Playwright's own install).
//   node scripts/design-lab-shots.mjs            all
//   node scripts/design-lab-shots.mjs a tracker  one direction and/or screen
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "@playwright/test";

const BASE = process.env.LAB_BASE_URL ?? "http://localhost:3000";
const OUT = join(import.meta.dirname, "..", "..", "docs", "demo", "directions");
const DIRECTIONS = ["a", "b", "c"];
const SCREENS = ["landing", "home", "certificate", "tracker", "proposal", "checkout", "checkout-success", "email", "tokens"];
const WIDTHS = [375, 1440];
const THEMES = ["light", "dark"];
const only = process.argv.slice(2);
const wanted = (list) => (only.some((x) => list.includes(x)) ? list.filter((x) => only.includes(x)) : list);

const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM ?? "/opt/pw-browsers/chromium" });
try {
  for (const direction of wanted(DIRECTIONS)) {
    mkdirSync(join(OUT, direction), { recursive: true });
    for (const screen of wanted(SCREENS)) {
      const route = screen === "checkout-success" ? "checkout" : screen;
      const variant = screen === "checkout-success" ? "&variant=success" : "";
      for (const theme of THEMES) {
        for (const width of WIDTHS) {
          const page = await browser.newPage({
            viewport: { width, height: width < 600 ? 812 : 900 },
            deviceScaleFactor: 1,
            colorScheme: theme,
            reducedMotion: "no-preference",
          });
          await page.goto(`${BASE}/design-lab/${direction}/${route}?theme=${theme}&bare=1${variant}`, { waitUntil: "networkidle" });
          await page.evaluate(() => document.fonts.ready);
          // Not part of any direction: Next's dev indicator; and the fixed tab bar sits at the page's end in a full-page shot.
          await page.addStyleTag({ content: "nextjs-portal{display:none!important}[data-direction]{position:relative}@media (width < 64rem){[data-tab-bar]{position:absolute!important}}" });
          if (screen === "checkout-success") await page.waitForSelector("[data-phase='succeeded']", { timeout: 15000 });
          await page.waitForTimeout(400);
          const file = join(OUT, direction, `${screen}-${theme}-${width}.jpg`);
          await page.screenshot({ path: file, fullPage: true, type: "jpeg", quality: 78 });
          console.log(file);
          await page.close();
        }
      }
    }
  }
} finally {
  await browser.close();
}
