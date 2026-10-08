import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FONT_FILES } from "@/next.config";

import { DEFERRED_FACES, DEFERRED_FONTS_CSS, DEFERRED_FONTS_SCRIPT } from "./fonts";

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

  it("are added only after the first frame, with swap, at the weights the CSS sets", () => {
    const added: { family: string; source: string; descriptors: FontFaceDescriptors }[] = [];
    const frames: FrameRequestCallback[] = [];
    const tasks: (() => void)[] = [];
    vi.stubGlobal(
      "FontFace",
      class {
        constructor(family: string, source: string, descriptors: FontFaceDescriptors) {
          added.push({ family, source, descriptors });
        }
      },
    );
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback));
    vi.stubGlobal("setTimeout", (callback: () => void) => tasks.push(callback));
    Object.defineProperty(document, "fonts", { configurable: true, value: { add: vi.fn() } });

    new Function(DEFERRED_FONTS_SCRIPT)();
    expect(added).toEqual([]); // nothing before the first frame
    frames.shift()!(0);
    expect(added).toEqual([]); // nor during it
    tasks.shift()!();
    expect(added).toEqual([
      { family: "Bricolage Grotesque", source: 'url(/fonts/bricolage-grotesque-v2.woff2) format("woff2")', descriptors: { weight: "600 800", display: "swap" } },
      { family: "IBM Plex Mono", source: 'url(/fonts/ibm-plex-mono-latin-v1.woff2) format("woff2")', descriptors: { weight: "400", display: "swap" } },
    ]);
    expect(document.fonts.add).toHaveBeenCalledTimes(2);
  });

  it("are declared for a browser without JavaScript", () => {
    expect(DEFERRED_FONTS_CSS).toBe(
      '@font-face{font-family:"Bricolage Grotesque";src:url("/fonts/bricolage-grotesque-v2.woff2") format("woff2");font-display:swap;font-weight:600 800}' +
        '@font-face{font-family:"IBM Plex Mono";src:url("/fonts/ibm-plex-mono-latin-v1.woff2") format("woff2");font-display:swap;font-weight:400}',
    );
    expect(layout).toContain("<noscript dangerouslySetInnerHTML={{ __html: `<style>${DEFERRED_FONTS_CSS}</style>` }} />");
  });
});
