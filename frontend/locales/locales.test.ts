import { describe, expect, it } from "vitest";

import en from "./en.json";
import sw from "./sw.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out[path] = value;
    else Object.assign(out, flatten(value, path));
  }
  return out;
}

const EN = flatten(en);
const SW = flatten(sw);
const visible = (messages: Record<string, string>) =>
  Object.entries(messages).filter(([key]) => !key.startsWith("_meta."));

/** ICU argument names ({name}, {count, plural, ...}) and rich-text tag names (<b>, <terms>) of a message. */
function slots(message: string): string[] {
  const args = [...message.matchAll(/\{\s*([A-Za-z_][\w]*)/g)].map((m) => `{${m[1]}}`);
  const tags = [...message.matchAll(/<([A-Za-z][\w]*)>/g)].map((m) => `<${m[1]}>`);
  return [...new Set([...args, ...tags])].sort();
}

// docs/spec/04 principle 2: never promise what the platform cannot deliver.
const BANNED = [/theft[\s-]?proof/i, /cannot be stolen/i, /protected idea/i, /protect (your|the) idea/i, /secure your (idea|ip)/i, /\bpatented\b/i];

describe("locale files", () => {
  it("have identical keys in English and Swahili", () => {
    expect(Object.keys(SW).sort()).toEqual(Object.keys(EN).sort());
  });

  it("have no empty messages", () => {
    for (const [key, value] of [...visible(EN), ...visible(SW)]) expect(value.trim(), key).not.toBe("");
  });

  it("use the same ICU arguments and tags in both languages", () => {
    for (const [key, value] of visible(EN)) expect(slots(SW[key]), key).toEqual(slots(value));
  });

  it("keep review markers out of visible strings and in _meta", () => {
    for (const [key, value] of [...visible(EN), ...visible(SW)]) {
      expect(value, key).not.toMatch(/\[\[(COPY|SW)-REVIEW\]\]/);
    }
    expect(EN["_meta.review"]).toContain("[[COPY-REVIEW]]");
    expect(SW["_meta.review"]).toContain("[[COPY-REVIEW]]");
    expect(SW["_meta.review"]).toContain("[[SW-REVIEW]]");
  });

  it("carry the terms placeholder until the G2 legal text exists", () => {
    expect(EN["legal.termsBody"]).toBe("[[LEGAL-PLACEHOLDER:tos]]");
    expect(SW["legal.termsBody"]).toBe("[[LEGAL-PLACEHOLDER:tos]]");
  });

  it("make no banned IP claims", () => {
    for (const [key, value] of [...visible(EN), ...visible(SW)]) {
      for (const pattern of BANNED) expect(value, key).not.toMatch(pattern);
    }
  });

  // A verified address gets only an "account exists" notice and throttled requests get nothing, so no screen may
  // say an email was, or will be, sent.
  const EMAIL_KEYS = [
    "signup.lead",
    "checkEmail.signup",
    "checkEmail.login",
    "checkEmail.noEmail",
    "checkEmail.resent",
    "link.failedLead",
    "errors.email_unverified",
  ];
  const PROMISE_EN = /\bwe (have )?sent\b|\bwe (will|'ll) (email|send)\b|\bwe emailed\b|\bwe are sending\b/i;
  const PROMISE_SW = /\btumekutumia\b|\btulichotuma\b|\btulichokutumia\b|\btutakutumia\b|\btuliyotuma\b/i;

  it("never promise that an email was or will be sent (throttled and existing-account requests get none)", () => {
    for (const key of EMAIL_KEYS) {
      expect(EN[key], key).not.toMatch(PROMISE_EN);
      expect(SW[key], key).not.toMatch(PROMISE_SW);
    }
    for (const [key, value] of visible(EN)) expect(value, key).not.toMatch(PROMISE_EN);
    for (const [key, value] of visible(SW)) expect(value, key).not.toMatch(PROMISE_SW);
  });

  it("word email outcomes conditionally", () => {
    for (const key of ["checkEmail.signup", "checkEmail.login", "checkEmail.noEmail", "checkEmail.resent"]) {
      expect(EN[key], key).toMatch(/^If\b|\bIf another\b/);
    }
  });

  it("never use a straight apostrophe right before an ICU brace (it would escape it)", () => {
    for (const [key, value] of [...visible(EN), ...visible(SW)]) expect(value, key).not.toMatch(/'[{}]/);
  });
});
