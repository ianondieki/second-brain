import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Seal } from "@/components/brand/Seal";
import { Wordmark } from "@/components/brand/Logo";
import { HeroComposition } from "@/components/landing/HeroComposition";
import { ThemeToggle } from "@/components/ThemeToggle";
import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass, textLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { Card, CardGrid } from "@/components/ui/Card";
import { CompaniesIcon, IdeasIcon } from "@/components/ui/icons";
import { Lattice } from "@/components/ui/Lattice";
import { CheckIcon, ClockIcon, LockIcon, SendIcon } from "@/components/ui/status-icons";
import { EngagementsIcon } from "@/components/tracker/icons";

const STEPS = [
  { key: "publish", Icon: IdeasIcon },
  { key: "review", Icon: LockIcon },
  { key: "track", Icon: EngagementsIcon },
] as const;

const PROOF = [
  { key: "when", Icon: ClockIcon },
  { key: "what", Icon: CheckIcon },
  { key: "who", Icon: SendIcon },
] as const;

/**
 * The landing page's content (D-52): the promise and a live product visual, how it works in three steps, who it is
 * for, the proof-of-authorship story, and one last call to action. No data read: the page itself only decides the
 * redirect of a signed-in person. Nothing here claims protection or figures: the visual is labelled an example.
 */
export async function LandingContent() {
  const t = await getTranslations("landing");
  return (
    <>
      <TopBar>
        <Link href="/login" className={standaloneLinkClass}>
          {t("logIn")}
        </Link>
      </TopBar>
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <section aria-labelledby="hero-title" className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-4 pt-10 pb-16 sm:px-6 lg:gap-12 lg:pt-16 lg:pb-24">
          <div className="max-w-4xl">
            {/* Eight words, two balanced lines from 1024 px (32ch at 56 px fits the column). */}
            <h1 id="hero-title" className="max-w-[32ch] text-3xl text-ink lg:text-[3.5rem] lg:leading-[1.06]">
              {t("title")}
            </h1>
            <p className="mt-5 max-w-[60ch] text-lg text-ink-soft lg:text-xl">{t("lead")}</p>
            <div className="mt-8 flex flex-col items-start gap-4">
              <ButtonLink href="/signup" variant="primary">
                {t("signUp")}
              </ButtonLink>
              <p className="text-ink">
                {t.rich("haveAccount", {
                  login: (chunks) => (
                    <Link href="/login" className={textLinkClass}>
                      {chunks}
                    </Link>
                  ),
                })}
              </p>
            </div>
          </div>
          <HeroComposition />
        </section>

        <section aria-labelledby="how-title" className="border-y border-line bg-field">
          <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 lg:py-20">
            <h2 id="how-title" className="text-2xl text-ink">
              {t("how.title")}
            </h2>
            <p className="mt-2 max-w-[60ch] text-ink-soft">{t("how.lead")}</p>
            <ol className="mt-10 grid grid-cols-1 gap-8 md:grid-cols-3 md:gap-10">
              {STEPS.map(({ key, Icon }, index) => (
                <li key={key} className="flex gap-4">
                  <span aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent-wash text-accent">
                    <Icon className="size-5" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-base text-ink">
                      <span className="mr-2 font-display text-lg font-medium text-accent tabular-nums">{index + 1}.</span>
                      {t(`how.${key}.title`)}
                    </h3>
                    <p className="mt-1.5 max-w-[40ch] text-ink-soft">{t(`how.${key}.body`)}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section aria-labelledby="who-title" className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 lg:py-20">
          <h2 id="who-title" className="text-2xl text-ink">
            {t("who.title")}
          </h2>
          <CardGrid className="mt-8 lg:gap-6">
            {(["developers", "organisations"] as const).map((side) => {
              const Icon = side === "developers" ? IdeasIcon : CompaniesIcon;
              return (
                <li key={side}>
                <Card className="flex h-full flex-col gap-4 p-6 lg:p-8">
                  <span aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center self-start rounded-control bg-accent-wash text-accent">
                    <Icon className="size-5" />
                  </span>
                  <h3 className="font-display text-xl font-medium text-ink">{t(`who.${side}.title`)}</h3>
                  <ul className="flex flex-col gap-2 text-ink">
                    {([1, 2, 3] as const).map((n) => (
                      <li key={n} className="flex gap-3">
                        <CheckIcon className="mt-1 size-4 shrink-0 text-accent" />
                        <span>{t(`who.${side}.point${n}`)}</span>
                      </li>
                    ))}
                  </ul>
                  <Link href="/signup" className={standaloneLinkClass}>
                    {t(`who.${side}.action`)}
                  </Link>
                </Card>
                </li>
              );
            })}
          </CardGrid>
        </section>

        <section aria-labelledby="proof-title" className="border-y border-line bg-field">
          <div className="mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[auto_minmax(0,1fr)] lg:gap-16 lg:py-20">
            <Seal size={160} animate className="mx-auto lg:mx-0" />
            <div>
              <h2 id="proof-title" className="text-2xl text-ink">
                {t("proof.title")}
              </h2>
              <p className="mt-2 max-w-[60ch] text-ink-soft">{t("proof.lead")}</p>
              <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-3">
                {PROOF.map(({ key, Icon }) => (
                  <li key={key} className="flex flex-col gap-2">
                    <Icon className="size-5 text-accent" />
                    <h3 className="text-base text-ink">{t(`proof.${key}.title`)}</h3>
                    <p className="text-sm text-ink-soft">{t(`proof.${key}.body`)}</p>
                  </li>
                ))}
              </ul>
              <p className="mt-6 max-w-[60ch] text-sm text-ink-soft">
                {t.rich("proof.note", {
                  verify: (chunks) => (
                    <Link href="/verify" className={textLinkClass}>
                      {chunks}
                    </Link>
                  ),
                })}
              </p>
            </div>
          </div>
        </section>

        <section aria-labelledby="cta-title" className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 lg:py-20">
          <div className="overflow-hidden rounded-panel bg-accent-wash">
            <Lattice />
            <div className="flex flex-col items-start gap-5 p-6 sm:p-10">
              <h2 id="cta-title" className="text-2xl text-ink">
                {t("cta.title")}
              </h2>
              <p className="max-w-[56ch] text-ink">{t("cta.lead")}</p>
              <ButtonLink href="/signup" variant="secondary">
                {t("cta.action")}
              </ButtonLink>
            </div>
          </div>
        </section>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="flex flex-col gap-2">
            <Wordmark size={22} />
            <p className="text-sm text-ink-soft">{t("footer.note")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Link href="/help" className={`${standaloneLinkClass} px-2`}>
              {t("footer.help")}
            </Link>
            <Link href="/legal/terms" className={`${standaloneLinkClass} px-2`}>
              {t("footer.terms")}
            </Link>
            <ThemeToggle />
          </div>
        </div>
      </footer>
    </>
  );
}
