import { describe, expect, it } from "vitest";

import { readCsrfCookie } from "./client";
import { CSRF_COOKIES, pickCookie, SESSION_COOKIES } from "./cookies";

describe("cookie names", () => {
  it("lists the __Host- prefixed name first, then the plain-http dev name", () => {
    expect(CSRF_COOKIES).toEqual(["__Host-bridge_csrf", "bridge_csrf"]);
    expect(SESSION_COOKIES).toEqual(["__Host-bridge_session", "bridge_session"]);
  });

  it("picks the prefixed session cookie first and reports the name it was found under", () => {
    const jar: Record<string, string> = { bridge_session: "plain", "__Host-bridge_session": "prefixed" };
    expect(pickCookie(SESSION_COOKIES, (name) => jar[name])).toEqual({
      name: "__Host-bridge_session",
      value: "prefixed",
    });
  });

  it("falls back to the plain name when COOKIE_SECURE is off", () => {
    const jar: Record<string, string> = { bridge_session: "plain" };
    expect(pickCookie(SESSION_COOKIES, (name) => jar[name])).toEqual({ name: "bridge_session", value: "plain" });
    expect(pickCookie(SESSION_COOKIES, () => undefined)).toBeUndefined();
  });

  it("reads the CSRF token under either name, prefixed first", () => {
    expect(readCsrfCookie("a=1; bridge_csrf=plain")).toBe("plain");
    expect(readCsrfCookie("bridge_csrf=plain; __Host-bridge_csrf=prefixed")).toBe("prefixed");
    expect(readCsrfCookie("a=1")).toBeUndefined();
  });
});
