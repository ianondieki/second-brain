// The tones notices share (Alert, the announced one; Callout, the static one): a 1 px tone border, a tone wash, and
// the icon in the tone (docs/platform/design/p16-design-system.md, Notices). No coloured left rules.

export type NoticeTone = "error" | "info" | "ok" | "neutral";

export const noticeBox = "flex items-start gap-3 rounded-panel border px-4 py-3.5 text-ink";

export const noticeTone: Record<NoticeTone, string> = {
  error: "border-error-line bg-error-wash",
  info: "border-accent-line bg-accent-wash",
  ok: "border-ok-line bg-ok-wash",
  neutral: "border-line bg-transparent",
};

export const noticeIconTone: Record<NoticeTone, string> = {
  error: "text-error",
  info: "text-accent",
  ok: "text-ok",
  neutral: "text-ink-soft",
};
