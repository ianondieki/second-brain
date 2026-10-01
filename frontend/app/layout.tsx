import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { RouteFocus } from "@/components/RouteFocus";
import { clientStrings } from "@/lib/i18n/client-strings";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

// Self-hosted faces (app/fonts/LICENCES.md; D-52): latin subsets, swap, a size-adjusted fallback while they load.
const display = localFont({ src: "./fonts/newsreader-latin.woff2", variable: "--font-display", display: "swap", weight: "400 700", adjustFontFallback: "Times New Roman" });
const text = localFont({ src: "./fonts/ibm-plex-sans-latin.woff2", variable: "--font-text", display: "swap", weight: "100 700", adjustFontFallback: "Arial" });
const figures = localFont({ src: "./fonts/ibm-plex-mono-latin.woff2", variable: "--font-figures", display: "swap", weight: "400", adjustFontFallback: false });

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("app");
  return {
    title: { default: t("workingTitle"), template: t("titleTemplate") },
    description: t("tagline"),
  };
}

export const viewport: Viewport = {
  // The browser chrome colour cannot read a CSS variable: keep these equal to --paper in app/globals.css.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfaf6" },
    { media: "(prefers-color-scheme: dark)", color: "#131412" },
  ],
  colorScheme: "light dark",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const locale = await getLocale();
  return (
    <html lang={locale} className={`h-full antialiased ${display.variable} ${text.variable} ${figures.variable}`} suppressHydrationWarning>
      <head>
        {/* The remembered appearance, before the first paint (lib/theme.ts); nothing else runs here. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col bg-paper text-ink">
        {/* Sign out and the error screen read server-formatted strings: no next-intl runtime in the browser. */}
        <ClientStrings strings={await clientStrings(["shell", "errorPage"])}>{children}</ClientStrings>
        {/* After an in-app navigation, focus moves to the new page's title (P16-C1). */}
        <RouteFocus />
      </body>
    </html>
  );
}
