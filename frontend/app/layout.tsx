import type { Metadata, Viewport } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { RouteFocus } from "@/components/RouteFocus";
import { CELEBRATION_INIT_SCRIPT } from "@/components/tracker/celebration-store";
import { TOUR_INIT_SCRIPT } from "@/components/tour/tour-store";
import { clientStrings } from "@/lib/i18n/client-strings";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

// Self-hosted faces (public/fonts/LICENCES.md; D-55, D-66; the @font-face rules in globals.css): the faces that paint
// the first screen's text are preloaded at high priority, ahead of the async scripts, so the headline swaps in early
// (mobile LCP, AC-UX-3): Fraunces upright (the titles; 46 KB, instanced to opsz 24–144 and wght 400–700) and the text
// face (Hanken Grotesk, 20 KB). The italic (the landing hero's accent phrase only) is preloaded by the landing's hero.
// Bricolage Grotesque (the wordmark and the figures, 34 KB) and the mono face are not preloaded: the wordmark has a
// sized fallback and the figures sit lower.
const PRELOADED_FONTS = ["/fonts/fraunces-v1.woff2", "/fonts/hanken-grotesk-v1.woff2"] as const;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("app");
  const origin = process.env.NEXT_PUBLIC_SITE_ORIGIN;
  return {
    // The site's public origin (frontend/.env.example) makes the share cards' addresses absolute (P24).
    metadataBase: origin ? new URL(origin) : undefined,
    title: { default: t("workingTitle"), template: t("titleTemplate") },
    description: t("tagline"),
  };
}

export const viewport: Viewport = {
  // The browser chrome colour cannot read a CSS variable: keep these equal to --paper in app/globals.css.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f4ed" },
    { media: "(prefers-color-scheme: dark)", color: "#100c1d" },
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
        {/* Before the first paint: the remembered appearance (lib/theme.ts) and a stale first-login tour hidden
            (components/tour/tour-store.ts); nothing else runs here. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT + TOUR_INIT_SCRIPT + CELEBRATION_INIT_SCRIPT }} />
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
