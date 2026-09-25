import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { BridgeLine } from "./BridgeLine";
import { TopBar } from "./TopBar";
import { cn } from "./ui/cn";

export interface AuthShellProps {
  children: ReactNode;
  /**
   * The landing page: the bridge line draws once, the column is wider for the headline, and the "how it works"
   * panel also shows below the actions on phones. Form screens keep the panel to 1024 px and up.
   */
  landing?: boolean;
  /** One control on the right of the top bar (for example "Sign out" on the second-factor page). */
  topBarAction?: ReactNode;
}

/** Signed-out screens: top bar, one left-aligned column (max 28 rem for forms), and the side panel on desktop. */
export async function AuthShell({ children, landing = false, topBarAction }: AuthShellProps) {
  const t = await getTranslations("panel");
  return (
    <>
      <TopBar>{topBarAction}</TopBar>
      <div
        className={
          "mx-auto grid w-full max-w-6xl flex-1 grid-cols-1 content-start gap-12 px-4 pt-8 pb-16 sm:px-6 " +
          "lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] lg:gap-20 lg:pt-16"
        }
      >
        <main id="main" tabIndex={-1} className={cn("w-full focus:outline-none", landing ? "max-w-xl" : "max-w-md")}>
          {children}
        </main>
        <aside
          aria-labelledby="how-it-works"
          className={cn("self-start rounded-panel bg-jacaranda-wash p-6 lg:p-8", !landing && "hidden lg:block")}
        >
          <BridgeLine
            developerLabel={t("developer")}
            organisationLabel={t("organisation")}
            animate={landing}
          />
          <h2 id="how-it-works" className="mt-8 text-lg text-ink">
            {t("title")}
          </h2>
          <ol className="mt-3 flex list-decimal flex-col gap-3 pl-5 text-ink marker:font-semibold marker:text-jacaranda">
            <li className="pl-1">{t("publish")}</li>
            <li className="pl-1">{t("review")}</li>
            <li className="pl-1">{t("track")}</li>
          </ol>
        </aside>
      </div>
    </>
  );
}
