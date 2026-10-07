import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass } from "@/components/ui/Button";

import { LandingFooter } from "./LandingFooter";

/** A public page beside the landing (Explore, Credits): the top bar with "Log in", the page, the landing's footer. */
export async function PublicFrame({ children }: { children: ReactNode }) {
  const t = await getTranslations("landing");
  return (
    <>
      <TopBar>
        <Link href="/login" className={standaloneLinkClass}>
          {t("logIn")}
        </Link>
      </TopBar>
      <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>
      <LandingFooter />
    </>
  );
}
