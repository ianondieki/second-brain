import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { OrgRefusal } from "./OrgRefusal";

// The organisation screens' refusals before anything shows (P10-F review MAJOR 4): the Inbox's two-step sentences, each
// with its action as the screen's one primary button, or "not available" with the given way back.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(cleanup);

const BACK = { href: "/org/inbox?tab=matches", action: "Back to scout matches" };

async function show(refusal: Parameters<typeof OrgRefusal>[0]["refusal"]) {
  return renderWithIntl(await OrgRefusal({ refusal, orgName: "Maziwa Buyers", back: BACK }));
}

describe("an organisation screen's refusal", () => {
  it("asks to turn on two-step sign-in, as the primary action", async () => {
    await show("mfa_enrolment_required");
    expect(screen.getByText(en.inbox.refusedMfaSetup.replace("{org}", "Maziwa Buyers"))).toBeTruthy();
    const action = screen.getByRole("link", { name: en.orgProposal.action.turnOnMfa });
    expect(action.getAttribute("href")).toBe("/settings/security");
    expect(action.hasAttribute("data-primary")).toBe(true);
  });

  it("asks for the code, as the primary action", async () => {
    await show("mfa_required");
    expect(screen.getByText(en.inbox.refusedMfaCode)).toBeTruthy();
    const action = screen.getByRole("link", { name: en.orgProposal.action.enterCode });
    expect(action.getAttribute("href")).toBe("/auth/mfa");
    expect(action.hasAttribute("data-primary")).toBe(true);
  });

  it("says it is not available, with the given way back and no primary action", async () => {
    await show("not_found");
    expect(screen.getByText(en.inbox.refusedNotFound)).toBeTruthy();
    expect(screen.getByRole("link", { name: BACK.action }).getAttribute("href")).toBe(BACK.href);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });
});
