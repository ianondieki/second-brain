import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";

import { pickMessages } from "@/components/IntlScope";

import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("app");
  return {
    title: { default: t("workingTitle"), template: t("titleTemplate") },
    description: t("tagline"),
  };
}

export const viewport: Viewport = {
  // The browser chrome colour cannot read a CSS variable: keep this equal to --paper in app/globals.css.
  themeColor: "#f5f7f3",
  colorScheme: "light",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const locale = await getLocale();
  return (
    <html lang={locale} className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-paper text-ink">
        <NextIntlClientProvider messages={await pickMessages(["shell", "errorPage"])}>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
