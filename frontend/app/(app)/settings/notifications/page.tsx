import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { SignedInShell } from "@/components/SignedInShell";
import { forwardHeaders, requireMe, serverApi } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { EmptyState } from "../../org/EmptyState";
import { notificationChoices, type ConsentItem } from "./choices";
import { NotificationChoices } from "./NotificationChoices";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("notificationSettings");
  return { title: t("pageTitle") };
}

/** The signed-in person's consents (GET /api/me/consents), bounded so a hung API ends in the route's error page. */
async function myConsents(): Promise<ConsentItem[]> {
  const { data, response } = await serverApi().GET("/api/me/consents", {
    headers: await forwardHeaders(),
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (response.status === 401) redirect("/login"); // the session ended between the page's /me check and this call
  if (!data) throw new Error(`GET /api/me/consents answered ${response.status}`);
  return data;
}

/**
 * Notification settings (docs/spec/07 item 1, the avatar menu; every email footer's "Manage notifications"): the
 * consents that decide which messages are sent, for anyone signed in, on either side (REQ-CON-01, REQ-NOT-03).
 */
export default async function NotificationSettingsPage() {
  const me = await requireMe();
  const home = homeOf(me);
  const t = await getTranslations("notificationSettings");
  const choices = notificationChoices(await myConsents());
  return (
    <SignedInShell homeHref={home}>
      <h1 className="text-xl text-ink lg:text-2xl">{t("pageTitle")}</h1>
      <p className="mt-3 max-w-[60ch] text-ink-soft">{t("lead")}</p>
      <div className="mt-8">
        {choices.length === 0 ? (
          <EmptyState sentence={t("empty")} action={t("action.home")} href={home} />
        ) : (
          <ClientStrings strings={await clientStrings(["notificationSettings"])}>
            <NotificationChoices initial={choices} />
          </ClientStrings>
        )}
      </div>
    </SignedInShell>
  );
}
