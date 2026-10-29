import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { PortalNavFor } from "@/components/PortalNavFor";
import { SignedInShell } from "@/components/SignedInShell";
import { PublicFrame } from "@/components/landing/PublicFrame";
import { ShowTourAgain } from "@/components/tour/ShowTourAgain";
import { textLinkClass } from "@/components/ui/Button";
import { PageHero } from "@/components/ui/PageHero";
import { Section } from "@/components/ui/Section";
import { getMe, getUnreadCount } from "@/lib/api/server";
import { homeOf, isPending, type Home, type Me } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { HELP_SECTIONS, NOTIFICATIONS_HREF } from "./sections";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("help");
  return { title: t("pageTitle") };
}

/** The signed-in person (and their home), or null for a visitor (and when the API cannot say: help must open regardless). */
async function signedIn(): Promise<{ me: Me; home: Home } | null> {
  // The bell's count, started beside /api/auth/me as requireMe does; with no session cookie it asks nothing.
  void getUnreadCount();
  try {
    const me = await getMe();
    return me && !isPending(me) ? { me, home: homeOf(me) } : null;
  } catch {
    return null;
  }
}

/**
 * Help (docs/spec/07 item 1, the avatar menu; every email footer's "Help"): short plain answers on pitching, what
 * stays confidential, reminders and support. Public, so a link from an email opens whether or not the reader is
 * signed in; signed in, it has the account menu. Server-rendered text only: no script of its own.
 */
export default async function HelpPage() {
  const [t, tp] = await Promise.all([getTranslations("help"), getTranslations("portal")]);
  const person = await signedIn();
  // The first-login tour, on request, for the two sides that have one (the staff console has none).
  const hasTour = person !== null && (person.home === "/dev" || person.home === "/org");
  const tTour = hasTour ? await getTranslations("tour") : null;
  const entries = [
    ...HELP_SECTIONS.map(({ id }) => ({ id: `help-${id}`, label: t(`${id}.title`) })),
    ...(tTour ? [{ id: "help-tour", label: tTour("title") }] : []),
  ];
  const content = (
    <>
      <PageHero eyebrow={tp("eyebrow.help")} title={t("pageTitle")} lead={t("lead")} />
      {/* A reading page: the answers at a comfortable measure, and a contents list that stays beside them from
          1024 px (under the header on a phone). The list is a navigation, not a heading, so the page's h2s are
          only its sections. */}
      <div className="mt-8 grid grid-cols-1 gap-10 lg:mt-10 lg:grid-cols-[minmax(0,1fr)_13rem] lg:gap-12">
        <nav
          aria-label={t("contents")}
          className="self-start border-l border-line pl-4 lg:sticky lg:top-8 lg:col-start-2 lg:row-start-1"
        >
          <p className="text-sm font-semibold text-ink-soft">{t("contents")}</p>
          <ul className="mt-1 flex flex-col">
            {entries.map((entry) => (
              <li key={entry.id}>
                <a
                  href={`#${entry.id}`}
                  className="inline-flex min-h-11 items-center text-ink no-underline hover:text-accent hover:underline lg:min-h-9"
                >
                  {entry.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex max-w-[65ch] flex-col gap-12 lg:col-start-1 lg:row-start-1 lg:gap-14">
          {HELP_SECTIONS.map(({ id, paragraphs }) => (
            <Section key={id} title={t(`${id}.title`)} headingId={`help-${id}`} data-help-section={id}>
              <div className="flex flex-col gap-3 text-ink">
                {paragraphs.map((key) => (
                  <p key={key} data-support-placeholder={key === "support.body" ? "" : undefined}>
                    {key === "reminders.manage"
                      ? t.rich(key, {
                          link: (chunks: ReactNode) => (
                            <Link href={NOTIFICATIONS_HREF} className={textLinkClass}>
                              {chunks}
                            </Link>
                          ),
                        })
                      : t(key)}
                  </p>
                ))}
              </div>
            </Section>
          ))}
          {person && tTour ? (
            <Section title={tTour("title")} headingId="help-tour" data-help-section="tour">
              <ClientStrings strings={await clientStrings(["tour"])}>
                <ShowTourAgain side={person.home === "/org" ? "org" : "developer"} />
              </ClientStrings>
            </Section>
          ) : null}
        </div>
      </div>
    </>
  );

  if (person) {
    return (
      <SignedInShell homeHref={person.home} nav={<PortalNavFor me={person.me} />} wide>
        {content}
      </SignedInShell>
    );
  }
  // A visitor reads it in the landing's public frame (its top bar with "Log in", its footer; D-67).
  return (
    <PublicFrame>
      <div className="mx-auto w-full max-w-6xl px-4 pt-8 pb-16 sm:px-6 lg:pt-16">
        <div className="max-w-4xl">{content}</div>
      </div>
    </PublicFrame>
  );
}
