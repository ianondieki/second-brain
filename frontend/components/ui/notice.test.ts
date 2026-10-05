import { describe, expect, it } from "vitest";

import { noticeBox, noticeIconTone, noticeTone } from "./notice";

// docs/platform/design/p16-design-system.md, Notices: a 1 px tone border, a tone wash, the icon in the tone; never a
// coloured left rule.
describe("notice tones", () => {
  it("gives every tone a border, a background and an icon colour", () => {
    expect(Object.keys(noticeTone).sort()).toEqual(["error", "info", "neutral", "ok"]);
    expect(Object.keys(noticeIconTone).sort()).toEqual(Object.keys(noticeTone).sort());
    for (const [tone, classes] of Object.entries(noticeTone)) {
      const parts = classes.split(" ");
      expect(parts.filter((c) => c.startsWith("border-")), tone).toHaveLength(1);
      expect(parts.filter((c) => c.startsWith("bg-")), tone).toHaveLength(1);
      expect(parts.some((c) => /^border-[lrtb]-/.test(c)), tone).toBe(false);
      expect(noticeIconTone[tone as keyof typeof noticeIconTone]).toMatch(/^text-/);
    }
  });

  it("draws the box the same way for every tone: a 1 px border, rounded, the icon beside the words", () => {
    expect(noticeBox.split(" ")).toEqual(expect.arrayContaining(["flex", "items-start", "border", "rounded-panel"]));
    expect(noticeBox).not.toMatch(/\bborder-l\b/);
  });

  it("keeps errors, successes and information apart by colour as well as by words", () => {
    const washes = Object.values(noticeTone);
    expect(new Set(washes).size).toBe(washes.length);
    expect(new Set(Object.values(noticeIconTone)).size).toBe(washes.length);
  });
});
