import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

// The notification settings' pure parts (REQ-CON-01, REQ-NOT-03; docs/spec/07 item 1 "Notification settings"). The
// page offers the consents that decide which messages are sent: email reminders (EM7 and the organisation digest,
// bridge/reminders/dispatch.py), product news by email, and WhatsApp (Release 2, not available yet). The other
// purposes GET /api/me/consents lists are asked for where they apply: `profiling` with liked niches (P12-F's Discover
// niches page), `github_import` at GitHub connect (Release 2), `tier2_llm_moderation` per proposal (docs/spec/06
// 6.12). Emails about a step of an engagement (approval, signatures, decline, dispute, termination) cannot be muted
// (docs/spec/06 6.10), so they are not choices here.

export type ConsentItem = components["schemas"]["ConsentItem"];
export type ConsentDecision = components["schemas"]["ConsentDecision"];
export type PreferenceItem = components["schemas"]["PreferenceOut"];
export type PreferenceIn = components["schemas"]["PreferenceIn"];

/**
 * A notification preference as the page shows it (GET /api/me/notification-preferences, a store of its own beside the
 * consents): its kind and channel, the person's choice, and its label in the page's language (the API's English
 * label when the page has none of its own).
 */
export interface PreferenceChoice {
  kind: string;
  channel: Channel;
  enabled: boolean;
  label: string;
}

export const preferenceKey = ({ kind, channel }: Pick<PreferenceChoice, "kind" | "channel">) => `${kind}:${channel}`;

/** The preferences the page can place: those on a channel it shows (in-app ones are never settable). */
export function preferenceChoices(
  items: readonly PreferenceItem[],
  label: (item: PreferenceItem) => string,
): PreferenceChoice[] {
  return items.flatMap((item) =>
    item.channel in CHANNELS
      ? [{ kind: item.kind, channel: item.channel as Channel, enabled: item.enabled, label: label(item) }]
      : [],
  );
}

/** The purposes of each channel, in screen order. */
export const CHANNELS = {
  email: ["reminders", "marketing"],
  whatsapp: ["whatsapp"],
} as const satisfies Record<string, readonly ConsentItem["purpose"][]>;

export type Channel = keyof typeof CHANNELS;
export type NotificationPurpose = (typeof CHANNELS)[Channel][number];

const PURPOSES: readonly NotificationPurpose[] = [...CHANNELS.email, ...CHANNELS.whatsapp];

/** A channel that exists only later: its consent can be withdrawn, never newly given, until it is live. */
const NOT_YET: readonly NotificationPurpose[] = ["whatsapp"];

export type NotificationChoice = ConsentItem & { purpose: NotificationPurpose };

/** The notification consents from GET /api/me/consents, in screen order, wording and version as the API sent them. */
export function notificationChoices(items: readonly ConsentItem[]): NotificationChoice[] {
  return PURPOSES.flatMap((purpose) => {
    const found = items.find((item) => item.purpose === purpose);
    return found ? [{ ...found, purpose }] : [];
  });
}

/** Whether the person can change this choice: always, except turning on a channel that is not available yet. */
export function isOffered(choice: Pick<ConsentItem, "purpose" | "granted">): boolean {
  return choice.granted || !(NOT_YET as readonly string[]).includes(choice.purpose);
}

/**
 * The PUT /api/me/consents body: one decision per changed choice, on the version whose wording was shown (the API
 * answers 409 when the wording changed since). Unchanged choices are not sent, so no decision is recorded twice.
 */
export function changedDecisions(
  shown: readonly NotificationChoice[],
  ticked: Partial<Record<NotificationPurpose, boolean>>,
): Partial<Record<NotificationPurpose, ConsentDecision>> {
  const body: Partial<Record<NotificationPurpose, ConsentDecision>> = {};
  for (const choice of shown) {
    const wanted = ticked[choice.purpose];
    if (wanted === undefined || wanted === choice.granted) continue;
    if (wanted && !isOffered(choice)) continue;
    body[choice.purpose] = { granted: wanted, version: choice.version };
  }
  return body;
}

export type SaveRefusal = "changed" | "signedOut" | "rateLimited" | "network" | "failed";

/** Why a save was refused, as one of the page's fixed sentences (the API's own message is never shown). */
export function saveRefusal(status: number, body: unknown): SaveRefusal {
  if (status === 0) return "network";
  if (status === 401) return "signedOut";
  if (status === 429) return "rateLimited";
  if (status === 409 && apiErrorCode(body) === "consent_text_changed") return "changed";
  return "failed";
}
