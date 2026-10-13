import { describe, expect, it } from "vitest";

import { asksToSaveData, DATA_SAVER_COOKIE, DATA_SAVER_MAX_AGE, dataSaverCookie, dataSaverIn } from "./data-saver";

// P27 track F (REQ-UX-08): the data-saver switch is a cookie the server treats exactly like `Save-Data: on`.

const reader = (sent: Record<string, string>) => {
  const headers = new Headers(sent);
  return (name: string) => headers.get(name);
};

describe("the data-saver cookie", () => {
  it("is on only for data-saver=1, wherever it sits among the cookies", () => {
    expect(dataSaverIn("data-saver=1")).toBe(true);
    expect(dataSaverIn("NEXT_LOCALE=sw; data-saver=1; wazo-tour-developer=done")).toBe(true);
    expect(dataSaverIn("a=b;data-saver=1")).toBe(true);
    for (const off of [
      "",
      "data-saver=0",
      "data-saver=",
      "data-saver=10",
      "xdata-saver=1",
      "data-saver-x=1",
      "a=data-saver=1",
    ]) {
      expect(dataSaverIn(off), off).toBe(false);
    }
    expect(dataSaverIn(null)).toBe(false);
  });

  it("is written for the whole site for a year, SameSite=Lax, Secure on HTTPS, and never HttpOnly", () => {
    expect(DATA_SAVER_COOKIE).toBe("data-saver");
    expect(DATA_SAVER_MAX_AGE).toBe(365 * 24 * 60 * 60);
    expect(dataSaverCookie(true, true)).toBe("data-saver=1; Path=/; Max-Age=31536000; SameSite=Lax; Secure");
    expect(dataSaverCookie(true, false)).toBe("data-saver=1; Path=/; Max-Age=31536000; SameSite=Lax");
    expect(dataSaverCookie(false, true)).toBe("data-saver=; Path=/; Max-Age=0; SameSite=Lax; Secure");
    expect(dataSaverCookie(true, true)).not.toMatch(/httponly/i);
  });
});

describe("a request that asks to save data", () => {
  it("is one with Save-Data: on, or with the switch's cookie, and nothing else", () => {
    expect(asksToSaveData(reader({ "Save-Data": "on" }))).toBe(true);
    expect(asksToSaveData(reader({ "save-data": " ON " }))).toBe(true);
    expect(asksToSaveData(reader({ cookie: "data-saver=1" }))).toBe(true);
    expect(asksToSaveData(reader({ "save-data": "off", cookie: "data-saver=1" }))).toBe(true);
    expect(asksToSaveData(reader({}))).toBe(false);
    expect(asksToSaveData(reader({ "save-data": "off" }))).toBe(false);
    expect(asksToSaveData(reader({ cookie: "data-saver=0" }))).toBe(false);
  });
});
