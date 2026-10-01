// The three candidate directions of P18 step 1 (owner brief, D-52), each as a complete token set for light and dark
// mode. The lab writes them as CSS custom properties over the app's own tokens (app/globals.css): the same components
// render under each direction without a change, which is the whole point of the comparison. Values here are the only
// source; lab.css carries the per-direction rules that cannot be a token swap (patterns, the display face on headings).

export const DIRECTIONS = ["a", "b", "c"] as const;
export type DirectionKey = (typeof DIRECTIONS)[number];
export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

export interface Palette {
  paper: string;
  field: string;
  ink: string;
  inkSoft: string;
  line: string;
  accent: string;
  accentWash: string;
  onAccent: string;
  ok: string;
  onOk: string;
  error: string;
  /** A second brand colour used only in patterns, seals and illustrations; never for status. */
  flourish: string;
  /** The page-level card shadow (layered: a contact shadow plus a soft ambient one), tinted from the ink. */
  shadowCard: string;
  shadowOverlay: string;
}

export interface Direction {
  key: DirectionKey;
  name: string;
  tagline: string;
  /** Who it is for and what it says about the product, in one sentence each. */
  story: string;
  fonts: { display: string; text: string; mono: string; licence: string };
  radius: { control: number; panel: number };
  type: { displayWeight: number; displayTracking: string; scale: number };
  motion: { fast: string; base: string; ease: string; description: string };
  icons: string;
  illustration: string;
  elevation: string;
  light: Palette;
  dark: Palette;
}

export const DIRECTION: Record<DirectionKey, Direction> = {
  a: {
    key: "a",
    name: "Confident fintech",
    tagline: "Deep ink, one cobalt accent, crisp geometry.",
    story:
      "Reads like money infrastructure: the certificate and the tracker are instruments, not pages. For a recruiter it says engineering rigour; for an organisation it says this is safe to sign.",
    fonts: { display: "Manrope", text: "Manrope", mono: "JetBrains Mono", licence: "OFL 1.1" },
    radius: { control: 8, panel: 14 },
    type: { displayWeight: 700, displayTracking: "-0.022em", scale: 1.25 },
    motion: {
      fast: "140ms",
      base: "200ms",
      ease: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      description: "Quick and decisive: 140–200 ms, ease-out, no overshoot; one drawn line on the landing page.",
    },
    icons: "1.75 px strokes, square-ish geometry, rounded caps; filled only for the current step.",
    illustration: "Thin isometric line drawings on a faint grid, in ink and cobalt.",
    elevation: "Two layers: a 1 px contact shadow and a cool ambient one; cards sit a hair above the paper.",
    light: {
      paper: "#F4F6FA",
      field: "#FFFFFF",
      ink: "#0C1424",
      inkSoft: "#4C5668",
      line: "#D6DCE6",
      accent: "#2140E8",
      accentWash: "#E5E9FD",
      onAccent: "#FFFFFF",
      ok: "#157A48",
      onOk: "#FFFFFF",
      error: "#B3261E",
      flourish: "#7D93FF",
      shadowCard: "0 1px 2px rgb(12 20 36 / 0.05), 0 10px 30px -14px rgb(12 20 36 / 0.22)",
      shadowOverlay: "0 16px 40px -16px rgb(12 20 36 / 0.3), 0 2px 6px -2px rgb(12 20 36 / 0.12)",
    },
    dark: {
      paper: "#0B111E",
      field: "#131B2C",
      ink: "#E9EEF8",
      inkSoft: "#A9B3C6",
      line: "#283349",
      accent: "#8DA0FF",
      accentWash: "#1B2547",
      onAccent: "#0B111E",
      ok: "#5CD197",
      onOk: "#0B111E",
      error: "#FF857D",
      flourish: "#2140E8",
      shadowCard: "0 1px 2px rgb(0 0 0 / 0.4), 0 12px 32px -14px rgb(0 0 0 / 0.6)",
      shadowOverlay: "0 16px 40px -16px rgb(0 0 0 / 0.7), 0 2px 6px -2px rgb(0 0 0 / 0.4)",
    },
  },
  b: {
    key: "b",
    name: "Warm Nairobi",
    tagline: "Sand and murram, a kanga-cut lattice, a face with character.",
    story:
      "Unmistakably from here: red-soil accents, warm paper, and a geometric lattice drawn from kanga and kitenge borders, used as a thin band and never as wallpaper. It says local, generous and confident.",
    fonts: { display: "Bricolage Grotesque", text: "DM Sans", mono: "JetBrains Mono", licence: "OFL 1.1" },
    radius: { control: 12, panel: 20 },
    type: { displayWeight: 600, displayTracking: "-0.015em", scale: 1.25 },
    motion: {
      fast: "180ms",
      base: "240ms",
      ease: "cubic-bezier(0.34, 1.2, 0.64, 1)",
      description: "Warm and springy: 180–240 ms with a slight overshoot on presses; the lattice band fades in once.",
    },
    icons: "Rounder 2 px strokes with soft corners; the current step is a filled warm dot.",
    illustration: "Flat warm shapes (sand, murram, ochre) with lattice fills; no outlines.",
    elevation: "Warm-tinted shadows, slightly longer; the whose-turn card and the primary button float a little.",
    light: {
      paper: "#F7F1E8",
      field: "#FFFCF8",
      ink: "#2B1D15",
      inkSoft: "#6B5546",
      line: "#E1D4C4",
      accent: "#B6401C",
      accentWash: "#F7E2D5",
      onAccent: "#FFFFFF",
      ok: "#2A7447",
      onOk: "#FFFFFF",
      error: "#A3291C",
      flourish: "#C98C1E",
      shadowCard: "0 1px 2px rgb(43 29 21 / 0.06), 0 12px 32px -16px rgb(43 29 21 / 0.28)",
      shadowOverlay: "0 18px 44px -18px rgb(43 29 21 / 0.35), 0 2px 6px -2px rgb(43 29 21 / 0.12)",
    },
    dark: {
      paper: "#1B1512",
      field: "#251D18",
      ink: "#F4ECE2",
      inkSoft: "#C6B4A4",
      line: "#3C3029",
      accent: "#F2905F",
      accentWash: "#3D2519",
      onAccent: "#1B1512",
      ok: "#79C796",
      onOk: "#1B1512",
      error: "#FF8F7E",
      flourish: "#E0A63C",
      shadowCard: "0 1px 2px rgb(0 0 0 / 0.4), 0 14px 36px -16px rgb(0 0 0 / 0.6)",
      shadowOverlay: "0 18px 44px -18px rgb(0 0 0 / 0.7), 0 2px 6px -2px rgb(0 0 0 / 0.4)",
    },
  },
  c: {
    key: "c",
    name: "Editorial trust",
    tagline: "Generous whitespace, a refined serif, one quiet green.",
    story:
      "Reads like a registry or a well-set contract: the certificate looks like something a lawyer would file. Calm for organisations, credible for a pitch deck; the product speaks in a measured voice.",
    fonts: { display: "Newsreader", text: "IBM Plex Sans", mono: "IBM Plex Mono", licence: "OFL 1.1" },
    radius: { control: 6, panel: 12 },
    type: { displayWeight: 500, displayTracking: "-0.01em", scale: 1.333 },
    motion: {
      fast: "180ms",
      base: "260ms",
      ease: "cubic-bezier(0.16, 1, 0.3, 1)",
      description: "Slow and gentle: 180–260 ms fades with a 4 px rise; nothing bounces; the seal draws once.",
    },
    icons: "1.5 px strokes, hairline feel, circular geometry; the current step is a small filled ring.",
    illustration: "Engraving-style thin line drawings in ink with a single green stroke.",
    elevation: "Mostly hairlines; one very soft, wide shadow under the certificate sheet and overlays only.",
    light: {
      paper: "#FBFAF6",
      field: "#FFFFFF",
      ink: "#1A1916",
      inkSoft: "#5C5A53",
      line: "#DEDACF",
      accent: "#1F5E49",
      accentWash: "#E5EFE9",
      onAccent: "#FFFFFF",
      ok: "#1F6B47",
      onOk: "#FFFFFF",
      error: "#9E2A1F",
      flourish: "#B8A46A",
      shadowCard: "0 1px 0 rgb(26 25 22 / 0.04), 0 16px 40px -24px rgb(26 25 22 / 0.22)",
      shadowOverlay: "0 16px 40px -16px rgb(26 25 22 / 0.24), 0 2px 6px -2px rgb(26 25 22 / 0.1)",
    },
    dark: {
      paper: "#131412",
      field: "#1B1C19",
      ink: "#ECE9E1",
      inkSoft: "#B4B0A5",
      line: "#30312C",
      accent: "#7FCBAB",
      accentWash: "#1F2F28",
      onAccent: "#131412",
      ok: "#7AC79A",
      onOk: "#131412",
      error: "#FF8F7E",
      flourish: "#8E7F4A",
      shadowCard: "0 1px 0 rgb(0 0 0 / 0.4), 0 16px 40px -24px rgb(0 0 0 / 0.6)",
      shadowOverlay: "0 16px 40px -16px rgb(0 0 0 / 0.7), 0 2px 6px -2px rgb(0 0 0 / 0.4)",
    },
  },
};

export function isDirection(value: string): value is DirectionKey {
  return (DIRECTIONS as readonly string[]).includes(value);
}

export function asTheme(value: string | string[] | undefined): Theme {
  const first = Array.isArray(value) ? value[0] : value;
  return first === "dark" ? "dark" : "light";
}

/** The custom properties one palette writes over app/globals.css. */
function paletteVars(p: Palette): string {
  return [
    `--paper:${p.paper}`,
    `--field:${p.field}`,
    `--ink:${p.ink}`,
    `--ink-soft:${p.inkSoft}`,
    `--line:${p.line}`,
    `--jacaranda:${p.accent}`,
    `--jacaranda-wash:${p.accentWash}`,
    `--on-accent:${p.onAccent}`,
    `--ok:${p.ok}`,
    `--on-ok:${p.onOk}`,
    `--error:${p.error}`,
    `--flourish:${p.flourish}`,
    `--shadow-card:${p.shadowCard}`,
    `--shadow-overlay:${p.shadowOverlay}`,
  ].join(";");
}

/**
 * The per-direction rules as one stylesheet. Font families come from next/font/local's variables (layout.lab.tsx)
 * so the real WOFF2 files load with font-display: swap and a size-adjusted fallback.
 */
export function directionsCss(fontVars: Record<DirectionKey, { display: string; text: string; mono: string }>): string {
  return DIRECTIONS.map((key) => {
    const d = DIRECTION[key];
    const f = fontVars[key];
    const base = [
      `--font-sans:${f.text},system-ui,sans-serif`,
      `--font-display:${f.display},${f.text},system-ui,sans-serif`,
      `--font-mono:${f.mono},ui-monospace,monospace`,
      `--display-weight:${d.type.displayWeight}`,
      `--display-tracking:${d.type.displayTracking}`,
      `--radius-control:${d.radius.control}px`,
      `--radius-panel:${d.radius.panel}px`,
      `--motion-fast:${d.motion.fast}`,
      `--motion-base:${d.motion.base}`,
      `--motion-ease:${d.motion.ease}`,
      paletteVars(d.light),
      // The app's derived mixes (app/globals.css) are computed where they are declared, on :root, from the root's
      // colours: declared again here, with the same formulas, they follow this direction's colours in both themes.
      "--accent-strong:color-mix(in oklab, var(--jacaranda) 84%, var(--ink))",
      "--wash-soft:color-mix(in oklab, var(--jacaranda-wash) 55%, var(--paper))",
      "--error-wash:color-mix(in oklab, var(--error) 7%, var(--field))",
      "--ok-wash:color-mix(in oklab, var(--ok) 7%, var(--field))",
      "--error-line:color-mix(in oklab, var(--error) 45%, var(--paper))",
      "--ok-line:color-mix(in oklab, var(--ok) 45%, var(--paper))",
      "--accent-line:color-mix(in oklab, var(--jacaranda) 35%, var(--paper))",
      "--scrim:color-mix(in oklab, var(--ink) 45%, transparent)",
      "color-scheme:light",
    ].join(";");
    const dark = [paletteVars(d.dark), "color-scheme:dark"].join(";");
    return `[data-direction="${key}"]{${base}}[data-direction="${key}"][data-theme="dark"]{${dark}}`;
  }).join("\n");
}
