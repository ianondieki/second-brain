import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { Closing } from "./Closing";
import { Hero } from "./Hero";
import { LandingFooter } from "./LandingFooter";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD): in the public demo the landing's main call to action goes to
// /login's persona picker, and no sign-up link is offered (sign-up is switched off there). Off: as before.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

async function renderCalls() {
  return renderWithIntl(
    <>
      {await resolveServerTree(<Hero />)}
      {await resolveServerTree(<Closing />)}
      {await resolveServerTree(<LandingFooter />)}
    </>,
  );
}

describe("the landing's calls to action", () => {
  it("go to the persona picker in the public demo, with no sign-up link anywhere", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { container } = await renderCalls();
    const primary = container.querySelector<HTMLAnchorElement>("a[data-primary]")!;
    expect(primary.getAttribute("href")).toBe("/login");
    expect(primary.textContent).toBe("Try the demo");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    // The hero, the closing call and the footer's /login link (it says "Try the demo" too: ux review of P28-PD, MINOR 6).
    expect(screen.getAllByRole("link", { name: "Try the demo" }).map((a) => a.getAttribute("href"))).toEqual(["/login", "/login", "/login"]);
    expect(container.querySelector('a[href="/signup"]')).toBeNull();
  });

  it("are today's with the mode off: create an account, and the sign-up links", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    const { container } = await renderCalls();
    const primary = container.querySelector<HTMLAnchorElement>("a[data-primary]")!;
    expect(primary.getAttribute("href")).toBe("/signup");
    expect(primary.textContent).toBe(en.landing.signUp);
    expect(screen.queryByRole("link", { name: "Try the demo" })).toBeNull();
    expect(container.querySelectorAll('a[href="/signup"]').length).toBe(3);
  });
});
