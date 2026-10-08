import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FONT_FILES } from "@/next.config";

import { DEFERRED_FACES, DEFERRED_FONTS_CSS, DEFERRED_FONTS_SCRIPT, FONTS_CACHED_KEY } from "./fonts";

// P25 (REQ-UX-05, acceptance 2): the two decorative faces are not fetched before the first paint. globals.css does not
// declare them (the browser would fetch them at the first layout, ahead of the LCP); the inline script adds them once
// the first frame has painted, and a <noscript> style declares them without JavaScript.

const globals = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
const layout = readFileSync(join(process.cwd(), "app/layout.tsx"), "utf8");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the decorative faces", () => {
  it("are vendored files, declared nowhere in globals.css, and neither preloaded", () => {
    for (const face of DEFERRED_FACES) {
      expect(FONT_FILES).toContain(face.file.replace("/fonts/", ""));
      expect(globals).not.toContain(face.file);
      expect(globals).not.toMatch(new RegExp(`font-family:\\s*"${face.family}";`));
      expect(layout).not.toContain(face.file);
    }
    // The faces the first screen's text needs stay preloaded and declared in globals.css.
    expect(layout).toContain('"/fonts/fraunces-v1.woff2", "/fonts/hanken-grotesk-v1.woff2"');
    expect(globals).toContain('src: url("/fonts/hanken-grotesk-v1.woff2")');
  });

  /** Stubs the browser's font and frame APIs; `load` settles each face's fetch when the test says so. */
  function stubBrowser() {
    const added: { family: string; source: string; descriptors: FontFaceDescriptors }[] = [];
    const frames: FrameRequestCallback[] = [];
    const tasks: (() => void)[] = [];
    let settle: () => void = () => undefined;
    const loaded = new Promise<void>((resolve) => (settle = resolve));
    vi.stubGlobal(
      "FontFace",
      class {
        constructor(family: string, source: string, descriptors: FontFaceDescriptors) {
          added.push({ family, source, descriptors });
        }
        load() {
          return loaded.then(() => this);
        }
      },
    );
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback));
    vi.stubGlobal("setTimeout", (callback: () => void) => tasks.push(callback));
    Object.defineProperty(document, "fonts", { configurable: true, value: { add: vi.fn() } });
    return { added, frames, tasks, settle };
  }

  const FACES = [
    { family: "Bricolage Grotesque", source: "url(/fonts/bricolage-grotesque-v2.woff2) format('woff2')", descriptors: { weight: "600 800", display: "swap" } },
    { family: "IBM Plex Mono", source: "url(/fonts/ibm-plex-mono-latin-v1.woff2) format('woff2')", descriptors: { weight: "400", display: "swap" } },
  ];

  it("are added only after the first frame on a first visit, with swap, at the weights the CSS sets", async () => {
    localStorage.removeItem(FONTS_CACHED_KEY);
    const { added, frames, tasks, settle } = stubBrowser();
    new Function(DEFERRED_FONTS_SCRIPT)();
    expect(added).toEqual([]); // nothing before the first frame
    frames.shift()!(0);
    expect(added).toEqual([]); // nor during it
    tasks.shift()!();
    expect(added).toEqual(FACES);
    expect(document.fonts.add).toHaveBeenCalledTimes(2);
    // Once both have loaded, the browser has them in its cache: the next page adds them before its first paint.
    expect(localStorage.getItem(FONTS_CACHED_KEY)).toBeNull();
    settle();
    await vi.waitFor(() => expect(localStorage.getItem(FONTS_CACHED_KEY)).toBe("1"));
  });

  it("are added at once, before the first paint, when this browser has loaded them before (no swap)", () => {
    localStorage.setItem(FONTS_CACHED_KEY, "1");
    const { added, frames, tasks } = stubBrowser();
    new Function(DEFERRED_FONTS_SCRIPT)();
    expect(added).toEqual(FACES);
    expect(frames).toEqual([]);
    expect(tasks).toEqual([]);
    localStorage.removeItem(FONTS_CACHED_KEY);
  });

  it("give IBM Plex Mono a fallback sized to it, as the other faces have", () => {
    expect(globals).toMatch(/font-family: "IBM Plex Mono Fallback";\s*src: local\("Courier New"\), local\("Liberation Mono"\), local\(Cousine\);/);
    expect(globals).toContain('--font-mono: "IBM Plex Mono", "IBM Plex Mono Fallback", ui-monospace,');
    expect(globals).toContain('--font-figure: "Bricolage Grotesque", "Bricolage Grotesque Fallback",');
  });

  it("are declared for a browser without JavaScript", () => {
    expect(DEFERRED_FONTS_CSS).toBe(
      '@font-face{font-family:"Bricolage Grotesque";src:url("/fonts/bricolage-grotesque-v2.woff2") format("woff2");font-display:swap;font-weight:600 800}' +
        '@font-face{font-family:"IBM Plex Mono";src:url("/fonts/ibm-plex-mono-latin-v1.woff2") format("woff2");font-display:swap;font-weight:400}',
    );
    expect(layout).toContain("<noscript dangerouslySetInnerHTML={{ __html: `<style>${DEFERRED_FONTS_CSS}</style>` }} />");
  });
});
