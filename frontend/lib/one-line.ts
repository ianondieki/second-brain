// One-line plain text, as the API and the database refuse it (backend/src/bridge/models/text.py FORBIDDEN_TEXT_CHARS,
// revision 0013): control characters (C0, DEL, C1), the format characters that hide, join or reorder text, every space
// but the ASCII one, and the line and paragraph separators. The screens check it before sending, so a title or a note
// with such a character is said on its field rather than refused by the API; the API decides again.

// The same set as FORBIDDEN_TEXT_CHARS, character for character (one-line.test.ts pins it).
const FORBIDDEN =
  /[\u0000-\u001F\u007F-\u009F\u00A0\u00AD\u061C\u1680\u180E\u2000-\u200F\u2028-\u202F\u205F-\u206F\u3000\uFEFF\uFFF9-\uFFFB\u{E0001}-\u{E007F}]/u;

/** Whether `text` (already trimmed) is one line of plain text the API accepts: no forbidden character. */
export function isOneLine(text: string): boolean {
  return !FORBIDDEN.test(text);
}
