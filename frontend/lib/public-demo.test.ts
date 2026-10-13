// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { DISALLOW_ALL_ROBOTS, PUBLIC_DEMO_VARIABLE, publicDemoOn, ROBOTS_HEADER } from "./public-demo";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD): the web reads PUBLIC_DEMO on the server at run time.

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("publicDemoOn", () => {
  it("is off when the variable is unset, empty or anything but a true value", () => {
    expect(publicDemoOn({})).toBe(false);
    for (const value of ["", "0", "false", "off", "no", "maybe", "truee"]) {
      expect(publicDemoOn({ PUBLIC_DEMO: value }), value).toBe(false);
    }
  });

  it("is on for the values the API's settings read as true, in any case and with spaces", () => {
    for (const value of ["true", "TRUE", " True ", "1", "yes", "on", "t", "y"]) {
      expect(publicDemoOn({ PUBLIC_DEMO: value }), value).toBe(true);
    }
  });

  it("reads process.env at each call, never a value fixed earlier", () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    expect(publicDemoOn()).toBe(true);
    vi.stubEnv("PUBLIC_DEMO", "false");
    expect(publicDemoOn()).toBe(false);
    vi.stubEnv("PUBLIC_DEMO", "1");
    expect(publicDemoOn()).toBe(true);
  });

  it("ignores a NEXT_PUBLIC_ twin (the one variable that would be inlined at build)", () => {
    expect(publicDemoOn({ NEXT_PUBLIC_PUBLIC_DEMO: "true" })).toBe(false);
    expect(PUBLIC_DEMO_VARIABLE).toBe("PUBLIC_DEMO");
  });

  it("names the header and the robots file the card asks for", () => {
    expect(ROBOTS_HEADER).toEqual({ key: "X-Robots-Tag", value: "noindex, nofollow" });
    expect(DISALLOW_ALL_ROBOTS).toBe("User-agent: *\nDisallow: /\n");
  });
});

// "Never inlined": the switch must not reach a browser bundle, where a build would fix its value. No client module
// imports the helper, the helper reads the variable with a computed key (nothing a bundler replaces), and nothing in
// the app names a NEXT_PUBLIC_ variant.
describe("the switch stays on the server", () => {
  const root = join(__dirname, "..");
  const SKIP = new Set(["node_modules", ".next", "e2e", "test-results", "playwright-report", "public"]);

  function sources(dir: string, out: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
      if (SKIP.has(name)) continue;
      const path = join(dir, name);
      if (statSync(path).isDirectory()) sources(path, out);
      else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path);
    }
    return out;
  }

  const files = sources(root);

  it("is imported by no client component", () => {
    const offenders = files.filter((file) => {
      const text = readFileSync(file, "utf8");
      return /^\s*["']use client["']/.test(text) && /from\s+["'](@\/lib\/public-demo|\.{1,2}\/(\.\.\/)*public-demo)["']/.test(text);
    });
    expect(offenders.map((file) => relative(root, file))).toEqual([]);
  });

  it("is read with a computed key, and no file names a NEXT_PUBLIC_ variant", () => {
    const helper = readFileSync(join(root, "lib", "public-demo.ts"), "utf8");
    expect(helper).not.toMatch(/process\.env\.PUBLIC_DEMO/);
    expect(helper).toMatch(/env\[PUBLIC_DEMO_VARIABLE\]/);
    const named = files.filter((file) => /NEXT_PUBLIC_PUBLIC_DEMO|process\.env\.PUBLIC_DEMO\b/.test(readFileSync(file, "utf8")));
    expect(named.map((file) => relative(root, file))).toEqual([]);
  });
});
