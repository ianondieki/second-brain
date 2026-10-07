import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass } from "@/components/ui/Button";

import { Closing } from "./Closing";
import { Features } from "./Features";
import { Hero } from "./Hero";
import { HowItWorks } from "./HowItWorks";
import { LandingFooter } from "./LandingFooter";
import { Proof } from "./Proof";
import { Questions } from "./Questions";
import { Sides } from "./Sides";
import { Trust } from "./Trust";

const sectionLink =
  "inline-flex min-h-11 items-center rounded-full px-4 font-semibold text-ink-soft no-underline hover:bg-wash-soft hover:text-ink";

/**
 * The landing page (D-55, Jacaranda): the night hero with the product, the strip of what every proposal carries, how it works with the tracker's five stages,
 * who it is for, what you can do, proof of authorship with a certificate check, questions, the closing call and the
 * footer. No data read and no script of its own: the page only decides the redirect of a signed-in person. Nothing
 * here claims protection or figures; every product picture is labelled example data.
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
              <a href="#organisations" className={sectionLink}>
                {t("nav.organisations")}
              </a>
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
        <Trust />
        <HowItWorks />
        <Sides />
        <Features />
        <Proof />
        <Questions />
        <Closing />
      </main>
      <LandingFooter />
    </>
  );
}
