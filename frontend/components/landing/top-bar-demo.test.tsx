import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { LandingContent } from "./LandingContent";
import { LandingFooter } from "./LandingFooter";
import { PublicFrame } from "./PublicFrame";

// REQ-FND-04 (ux review of P28-PD, MINOR 6): in the public demo /login is the persona picker, so the landing's top bar,
// the public pages' top bar and the footer say "Try the demo" where they say "Log in" otherwise; every one of those
// links, and the footer's small links, is a target of at least 44 px each way (min-h-11 and min-w-11).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
// The landing's sections are not under test here: only its top bar and footer are.
vi.mock("./Hero", () => ({ Hero: () => null }));
vi.mock("./Counties", () => ({ Counties: () => null }));
vi.mock("./HowItWorks", () => ({ HowItWorks: () => null }));
vi.mock("./Reasons", () => ({ Reasons: () => null }));
vi.mock("./Features", () => ({ Features: () => null }));
vi.mock("./Activity", () => ({ Activity: () => null }));
vi.mock("./Proof", () => ({ Proof: () => null }));
vi.mock("./Questions", () => ({ Questions: () => null }));
vi.mock("./Closing", () => ({ Closing: () => null }));

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

const TRY = "Try the demo";
const LOG_IN = en.landing.logIn;

/** A 44 px target: both minimums on the link itself. */
function expectTarget(link: HTMLElement) {
  expect(link.className).toMatch(/\bmin-h-11\b/);
  expect(link.className).toMatch(/\bmin-w-11\b/);
}

async function draw(node: React.ReactNode) {
  return renderWithIntl(<>{await resolveServerTree(node)}</>);
}

describe.each([
  ["the landing", () => <LandingContent />],
  ["a public page", () => <PublicFrame>page</PublicFrame>],
])("%s's top bar and footer", (_, page) => {
  it("say \"Try the demo\" for /login in the public demo, and never \"Log in\"", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    await draw(page());
    const bar = document.querySelector<HTMLElement>("[data-top-bar]")!;
    const link = within(bar).getByRole("link", { name: TRY });
    expect(link.getAttribute("href")).toBe("/login");
    expectTarget(link);
    const footer = document.querySelector("footer")!;
    expect(within(footer).getByRole("link", { name: TRY }).getAttribute("href")).toBe("/login");
    expect(screen.queryByRole("link", { name: LOG_IN })).toBeNull();
  });

  it("say \"Log in\" with the mode off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    await draw(page());
    const bar = document.querySelector<HTMLElement>("[data-top-bar]")!;
    const link = within(bar).getByRole("link", { name: LOG_IN });
    expect(link.getAttribute("href")).toBe("/login");
    expectTarget(link);
    expect(within(document.querySelector("footer")!).getByRole("link", { name: en.landing.footer.logIn })).toBeTruthy();
    expect(screen.queryByRole("link", { name: TRY })).toBeNull();
  });
});

describe("the footer's small links", () => {
  it.each([["on", "true"], ["off", "false"]])("are each at least 44 px each way with the mode %s", async (_, value) => {
    vi.stubEnv("PUBLIC_DEMO", value);
    await draw(<LandingFooter />);
    const links = within(document.querySelector("footer")!).getAllByRole("link");
    // The wordmark is a link home of its own size; every link in the three lists is a small one.
    const listed = links.filter((link) => link.closest("li"));
    expect(listed.length).toBeGreaterThan(5);
    for (const link of listed) expectTarget(link);
  });
});
