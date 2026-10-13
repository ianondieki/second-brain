// @vitest-environment node
import { describe, expect, it } from "vitest";

import { isTurbopackRuntime } from "./turbopack-runtime.mjs";

// AC-UX-3 / REQ-UX-05: js-budget.mjs refuses to report a page that loaded no Turbopack runtime chunk (a webpack build
// reads about 2 KB heavier per route).
const RUNTIME = '(globalThis.TURBOPACK||(globalThis.TURBOPACK=[])).push(["object"==typeof document?document.currentScript:void 0,{otherChunks:[]}]);';

describe("isTurbopackRuntime", () => {
  it("knows Turbopack's runtime chunk by its name and its body", () => {
    expect(isTurbopackRuntime("http://localhost:3000/_next/static/chunks/turbopack-2qgv_qre53r3g.js", RUNTIME)).toBe(true);
    expect(isTurbopackRuntime("https://demo.example/_next/static/chunks/turbopack-0a1b-c2.js?v=1", RUNTIME)).toBe(true);
  });

  it("refuses webpack's runtime and Turbopack's other chunks", () => {
    const webpack = '(()=>{"use strict";var e={},r={};self.webpackChunk_N_E=self.webpackChunk_N_E||[]})();';
    expect(isTurbopackRuntime("http://localhost:3000/_next/static/chunks/webpack-8f2c1d0e9a7b6c5d.js", webpack)).toBe(false);
    // A page chunk of a Turbopack build carries the global too, but not the runtime's name.
    expect(isTurbopackRuntime("http://localhost:3000/_next/static/chunks/08bv1n-u9ik4_.js", RUNTIME)).toBe(false);
  });

  it("wants both: the name alone, or the body alone, is not enough", () => {
    expect(isTurbopackRuntime("http://localhost:3000/_next/static/chunks/turbopack-abc.js", "console.log(1)")).toBe(false);
    expect(isTurbopackRuntime("http://localhost:3000/_next/static/chunks/turbopack-abc.mjs", RUNTIME)).toBe(false);
    expect(isTurbopackRuntime("not a url", RUNTIME)).toBe(false);
  });
});
