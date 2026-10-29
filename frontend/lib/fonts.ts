// The two decorative faces (public/fonts/LICENCES.md; D-55): Bricolage Grotesque (the wordmark and the figures) and
// IBM Plex Mono (the eyebrows). The first screen uses both, so declared in globals.css the browser fetched them at its
// first layout, at the highest priority, beside the CSS, the preloaded text faces and the LCP photograph: on Slow 4G
// 36 KB more before the first paint (P25, REQ-UX-05). They are declared here instead, once the first frame is on
// screen (at once when this browser already has them), and swap in over their fallbacks, each sized to its face
// (globals.css), so the swap moves nothing.

export interface DeferredFace {
  family: string;
  file: string;
  weight: string;
}

export const DEFERRED_FACES: readonly DeferredFace[] = [
  { family: "Bricolage Grotesque", file: "/fonts/bricolage-grotesque-v2.woff2", weight: "600 800" },
  { family: "IBM Plex Mono", file: "/fonts/ibm-plex-mono-latin-v1.woff2", weight: "400" },
];

/** Set once this browser has loaded both faces: they are then in its HTTP cache (immutable, a year; next.config.ts). */
export const FONTS_CACHED_KEY = "wazo-fonts:v1";

/**
 * Inline in <head>, no dependencies. On a browser that has loaded the faces before (FONTS_CACHED_KEY), they are added at
 * once, before the first paint, and come from the cache with no swap. Otherwise they are added after the first frame
 * (a frame callback, then a task, which runs once that frame has painted), fetched, and swap in over their sized
 * fallbacks; once both have loaded the key is set. (`document.fonts.check` cannot tell: it answers true for a family
 * no face declares yet, and a declared face is not fetched until something asks for it.) A browser without the CSS
 * Font Loading API keeps the fallbacks; without JavaScript the <noscript> rules below declare the faces.
 */
export const DEFERRED_FONTS_SCRIPT =
  `(function(){var f=${JSON.stringify(DEFERRED_FACES)},k=${JSON.stringify(FONTS_CACHED_KEY)},s=null;` +
  `try{s=localStorage}catch(e){}` +
  `function add(seen){if(!window.FontFace||!document.fonts)return;var l=[];f.forEach(function(x){try{` +
  `var face=new FontFace(x.family,"url("+x.file+") format('woff2')",{weight:x.weight,display:"swap"});` +
  `document.fonts.add(face);if(!seen)l.push(face.load());}catch(e){}});` +
  `if(!seen&&s&&l.length===f.length)Promise.all(l).then(function(){try{s.setItem(k,"1")}catch(e){}},function(){});}` +
  `var seen=false;try{seen=!!s&&s.getItem(k)==="1"}catch(e){}` +
  `if(seen)add(true);else if(window.requestAnimationFrame)requestAnimationFrame(function(){setTimeout(function(){add(false)},0);});` +
  `else setTimeout(function(){add(false)},0);})();`;

/** The same faces as @font-face rules, for a browser running no JavaScript (a <noscript> style in <head>). */
export const DEFERRED_FONTS_CSS = DEFERRED_FACES.map(
  (face) =>
    `@font-face{font-family:"${face.family}";src:url("${face.file}") format("woff2");font-display:swap;font-weight:${face.weight}}`,
).join("");
