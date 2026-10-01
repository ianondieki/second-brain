import localFont from "next/font/local";
import type { ReactNode } from "react";

import { directionsCss } from "./directions";

import "./lab.css";

// Self-hosted, latin-subset variable fonts (fonts/LICENCES.md); next/font inlines the @font-face rules with
// font-display: swap and a size-adjusted fallback, and only this layout (dev only) loads them.
const manrope = localFont({ src: "./fonts/manrope-latin.woff2", variable: "--lab-manrope", display: "swap", weight: "400 800" });
const jetbrains = localFont({ src: "./fonts/jetbrains-mono-latin.woff2", variable: "--lab-jetbrains", display: "swap", weight: "400 600" });
const bricolage = localFont({ src: "./fonts/bricolage-grotesque-latin.woff2", variable: "--lab-bricolage", display: "swap", weight: "400 800" });
const dmSans = localFont({ src: "./fonts/dm-sans-latin.woff2", variable: "--lab-dm-sans", display: "swap", weight: "400 700" });
const newsreader = localFont({ src: "./fonts/newsreader-latin.woff2", variable: "--lab-newsreader", display: "swap", weight: "400 700" });
const plexSans = localFont({ src: "./fonts/ibm-plex-sans-latin.woff2", variable: "--lab-plex-sans", display: "swap", weight: "100 700" });
const plexMono = localFont({ src: "./fonts/ibm-plex-mono-latin.woff2", variable: "--lab-plex-mono", display: "swap", weight: "400" });

const FONT_VARS = {
  a: { display: "var(--lab-manrope)", text: "var(--lab-manrope)", mono: "var(--lab-jetbrains)" },
  b: { display: "var(--lab-bricolage)", text: "var(--lab-dm-sans)", mono: "var(--lab-jetbrains)" },
  c: { display: "var(--lab-newsreader)", text: "var(--lab-plex-sans)", mono: "var(--lab-plex-mono)" },
} as const;

const fontClasses = [manrope, jetbrains, bricolage, dmSans, newsreader, plexSans, plexMono].map((f) => f.variable).join(" ");

/** The lab's root: the fonts' variables and the three directions' token sheets; the pages pick a direction. */
export default function DesignLabLayout({ children }: { children: ReactNode }) {
  return (
    <div className={fontClasses}>
      <style>{directionsCss(FONT_VARS)}</style>
      {children}
    </div>
  );
}
