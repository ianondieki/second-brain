import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Me } from "@/lib/auth/routing";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { HomeContent } from "./HomeContent";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD): in the public demo, setting up two-step sign-in is switched off for
// the shared personas, so the developer's Home does not send them to it.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/tour/FirstLoginTour", () => ({ FirstLoginTour: () => null }));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));

const ME = { user: { display_name: "Brian" }, mfa: { enrolled: false, required: false, verified: false } } as unknown as Me;

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

async function home() {
  const tree = await HomeContent({ me: ME, engagements: [], ideas: [], recommended: { kind: "unavailable" }, now: "2026-10-07T07:40:00Z" });
  return renderWithIntl(<>{await resolveServerTree(tree)}</>);
}

describe("Home's two-step sign-in notice", () => {
  it("shows while two-step sign-in is off, with the mode off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    const { container } = await home();
    expect(container.querySelector("[data-home='security']")).not.toBeNull();
  });

  it("is left out in the public demo", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { container } = await home();
    expect(container.querySelector("[data-home='security']")).toBeNull();
    expect(container.querySelector("a[href='/settings/security']")).toBeNull();
  });
});
