import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { LandingFooter } from "@/components/landing/LandingFooter";
import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass } from "@/components/ui/Button";
import { CheckIcon, EyeOffIcon } from "@/components/ui/icons";

/**
 * The public verification pages in the landing's public language (D-67): its top bar with "Log in", a mono eyebrow
 * over one content column, an aside that says in plain words what a check shows and what it never shows (beside the
 * content from 1024 px behind a hairline, and staying in view; below it on a phone), then the landing's footer. The
 * certificate is the page's one raised sheet, so the aside is plain text on the canvas.
 */
export async function VerifyShell({ children }: { children: ReactNode }) {
  const [t, tl, tp] = await Promise.all([getTranslations("verify"), getTranslations("landing"), getTranslations("portal")]);
  return (
    <>
      <TopBar>
        <Link href="/login" className={standaloneLinkClass}>
          {tl("logIn")}
        </Link>
      </TopBar>
      <div
        className={
          "mx-auto grid w-full max-w-6xl flex-1 grid-cols-1 content-start gap-12 px-4 pt-8 pb-16 sm:px-6 " +
          "lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:gap-16 lg:pt-16"
        }
      >
        <main id="main" tabIndex={-1} className="w-full min-w-0 max-w-2xl focus:outline-none">
          <p className="page-eyebrow mb-3" data-eyebrow="">
            {tp("eyebrow.verify")}
          </p>
          {children}
        </main>
        <aside
          aria-labelledby="what-a-check-shows"
          className="self-start border-t border-line pt-8 lg:sticky lg:top-8 lg:border-t-0 lg:border-l lg:pt-2 lg:pl-8"
        >
          <h2 id="what-a-check-shows" className="text-lg text-ink">
            {t("panelTitle")}
          </h2>
          {/* What it shows (a tick each) and what it never shows (a struck eye): a mark and the words, never colour alone. */}
          <ul className="mt-4 flex flex-col gap-4 text-ink">
            <li className="flex items-start gap-3">
              <CheckIcon className="mt-0.5 size-5 shrink-0 text-accent" />
              <span>{t("panelFingerprint")}</span>
            </li>
            <li className="flex items-start gap-3">
              <CheckIcon className="mt-0.5 size-5 shrink-0 text-accent" />
              <span>{t("panelTime")}</span>
            </li>
            <li className="flex items-start gap-3">
              <EyeOffIcon className="mt-0.5 size-5 shrink-0 text-ink-soft" />
              <span>{t("panelNot")}</span>
            </li>
          </ul>
        </aside>
      </div>
      <LandingFooter />
    </>
  );
}
