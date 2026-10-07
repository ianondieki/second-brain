import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass } from "@/components/ui/Button";

import { Suspense } from "react";

import { Activity } from "./Activity";
import { Closing } from "./Closing";
import { Counties } from "./Counties";
import { Features } from "./Features";
import { Hero } from "./Hero";
import { HowItWorks } from "./HowItWorks";
import { LandingFooter } from "./LandingFooter";
import { Proof } from "./Proof";
import { Questions } from "./Questions";
import { Reasons } from "./Reasons";

const sectionLink =
  "inline-flex min-h-11 items-center rounded-full px-4 font-semibold text-ink-soft no-underline hover:bg-wash-soft hover:text-ink";

/**
 * The landing page (D-66, "Jacaranda in print"): the hero on paper with the product panel and the stats row of
 * product constants, the county strip, how it works in three numbered steps, the night band with the ranker's
 * reasons, what you can do, what's happening (the public activity feed, left out when it cannot be read; streamed, so
 * the page never waits on it), proof of authorship with a certificate check, questions, the closing call and the
 * footer. Nothing here claims protection or a usage figure; every product picture is labelled example data.
 */
export async function LandingContent() {
  const t = await getTranslations("landing");
  return (
    <>
      <TopBar>
        <nav aria-label={t("nav.label")}>
          <ul className="flex items-center gap-1">
            <li className="hidden lg:block">
              <a href="#how" className={sectionLink}>
                {t("nav.how")}
              </a>
            </li>
            <li className="hidden lg:block">
              <Link href="/explore" className={sectionLink}>
                {t("nav.explore")}
              </Link>
            </li>
            <li className="hidden lg:block">
              <Link href="/verify" className={sectionLink}>
                {t("nav.verify")}
              </Link>
            </li>
            <li className="lg:ml-3">
              <Link href="/login" className={standaloneLinkClass}>
                {t("logIn")}
              </Link>
            </li>
          </ul>
        </nav>
      </TopBar>
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <Hero />
        <Counties />
        <HowItWorks />
        <Reasons />
        <Features />
        <Suspense fallback={null}>
          <Activity />
        </Suspense>
        <Proof />
        <Questions />
        <Closing />
      </main>
      <LandingFooter />
    </>
  );
}
