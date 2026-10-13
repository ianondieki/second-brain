import type { Metadata, Viewport } from "next";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { DEMO_BANNER_NOSCRIPT_CSS, DEMO_BANNER_SCRIPT, PublicDemoBanner } from "@/components/PublicDemoBanner";
import { SkipLink } from "@/components/TopBarBase";
import { RouteFocus } from "@/components/RouteFocus";
import { CELEBRATION_INIT_SCRIPT } from "@/components/tracker/celebration-store";
import { CLOCK_BOOT_SCRIPT } from "@/components/ui/ClockTicker";
import { TOUR_INIT_SCRIPT } from "@/components/tour/tour-store";
import { clientStrings } from "@/lib/i18n/client-strings";
import { DEFERRED_FONTS_CSS, DEFERRED_FONTS_SCRIPT } from "@/lib/fonts";
import { publicDemoOn } from "@/lib/public-demo";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

// Self-hosted faces (public/fonts/LICENCES.md; D-55, D-66; the @font-face rules in globals.css): the faces that paint
// the first screen's text are preloaded at high priority, ahead of the async scripts, so the headline swaps in early
// (mobile LCP, AC-UX-3): Fraunces upright (the titles; 35 KB, instanced to opsz 24–72 and wght 500–700) and the text
// face (Hanken Grotesk, 20 KB). The italic (9 KB, the landing hero's accent phrase only) is preloaded by the hero.
// Bricolage Grotesque (the wordmark and the figures, 21 KB) and the mono face (15 KB) are neither preloaded nor in
// globals.css: lib/fonts.ts declares them once the first frame has painted (P25), and they swap in over their fallbacks.
const PRELOADED_FONTS = ["/fonts/fraunces-v1.woff2", "/fonts/hanken-grotesk-v1.woff2"] as const;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("app");
  const origin = process.env.NEXT_PUBLIC_SITE_ORIGIN;
  return {
    // The site's public origin (frontend/.env.example) makes the share cards' addresses absolute (P24).
    metadataBase: origin ? new URL(origin) : undefined,
    title: { default: t("workingTitle"), template: t("titleTemplate") },
    description: t("tagline"),
    // The public demo (REQ-FND-04): kept out of search engines in the page too, beside the proxy's X-Robots-Tag.
    ...(publicDemoOn() ? { robots: { index: false, follow: false } } : {}),
  };
}

/**
 * The strings the browser's sign-out controls read (components/SignOutButton.tsx, the account menu's fallback): in the
 * public demo, signing out is how a visitor changes persona (it lands on /login's picker), so it says so (REQ-FND-04).
 */
async function shellStrings(demo: boolean) {
  const strings = await clientStrings(["shell", "errorPage"]);
  if (!demo) return strings;
  const t = await getTranslations("publicDemo");
  return {
    ...strings,
    shell: {
      ...strings.shell,
      signOut: t("switchPersona"),
      signingOut: t("switchingPersona"),
      signOutRetry: t("switchRetry"),
    },
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
  // Read per request, on the server (lib/public-demo.ts): the same build runs with the public demo on or off.
  const demo = publicDemoOn();
  return (
    <html lang={locale} className="h-full antialiased" suppressHydrationWarning>
      <head>
        {PRELOADED_FONTS.map((href) => (
          <link key={href} rel="preload" href={href} as="font" type="font/woff2" crossOrigin="anonymous" fetchPriority="high" />
        ))}
        {/* Before the first paint: the remembered appearance (lib/theme.ts) and a stale first-login tour hidden
            (components/tour/tour-store.ts); after it, the two decorative faces (lib/fonts.ts); once parsed, the deadline
            clocks that arrive later run by the page's ticker (components/ui/ClockTicker.tsx). */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              THEME_INIT_SCRIPT +
              TOUR_INIT_SCRIPT +
              CELEBRATION_INIT_SCRIPT +
              DEFERRED_FONTS_SCRIPT +
              CLOCK_BOOT_SCRIPT,
          }}
        />
        <noscript dangerouslySetInnerHTML={{ __html: `<style>${DEFERRED_FONTS_CSS}</style>` }} />
        {/* The public demo's banner: hidden before paint once dismissed this session (components/PublicDemoBanner.tsx). */}
        {demo ? <script dangerouslySetInnerHTML={{ __html: DEMO_BANNER_SCRIPT }} /> : null}
        {demo ? <noscript dangerouslySetInnerHTML={{ __html: `<style>${DEMO_BANNER_NOSCRIPT_CSS}</style>` }} /> : null}
      </head>
      <body className="flex min-h-full flex-col bg-paper text-ink">
        {/* First on every page while the public demo is on: a notice, in the flow (it never covers content), after the
            page's one skip link (the top bar leaves its own out then), so the keyboard's first stop stays "Skip to
            content". */}
        {demo ? <SkipLink /> : null}
        {demo ? <PublicDemoBanner /> : null}
        {/* Sign out and the error screen read server-formatted strings: no next-intl runtime in the browser. */}
        <ClientStrings strings={await shellStrings(demo)}>{children}</ClientStrings>
        {/* After an in-app navigation, focus moves to the new page's title (P16-C1). */}
        <RouteFocus />
      </body>
    </html>
  );
}
