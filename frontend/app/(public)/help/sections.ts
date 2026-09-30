// The help page's content, in reading order (docs/spec/07 item 1): each section is a heading and its paragraphs, as
// keys of the `help` messages. Kept apart from the page so a test can check every key exists in both languages.

export const NOTIFICATIONS_HREF = "/settings/notifications";

export const HELP_SECTIONS = [
  { id: "pitching", paragraphs: ["pitching.parts", "pitching.pitch", "pitching.interest"] },
  { id: "confidential", paragraphs: ["confidential.tier1", "confidential.tier2", "confidential.record"] },
  { id: "reminders", paragraphs: ["reminders.daily", "reminders.always", "reminders.manage"] },
  { id: "support", paragraphs: ["support.body"] },
] as const;
