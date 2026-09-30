import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { SignedInShell } from "@/components/SignedInShell";
import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass, textLinkClass } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { getMe } from "@/lib/api/server";
import { homeOf, isPending, type Home } from "@/lib/auth/routing";

import { HELP_SECTIONS, NOTIFICATIONS_HREF } from "./sections";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("help");
  return { title: t("pageTitle") };
}

/** The signed-in person's home, or null for a visitor (and when the API cannot say: help must open regardless). */
async function signedInHome(): Promise<Home | null> {
  try {
    const me = await getMe();
    return me && !isPending(me) ? homeOf(me) : null;
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
  const t = await getTranslations("help");
  const home = await signedInHome();
  const content = (
    <>
      <PageHeader title={t("pageTitle")} lead={t("lead")} />
      <div className="mt-10 flex flex-col gap-12">
        {HELP_SECTIONS.map(({ id, paragraphs }) => (
          <Section key={id} title={t(`${id}.title`)} headingId={`help-${id}`} data-help-section={id}>
            <div className="flex max-w-[65ch] flex-col gap-3 text-ink">
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
      </div>
    </>
  );

  if (home) return <SignedInShell homeHref={home}>{content}</SignedInShell>;
  return (
    <>
      <TopBar>
        <Link href="/login" className={standaloneLinkClass}>
          {t("logIn")}
        </Link>
      </TopBar>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 pb-16 focus:outline-none sm:px-6 lg:pt-16">
        <div className="max-w-xl">{content}</div>
      </main>
    </>
  );
}
