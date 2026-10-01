import type { Metadata, Viewport } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { RouteFocus } from "@/components/RouteFocus";
import { clientStrings } from "@/lib/i18n/client-strings";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

// Self-hosted faces (public/fonts/LICENCES.md; D-52; the @font-face rules in globals.css): the two faces that paint
// above the fold are preloaded at high priority, ahead of the async scripts, so the headline swaps in early (mobile
// LCP, AC-UX-3). The display face is instanced to the one weight the headings use (500) over optical sizes 18–72
// (42 KB, from 132); the text face to the weights in use (400–600; 35 KB, from 45); the mono face (fingerprints and
// codes, below the fold) is not preloaded.
const PRELOADED_FONTS = ["/fonts/newsreader-latin.woff2", "/fonts/ibm-plex-sans-latin.woff2"] as const;

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
    <html lang={locale} className="h-full antialiased" suppressHydrationWarning>
      <head>
        {PRELOADED_FONTS.map((href) => (
          <link key={href} rel="preload" href={href} as="font" type="font/woff2" crossOrigin="anonymous" fetchPriority="high" />
        ))}
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
