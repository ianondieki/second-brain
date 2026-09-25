import { describe, expect, it } from "vitest";

import { consentDecisions, signupConsents, type ConsentTexts } from "./consents";

const texts: ConsentTexts = {
  version: "2026-09-24.1",
  purposes: [
    { purpose: "profiling", text: "Use my niches and activity to recommend problems." },
    { purpose: "github_import", text: "Read my linked GitHub repositories." },
    { purpose: "marketing", text: "Send me occasional product news by email." },
    { purpose: "whatsapp", text: "Send me reminders on WhatsApp." },
    { purpose: "reminders", text: "Send me reminders by email." },
  ],
};

describe("signupConsents", () => {
  it("keeps the four signup purposes in screen order with the server's exact wording and version", () => {
    const shown = signupConsents(texts);
    expect(shown.version).toBe("2026-09-24.1");
    expect(shown.items.map((item) => item.purpose)).toEqual(["marketing", "reminders", "whatsapp", "profiling"]);
    expect(shown.items[0].text).toBe("Send me occasional product news by email.");
  });

  it("skips a signup purpose the server does not describe", () => {
    const shown = signupConsents({ version: "v", purposes: texts.purposes.filter((p) => p.purpose !== "whatsapp") });
    expect(shown.items.map((item) => item.purpose)).toEqual(["marketing", "reminders", "profiling"]);
  });
});

describe("consentDecisions", () => {
  it("sends one decision per consent shown, unticked as false, and nothing else", () => {
    const shown = signupConsents(texts);
    expect(consentDecisions(shown, { reminders: true })).toEqual({
      marketing: false,
      reminders: true,
      whatsapp: false,
      profiling: false,
    });
  });
});
