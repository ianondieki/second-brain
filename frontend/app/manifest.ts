import type { MetadataRoute } from "next";
import { getTranslations } from "next-intl/server";

// The colours of the browser chrome and the splash screen: the paper canvas and bloom (app/globals.css --paper,
// --accent). A manifest cannot read a CSS variable, so they are written here (as app/layout.tsx's themeColor).
export const PAPER = "#f7f4ed";
export const BLOOM = "#5a3fc0";

/**
 * The web app manifest (P24; REQ-UX-04): Wazo installs on an Android home screen and opens standalone, from the
 * landing (a signed-in person is sent on to their home). Icons drawn from the mark (public/icons; the maskable one
 * keeps the mark inside the safe zone). No service worker yet (offline reading is Release 2, docs/spec/07 item 5).
 */
export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const t = await getTranslations("app");
  return {
    name: t("name"),
    short_name: t("name"),
    description: t("tagline"),
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: PAPER,
    theme_color: BLOOM,
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
