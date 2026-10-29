import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";

import { clientStrings, pickedStrings } from "./client-strings";

// Server-formatted strings for client components (lib/i18n/client-strings.ts): whole namespaces with "{name}" left
// for the browser to fill, or only the chosen messages of a namespace (P16-D: the scout form's maturity labels, the
// security page's password hint).

vi.mock("next-intl/server", () => ({
  getMessages: async () => en,
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

describe("clientStrings", () => {
  it("formats whole namespaces and leaves the placeholders for the browser", async () => {
    const { security } = await clientStrings(["security"]);
    expect((security as Record<string, string>).title).toBe(en.security.title);
    expect((security as Record<string, string>).cancelled).toContain("{product}");
  });
});

describe("pickedStrings", () => {
  it("sends only the chosen messages or groups of a namespace", async () => {
    expect(await pickedStrings("ideaFields", ["maturityValue"])).toEqual({
      ideaFields: { maturityValue: en.ideaFields.maturityValue },
    });
    expect(await pickedStrings("signup", ["passwordHint"])).toEqual({ signup: { passwordHint: en.signup.passwordHint } });
  });
});
