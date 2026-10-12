import { describe, expect, it } from "vitest";

import { isOneLine } from "./one-line";

// The client-side copy of the API's one-line rule (backend/src/bridge/models/text.py; P27 security review MINOR).
describe("one line of plain text", () => {
  it("accepts ordinary words, accents, other scripts and emoji", () => {
    for (const text of ["Board minutes, 10 June 2025", "Kikao cha bodi — Juni", "Café ñandú", "会议记录", "Pilot 🚀"]) {
      expect(isOneLine(text), text).toBe(true);
    }
  });

  it.each([
    ["a tab", "a\tb"],
    ["a line break", "a\nb"],
    ["DEL", "a\u007Fb"],
    ["a C1 control", "a\u0085b"],
    ["a no-break space", "a\u00A0b"],
    ["a soft hyphen", "a\u00ADb"],
    ["the Arabic letter mark", "a\u061Cb"],
    ["the ogham space", "a\u1680b"],
    ["the Mongolian vowel separator", "a\u180Eb"],
    ["an en space", "a\u2002b"],
    ["a zero-width space", "a\u200Bb"],
    ["a right-to-left mark", "a\u200Fb"],
    ["the line separator", "a\u2028b"],
    ["a right-to-left override", "a\u202Eb"],
    ["a narrow no-break space", "a\u202Fb"],
    ["a word joiner", "a\u2060b"],
    ["a bidirectional isolate", "a\u2067b"],
    ["the ideographic space", "a\u3000b"],
    ["the byte order mark", "a\uFEFFb"],
    ["an interlinear annotation", "a\uFFF9b"],
    ["a tag character", "a\u{E0041}b"],
  ])("refuses %s", (_name, text) => {
    expect(isOneLine(text)).toBe(false);
  });
});
