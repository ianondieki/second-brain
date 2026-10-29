import type { components } from "@/lib/api/schema";

export type ConsentTexts = components["schemas"]["ConsentTexts"];

/** The optional consents signup offers, in screen order. Other purposes are asked for where they apply. */
export const SIGNUP_CONSENTS = ["marketing", "reminders", "whatsapp", "profiling"] as const;
export type SignupConsent = (typeof SIGNUP_CONSENTS)[number];

/** What the signup form shows: the server's exact wording (the recorded source of truth) and its version. */
export interface ShownConsents {
  version: string;
  items: Array<{ purpose: SignupConsent; text: string }>;
}

/** Picks the signup purposes from GET /api/consents, keeping screen order and skipping any the server lacks. */
export function signupConsents(texts: ConsentTexts): ShownConsents {
  const byPurpose = new Map(texts.purposes.map((item) => [item.purpose, item.text]));
  return {
    version: texts.version,
    items: SIGNUP_CONSENTS.flatMap((purpose) => {
      const text = byPurpose.get(purpose);
      return text ? [{ purpose, text }] : [];
    }),
  };
}

/** One decision per consent shown (unticked is an explicit false); nothing for purposes that were not shown. */
export function consentDecisions(
  shown: ShownConsents,
  ticked: Partial<Record<SignupConsent, boolean>>,
): Record<string, boolean> {
  return Object.fromEntries(shown.items.map(({ purpose }) => [purpose, ticked[purpose] === true]));
}
