// What a notification is about, from its `kind` (the API's own codes: engagement.n03 and the tracker's other notices,
// engagement.n18 a message, em3 the scout's digest, saved_search_match, em7 / em7_org the reminders, n26 / n27 an
// event, team.n28 / team.n29, pitch_sent), so the list can draw one icon per kind (D-67, P25). Pure, so it is tested
// without a page; an unknown kind is "other" (a plain bell), never an error.

export type NoticeKind = "message" | "engagement" | "discover" | "reminder" | "event" | "team" | "inbox" | "other";

export function noticeKind(kind: string): NoticeKind {
  const k = kind.toLowerCase();
  if (k === "engagement.n18") return "message";
  if (k.startsWith("engagement.") || /^n(0\d|1[0-7])$/.test(k)) return "engagement";
  if (k === "em3" || k.startsWith("saved_search") || k.startsWith("scout")) return "discover";
  if (k.startsWith("em7") || k.startsWith("reminder")) return "reminder";
  if (k === "n26" || k === "n27" || k.startsWith("event")) return "event";
  if (k.startsWith("team.")) return "team";
  if (k === "pitch_sent") return "inbox";
  return "other";
}
