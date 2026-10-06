import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings, type StringTree } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { problemHref } from "@/components/problem/problem";
import { nairobiToday } from "@/components/tracker/input";
import { textLinkClass } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { InfoIcon } from "@/components/ui/status-icons";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { myPublishedIdeas, teamThread } from "../data";
import { closedReason, TEAMS_PATH, toThreadPage } from "../teams";
import { StepButtons } from "./StepButtons";
import { TeamThread } from "./TeamThread";
import { STEP_FAILED_ID, STEPS_ID } from "./ids";

export async function generateMetadata({ params }: PageProps<"/dev/teams/[id]">): Promise<Metadata> {
  const t = await getTranslations("teams");
  const read = await teamThread((await params).id).catch(() => null);
  return { title: read?.thread.counterpart?.handle ?? t("thread.pageTitle") };
}

/**
 * One team thread (REQ-DEV-03; D-58, D-62): the other developer's handle and the problem the two team up on (a link
 * to it while it is published), the thread's steps (credit them on one of the caller's published ideas; leave or
 * block, in the overflow menu), then the messages on the engagement thread's parts with Send as the one primary
 * action. A closed thread stays readable, with one sentence saying why it closed in place of the composer. N29 links
 * here. Developers who are not a party get the not-found page; organisations go to their own home.
 */
export default async function TeamThreadPage({ params }: PageProps<"/dev/teams/[id]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const id = (await params).id;
  const [t, tu, locale, read, published] = await Promise.all([
    getTranslations("teams"),
    getTranslations("teamUp"),
    getLocale(),
    teamThread(id),
    myPublishedIdeas(),
  ]);
  const { thread } = read;
  const name = thread.counterpart?.handle ?? t("list.someone");
  const reason = closedReason(thread);
  const counterpart = thread.counterpart ? { user_id: thread.counterpart.user_id, handle: thread.counterpart.handle } : null;
  const page = toThreadPage(read, name);
  const empty = page.items.length === 0 && !page.next_cursor;
  // The ideas the other developer can be credited on: the caller's published ones ([] when they cannot be read).

  // The composer's refusal for a thread that closed meanwhile says "thread", not "engagement" (same parts, own words).
  const strings = await clientStrings(["trackerMessages", "teamUp"]);
  const messages = strings.trackerMessages as StringTree;
  const closedNow = t("thread.refusalClosed");
  strings.trackerMessages = { ...messages, refusal: { ...(messages.refusal as StringTree), readOnly: closedNow, cannotPost: closedNow } };

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <div className="flex max-w-3xl flex-col gap-10 [&:has([data-thread][data-hydrated=false])_#thread-steps]:pointer-events-none [&:has([data-thread][data-hydrated=false])_#thread-steps]:opacity-60">
        <PageHeader back={{ href: TEAMS_PATH, label: t("thread.back") }} title={name}>
          <p className="mt-2 text-ink-soft [overflow-wrap:anywhere]" data-thread-problem="">
            {thread.problem.title
              ? t.rich("thread.on", {
                  title: thread.problem.title,
                  link: (chunks) => (
                    <Link href={problemHref(thread.problem.id)} className={textLinkClass}>
                      {chunks}
                    </Link>
                  ),
                })
              : t("thread.onGone")}
          </p>
        </PageHeader>

        <ClientStrings strings={strings}>
          {/* The steps' buttons are markup; TeamThread answers their presses and puts a step's dialog and status line
              in the first box (nothing of the steps ships with the page: docs/spec/07 item 5). */}
          <div className="-mt-4 flex flex-col gap-4" data-thread-actions="">
            <div id={STEP_FAILED_ID} hidden tabIndex={-1} className="focus:outline-none">
              <Alert>{tu("thread.loadFailed")}</Alert>
            </div>
            {/* Dimmed and not pressable until the thread's script answers them (it has hydrated). */}
            <div id={STEPS_ID} className="flex flex-wrap items-center gap-3 empty:hidden">
              <StepButtons
                credit={counterpart && published.length > 0 ? tu("credit.add") : null}
                more={tu("thread.more")}
                leave={thread.open ? tu("thread.leave") : null}
                block={counterpart ? tu("thread.block", { name: counterpart.handle }) : null}
              />
            </div>
          </div>

          <Section
            title={t("thread.title")}
            headingId="team-thread-heading"
            description={thread.open ? t("thread.lead") : undefined}
            data-thread-state={thread.open ? "open" : "closed"}
          >
            <TeamThread
              threadId={thread.id}
              initial={page}
              counterpart={name}
              today={nairobiToday()}
              locale={locale}
              empty={reason ? null : t("thread.empty")}
              person={counterpart}
              ideas={published}
            />
            {reason ? (
              <p className="mt-6 flex max-w-[65ch] items-start gap-2 text-ink" data-thread-closed={reason}>
                <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />
                <span>{empty ? t("thread.closedEmpty") : t(`thread.closed.${reason}`)}</span>
              </p>
            ) : null}
          </Section>
        </ClientStrings>
      </div>
    </SignedInShell>
  );
}
