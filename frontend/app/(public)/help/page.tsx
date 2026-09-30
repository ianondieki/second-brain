import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { SignedInShell } from "@/components/SignedInShell";
import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass, textLinkClass } from "@/components/ui/Button";
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
      <h1 className="text-xl text-ink lg:text-2xl">{t("pageTitle")}</h1>
      <p className="mt-3 max-w-[60ch] text-ink-soft">{t("lead")}</p>
      <div className="mt-8 flex flex-col gap-8">
        {HELP_SECTIONS.map(({ id, paragraphs }) => (
          <section key={id} aria-labelledby={`help-${id}`} data-help-section={id} className="border-t border-line pt-6">
            <h2 id={`help-${id}`} className="text-lg text-ink">
              {t(`${id}.title`)}
            </h2>
            <div className="mt-2 flex max-w-[60ch] flex-col gap-3 text-ink">
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
          </section>
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
