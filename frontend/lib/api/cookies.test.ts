import { describe, expect, it } from "vitest";

import { readCsrfCookie } from "./client";
import { cookieSecure, CSRF_COOKIES, pickCookie, sessionCookieHeader } from "./cookies";

const TOKEN = "session-".padEnd(43, "x"); // fake, 43 characters like secrets.token_urlsafe(32)
const OTHER = "AttackerTokenAttackerTokenAttackerToken0000";

function jar(values: Record<string, string>) {
  return (name: string) => values[name];
}

describe("session cookie for the server-side /me call", () => {
  it("forwards only the prefixed cookie in secure mode, and ignores the bare name", () => {
    expect(sessionCookieHeader(jar({ "__Host-bridge_session": TOKEN }), true)).toBe(`__Host-bridge_session=${TOKEN}`);
    expect(sessionCookieHeader(jar({ bridge_session: TOKEN }), true)).toBeUndefined();
    expect(sessionCookieHeader(jar({ bridge_session: OTHER, "__Host-bridge_session": TOKEN }), true)).toBe(
      `__Host-bridge_session=${TOKEN}`,
    );
  });

  it("forwards only the bare cookie in plain mode, and ignores the prefixed name", () => {
    expect(sessionCookieHeader(jar({ bridge_session: TOKEN }), false)).toBe(`bridge_session=${TOKEN}`);
    expect(sessionCookieHeader(jar({ "__Host-bridge_session": TOKEN }), false)).toBeUndefined();
  });

  it("never forwards an injected value: a decoded '; name=value' is treated as signed out", () => {
    // What cookies() returns for a planted bridge_session=x%3B%20__Host-bridge_session%3D<attacker token>.
    const injected = `x; __Host-bridge_session=${OTHER}`;
    expect(sessionCookieHeader(jar({ bridge_session: injected }), false)).toBeUndefined();
    expect(sessionCookieHeader(jar({ "__Host-bridge_session": injected }), true)).toBeUndefined();
    for (const bad of ["short", `${TOKEN}\r\nX-Evil: 1`, `${TOKEN} `, "a".repeat(129), `${TOKEN}=`, "tok,en".repeat(5)]) {
      expect(sessionCookieHeader(jar({ "__Host-bridge_session": bad }), true), JSON.stringify(bad)).toBeUndefined();
    }
  });
});

describe("cookieSecure", () => {
  it("is true by default and for anything but a clear 'off', like the API's setting", () => {
    expect(cookieSecure(undefined)).toBe(true);
    expect(cookieSecure("true")).toBe(true);
    expect(cookieSecure("1")).toBe(true);
    expect(cookieSecure(" False ")).toBe(false);
    expect(cookieSecure("0")).toBe(false);
    expect(cookieSecure("off")).toBe(false);
  });
});

describe("CSRF cookie in the browser", () => {
  it("lists the __Host- prefixed name first, then the plain-http dev name", () => {
    expect(CSRF_COOKIES).toEqual(["__Host-bridge_csrf", "bridge_csrf"]);
    expect(pickCookie(CSRF_COOKIES, jar({ bridge_csrf: "plain", "__Host-bridge_csrf": "prefixed" }))).toEqual({
      name: "__Host-bridge_csrf",
      value: "prefixed",
    });
  });

  it("reads the CSRF token under either name, prefixed first", () => {
    expect(readCsrfCookie("a=1; bridge_csrf=plain")).toBe("plain");
    expect(readCsrfCookie("bridge_csrf=plain; __Host-bridge_csrf=prefixed")).toBe("prefixed");
    expect(readCsrfCookie("a=1")).toBeUndefined();
  });
});
