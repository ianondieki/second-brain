import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { OfflineAction } from "@/components/offline/OfflineAction";
import { TopBarBase } from "@/components/TopBarBase";
import { EmptyStateFrame } from "@/components/ui/EmptyStateFrame";
import { PageHeader } from "@/components/ui/PageHeader";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("offline");
  return { title: t("pageTitle"), robots: { index: false } };
}

/**
 * /offline (P27 track F; REQ-UX-08; D-69): what the service worker answers when a page cannot be loaded and it holds no
 * copy of it. Cached when the worker installs, so it reads no session and calls no API: the top bar, the title, one
 * sentence and one action (docs/spec/07 item 4), Engagements of the portal the address belongs to (where the trackers
 * kept on this device are), else the home page. No photograph.
 */
export default async function OfflinePage() {
  const t = await getTranslations("offline");
  return (
    <>
      <TopBarBase homeHref="/" Anchor="a" />
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 pb-16 focus:outline-none sm:px-6 lg:pt-16"
        data-offline-page=""
      >
        <div className="max-w-md">
          <PageHeader title={t("title")} />
          <EmptyStateFrame
            className="mt-6"
            illustration="waiting"
            sentence={t("body")}
            action={<OfflineAction engagements={t("engagements")} home={t("home")} />}
          />
        </div>
      </main>
    </>
  );
}
