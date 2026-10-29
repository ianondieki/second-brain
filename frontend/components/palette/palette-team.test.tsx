import { createTranslator } from "next-intl";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";

import { PaletteSlot } from "./PaletteSlot";
import type { PaletteData } from "./types";

// REQ-TEN-02: the organisation's Team is in the palette's Go to list after the portal's five sections (it has no tab of
// its own), keeping the chosen organisation; the developer's palette has no Team.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("@/lib/api/server", () => ({ getMe: async () => null }));

async function goTo(homeHref: string) {
  const slot = (await PaletteSlot({ homeHref })) as ReactElement<{ data: PaletteData }>;
  return slot.props.data.goTo;
}

describe("Team in the command palette", () => {
  it("follows the organisation's sections, with ?org= kept", async () => {
    const links = await goTo("/org?org=0199c000-0000-7000-8000-0000000000a1");
    expect(links.map((l) => l.id).slice(0, 6)).toEqual([
      "go-home",
      "go-inbox",
      "go-engagements",
      "go-problems",
      "go-events",
      "go-team",
    ]);
    expect(links.find((l) => l.id === "go-team")).toEqual({
      id: "go-team",
      title: "Team",
      href: "/org/team?org=0199c000-0000-7000-8000-0000000000a1",
    });
  });

  it("is not offered on the developer's screens", async () => {
    expect((await goTo("/dev")).some((l) => l.id === "go-team")).toBe(false);
  });
});
