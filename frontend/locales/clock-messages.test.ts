import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import { PARTS } from "@/components/ui/ClockFigures";

import en from "./en.json";
import sw from "./sw.json";

// P26 (REQ-TRACK-03): the live clock fills each language's countdown.clock* message on the client (ClockFigures'
// PARTS). A message that compiles but is the wrong shape (a figure's tag with a space in it, a slot outside its tag, a
// stray "<") would draw as literal text with no figure; the other locale tests would not notice.
const SLOTS = {
  days: "{days}",
  hours: "{hours}",
  minutes: "{minutes}",
  f: (chunks: string) => `<f>${chunks}</f>`,
  u: (chunks: string) => `<u>${chunks}</u>`,
};
const FIGURES = { clockDays: ["days", "hours", "minutes"], clockHours: ["hours", "minutes"], clockMinutes: ["minutes"] } as const;

describe.each([
  ["en", en] as const,
  ["sw", sw] as const,
])("the %s clock messages", (locale, messages) => {
  const t = createTranslator({ locale, messages, namespace: "countdown" });
  it.each(Object.entries(FIGURES))("%s is made only of figures, unit words and the text between them", (key, figures) => {
    const text = t.markup(key as keyof typeof FIGURES, SLOTS);
    const parts = [...text.matchAll(PARTS)];
    // The parts cover the whole message: nothing is dropped.
    expect(parts.map(([whole]) => whole).join("")).toBe(text);
    // Each figure exactly once, from the largest unit down to the minutes.
    expect(parts.map(([, figure]) => figure).filter(Boolean)).toEqual([...figures]);
    // No slot or tag left as text outside its place.
    for (const [, figure, , between] of parts) if (!figure) expect(between ?? "").not.toMatch(/[{}<>]/);
  });
});
