import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Row, RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { formatMoment } from "@/lib/format";
import { clientStrings } from "@/lib/i18n/client-strings";

import { Credits } from "./Credits";
import { myContributions, myInvitations, myThreads } from "./data";
import { InvitationList } from "./InvitationList";
import { StatusHost } from "./StatusHost";
import { PEERS_PATH, sortThreads, threadHref, type ThreadSummary } from "./teams";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("teams");
  return { title: t("list.pageTitle") };
}

/**
 * Developer › Team up (REQ-DEV-03; D-58): the pending invitations (received first, each with Accept and Decline;
 * then sent, with Withdraw), then the threads (open ones first, then closed; each the other developer's handle, the
 * problem, the last message's time and how many are unread, as plain text), then the ideas that credit the caller as
 * a contributor. Nothing at all: one sentence and the way to Peers. The screen has no primary action (accepting is
 * one of several equal answers). N28 and N29 land here or on a thread. Developers only.
 */
export default async function TeamsPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const [t, invitations, threads, credits] = await Promise.all([
    getTranslations("teams"),
    myInvitations(),
    myThreads(),
    myContributions(),
  ]);
  const anyInvitation = invitations.received.length + invitations.sent.length > 0;
  const nothing = !anyInvitation && threads.length === 0 && credits.length === 0;
  const strings = await clientStrings(["teamUp"]);

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <div className="flex max-w-4xl flex-col gap-12 lg:gap-14">
        <PageHeader back={{ href: PEERS_PATH, label: t("list.back") }} title={t("list.title")} lead={t("list.lead")} />

        {/* The status line of an answer to an invitation sits above the sections, so reading the page again keeps it. */}
        <ClientStrings strings={strings}>
          <StatusHost>
            {nothing ? (
              <EmptyState className="-mt-4" data-teams="empty" sentence={t("list.empty")} action={t("list.emptyAction")} href={PEERS_PATH} />
            ) : (
              <>
                {anyInvitation ? (
                  <Section title={t("list.invitations")} headingId="teams-invitations" data-teams="invitations">
                    <InvitationList initial={invitations} />
                  </Section>
                ) : null}

                <Section title={t("list.threads")} headingId="teams-threads" data-teams="threads">
                  {threads.length === 0 ? (
                    <p className="text-ink">{t("list.noThreads")}</p>
                  ) : (
                    <div className="rounded-panel border border-line bg-field px-4 sm:px-6">
                      <RowList rule={false} aria-label={t("list.threadsLabel")}>
                        {sortThreads(threads).map((thread) => (
                          <ThreadRow key={thread.id} thread={thread} />
                        ))}
                      </RowList>
                    </div>
                  )}
                </Section>

                {credits.length > 0 ? (
                  <Section title={t("list.credits")} headingId="teams-credits" description={t("list.creditsLead")} data-teams="credits">
                    <Credits initial={credits} />
                  </Section>
                ) : null}
              </>
            )}
          </StatusHost>
        </ClientStrings>
      </div>
    </SignedInShell>
  );
}

/** One thread as a row: the other developer, the problem, the last message's time, and unread or closed in words. */
async function ThreadRow({ thread }: { thread: ThreadSummary }) {
  const [t, locale] = await Promise.all([getTranslations("teams.list"), getLocale()]);
  return (
    <Row
      data-thread={thread.id}
      data-open={thread.open ? "true" : "false"}
      href={threadHref(thread.id)}
      title={thread.counterpart?.handle ?? t("someone")}
      meta={thread.problem.title ? t("on", { title: thread.problem.title }) : t("problemGone")}
    >
      <p className="flex flex-wrap gap-x-4 text-sm text-ink-soft">
        <span className="tabular-nums">
          {thread.last_message_at ? t("lastMessage", { time: formatMoment(locale, thread.last_message_at) }) : t("noMessages")}
        </span>
        {thread.unread > 0 ? (
          <span className="font-semibold text-accent tabular-nums" data-unread={thread.unread}>
            {t("unread", { count: thread.unread })}
          </span>
        ) : null}
        {thread.open ? null : (
          <span className="font-semibold text-ink" data-closed="">
            {t("closed")}
          </span>
        )}
      </p>
    </Row>
  );
}
