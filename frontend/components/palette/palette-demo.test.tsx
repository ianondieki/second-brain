import { createTranslator } from "next-intl";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";

import { PaletteSlot } from "./PaletteSlot";
import type { PaletteData } from "./types";

// REQ-FND-04: in the public demo the command palette's sign-out reads "Switch persona", as the account menu's does.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("@/lib/api/server", () => ({ getMe: async () => null }));

afterEach(() => vi.unstubAllEnvs());

async function signOutLabel() {
  const slot = (await PaletteSlot({ homeHref: "/dev" })) as ReactElement<{ data: PaletteData }>;
  return slot.props.data.strings.signOut;
}

describe("the palette's sign-out", () => {
  it("reads \"Switch persona\" in the public demo", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    expect(await signOutLabel()).toBe("Switch persona");
  });

  it("reads \"Sign out\" with the mode off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    expect(await signOutLabel()).toBe(en.shell.signOut);
  });
});
