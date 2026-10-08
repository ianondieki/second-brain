// The two decorative faces (public/fonts/LICENCES.md; D-55): Bricolage Grotesque (the wordmark and the figures) and
// IBM Plex Mono (the eyebrows). The first screen uses both, so declared in globals.css the browser fetched them at its
// first layout, at the highest priority, beside the CSS, the preloaded text faces and the LCP photograph: on Slow 4G
// 36 KB more before the first paint (P25, REQ-UX-05). They are declared here instead, once the first frame is on
// screen, and swap in over their fallbacks (the wordmark's is sized to Bricolage, globals.css). Nothing else changes.

export interface DeferredFace {
  family: string;
  file: string;
  weight: string;
}

export const DEFERRED_FACES: readonly DeferredFace[] = [
  { family: "Bricolage Grotesque", file: "/fonts/bricolage-grotesque-v2.woff2", weight: "600 800" },
  { family: "IBM Plex Mono", file: "/fonts/ibm-plex-mono-latin-v1.woff2", weight: "400" },
];

/**
 * Inline in <head>, no dependencies: after the first frame (a frame callback, then a task, which runs once that frame
 * has painted) the faces are added to the document, and the browser fetches each one the page uses. A browser without
 * the CSS Font Loading API keeps the fallbacks; without JavaScript the <noscript> rules below declare them.
 */
export const DEFERRED_FONTS_SCRIPT =
  `(function(){var f=${JSON.stringify(DEFERRED_FACES)};` +
  `function add(){if(!window.FontFace||!document.fonts)return;f.forEach(function(x){try{` +
  `document.fonts.add(new FontFace(x.family,"url("+x.file+") format(\\"woff2\\")",{weight:x.weight,display:"swap"}));` +
  `}catch(e){}});}` +
  `if(window.requestAnimationFrame)requestAnimationFrame(function(){setTimeout(add,0);});else setTimeout(add,0);})();`;

/** The same faces as @font-face rules, for a browser running no JavaScript (a <noscript> style in <head>). */
export const DEFERRED_FONTS_CSS = DEFERRED_FACES.map(
  (face) =>
    `@font-face{font-family:"${face.family}";src:url("${face.file}") format("woff2");font-display:swap;font-weight:${face.weight}}`,
).join("");
