import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { TopBar } from "@/components/TopBar";
import { Panel } from "@/components/ui/Panel";

/**
 * The public verification pages: top bar, one content column, and a panel that says in plain words what a check
 * shows and what it never shows (beside the content from 1024 px, below it on a phone).
 */
export async function VerifyShell({ children }: { children: ReactNode }) {
  const t = await getTranslations("verify");
  return (
    <>
      <TopBar />
      <div
        className={
          "mx-auto grid w-full max-w-6xl flex-1 grid-cols-1 content-start gap-12 px-4 pt-8 pb-16 sm:px-6 " +
          "lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:gap-16 lg:pt-16"
        }
      >
        <main id="main" tabIndex={-1} className="w-full min-w-0 max-w-2xl focus:outline-none">
          {children}
        </main>
        <Panel as="aside" variant="wash" aria-labelledby="what-a-check-shows" className="self-start">
          <h2 id="what-a-check-shows" className="text-lg text-ink">
            {t("panelTitle")}
          </h2>
          <ul className="mt-3 flex list-disc flex-col gap-3 pl-5 text-ink marker:text-accent">
            <li className="pl-1">{t("panelFingerprint")}</li>
            <li className="pl-1">{t("panelTime")}</li>
            <li className="pl-1">{t("panelNot")}</li>
          </ul>
        </Panel>
      </div>
    </>
  );
}
