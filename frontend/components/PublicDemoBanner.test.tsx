import { cleanup, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createTranslator } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useStrings } from "@/components/ClientStrings";
import en from "@/locales/en.json";
import { resolveServerTree } from "@/test/server-tree";

import {
  DEMO_BANNER_HIDDEN_ATTRIBUTE,
  DEMO_BANNER_NOSCRIPT_CSS,
  DEMO_BANNER_SCRIPT,
  DEMO_BANNER_STORAGE_KEY,
  PublicDemoBanner,
} from "./PublicDemoBanner";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD; AT-PD-6): a slim banner on every page while the public demo is
// on, dismissible for the browser session, server-rendered with no client bundle of its own.

vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getMessages: async () => en,
  getTranslations: async (namespace?: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

const SENTENCE =
  "Public demo: every name and organisation here is fictional, and the data resets every night at 03:00 EAT. Please don't enter real personal information.";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  sessionStorage.clear();
  document.documentElement.removeAttribute(DEMO_BANNER_HIDDEN_ATTRIBUTE);
});

describe("the banner", () => {
  it("is a labelled region with the card's sentence, the label in bold, and a named dismiss button", async () => {
    render(<>{await resolveServerTree(<PublicDemoBanner />)}</>);
    const region = screen.getByRole("region", { name: "Public demo notice" });
    expect(region.querySelector("p")?.textContent).toBe(SENTENCE);
    expect(within(region).getByText("Public demo:").tagName).toBe("STRONG");
    const dismiss = within(region).getByRole("button", { name: "Hide the demo notice" });
    expect(dismiss.className).toMatch(/\bsize-11\b/); // a 44 px target
    expect(region.className).not.toMatch(/\b(fixed|sticky|absolute)\b/); // in the flow: it never covers content
  });

  it("is hidden by a rule outside any layer once <html> carries the dismissed mark", () => {
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    expect(css).toMatch(/html\[data-demo-banner-hidden\] \[data-demo-banner\] \{\s*display: none;\s*\}/);
  });
});

describe("dismissal (the inline script)", () => {
  const run = () => new Function(DEMO_BANNER_SCRIPT)();

  beforeEach(() => {
    document.body.innerHTML =
      '<section data-demo-banner=""><p>x</p><button type="button" data-demo-dismiss=""><svg><path/></svg></button></section>' +
      '<main id="main" tabindex="-1"><h1>Page</h1></main>';
  });

  it("leaves the banner shown on a first visit", () => {
    run();
    expect(document.documentElement.hasAttribute(DEMO_BANNER_HIDDEN_ATTRIBUTE)).toBe(false);
  });

  it("hides it before paint when this session dismissed it (nothing to shift on hydrate)", () => {
    sessionStorage.setItem(DEMO_BANNER_STORAGE_KEY, "1");
    run();
    expect(document.documentElement.hasAttribute(DEMO_BANNER_HIDDEN_ATTRIBUTE)).toBe(true);
  });

  it("on a press (the icon inside the button too), hides it, remembers it for the session and moves focus to main", () => {
    run();
    document.querySelector("[data-demo-dismiss] path")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(document.documentElement.hasAttribute(DEMO_BANNER_HIDDEN_ATTRIBUTE)).toBe(true);
    expect(sessionStorage.getItem(DEMO_BANNER_STORAGE_KEY)).toBe("1");
    expect(document.activeElement).toBe(document.getElementById("main"));
  });

  it("ignores every other press", () => {
    run();
    document.querySelector("h1")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(document.documentElement.hasAttribute(DEMO_BANNER_HIDDEN_ATTRIBUTE)).toBe(false);
    expect(sessionStorage.getItem(DEMO_BANNER_STORAGE_KEY)).toBeNull();
  });

  it("uses the session's storage, never localStorage (dismissal lasts for the browser session only)", () => {
    expect(DEMO_BANNER_SCRIPT).toContain("sessionStorage");
    expect(DEMO_BANNER_SCRIPT).not.toContain("localStorage");
    expect(DEMO_BANNER_NOSCRIPT_CSS).toBe("[data-demo-dismiss]{display:none}");
  });
});

describe("the root layout", () => {
  /** What the sign-out controls read (components/SignOutButton.tsx and the account menu's fallback). */
  function SignOutLabels() {
    const t = useStrings("shell");
    return <main id="main">{[t("signOut"), t("signingOut"), t("signOutRetry")].join("|")}</main>;
  }

  async function layoutMarkup() {
    const { default: RootLayout } = await import("@/app/layout");
    const tree = await resolveServerTree(await RootLayout({ children: <SignOutLabels />, params: Promise.resolve({}) } as never));
    return renderToStaticMarkup(<>{tree}</>);
  }

  it("names sign-out \"Switch persona\" while on (it lands on /login's picker), and leaves it as it was while off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    expect(await layoutMarkup()).toContain("Switch persona|Switching…|Try switching again");
    vi.stubEnv("PUBLIC_DEMO", "false");
    expect(await layoutMarkup()).toContain("Sign out|Signing out…|Try signing out again");
  });

  it("draws the banner first in <body>, with its script and noscript style, while PUBLIC_DEMO is on", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const html = await layoutMarkup();
    const body = html.slice(html.indexOf("<body"));
    expect(body.indexOf("data-demo-banner")).toBeGreaterThan(-1);
    expect(body.indexOf("data-demo-banner")).toBeLessThan(body.indexOf('id="main"'));
    expect(html).toContain(DEMO_BANNER_STORAGE_KEY);
    expect(html).toContain(DEMO_BANNER_NOSCRIPT_CSS);
  });

  it("draws none of it while the mode is off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    const html = await layoutMarkup();
    expect(html).not.toContain("data-demo-banner");
    expect(html).not.toContain(DEMO_BANNER_STORAGE_KEY);
    expect(html).not.toContain("data-demo-dismiss");
  });

  it("asks search engines not to index the pages while on, and says nothing while off", async () => {
    const { generateMetadata } = await import("@/app/layout");
    vi.stubEnv("PUBLIC_DEMO", "on");
    expect((await generateMetadata()).robots).toEqual({ index: false, follow: false });
    vi.stubEnv("PUBLIC_DEMO", "");
    expect((await generateMetadata()).robots).toBeUndefined();
  });
});
