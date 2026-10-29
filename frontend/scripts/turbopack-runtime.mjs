// Whether a script a page loaded is Turbopack's browser runtime chunk (scripts/js-budget.mjs, AC-UX-3). The budget is
// measured on Turbopack builds, as the image ships (`next build`'s default): a webpack build of the same code reads
// about 2 KB heavier per route and once misled a review. A Turbopack production build loads exactly one runtime chunk,
// `/_next/static/chunks/turbopack-<hash>.js`, whose body registers itself on `globalThis.TURBOPACK`; a webpack build
// loads `webpack-<hash>.js` (`self.webpackChunk_N_E`) instead. Both the name and the body must match.

/**
 * @param {string} url the script's URL
 * @param {string} body the script's text
 * @returns {boolean}
 */
export function isTurbopackRuntime(url, body) {
  let name;
  try {
    name = new URL(url).pathname.split("/").pop() ?? "";
  } catch {
    return false;
  }
  return /^turbopack-[\w-]+\.js$/.test(name) && body.includes("TURBOPACK");
}
