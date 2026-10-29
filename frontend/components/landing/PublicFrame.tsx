import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { TopBar } from "@/components/TopBar";
import { standaloneLinkClass } from "@/components/ui/Button";
import { publicDemoOn } from "@/lib/public-demo";

import { LandingFooter } from "./LandingFooter";

/**
 * A public page beside the landing (Explore, Credits): the top bar with "Log in" ("Try the demo" in the public demo,
 * where /login is the persona picker; REQ-FND-04), the page, the landing's footer.
 */
export async function PublicFrame({ children }: { children: ReactNode }) {
  const [t, tDemo] = await Promise.all([getTranslations("landing"), getTranslations("publicDemo")]);
  return (
    <>
      <TopBar>
        <Link href="/login" className={standaloneLinkClass}>
          {publicDemoOn() ? tDemo("tryDemo") : t("logIn")}
        </Link>
      </TopBar>
      <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>
      <LandingFooter />
    </>
  );
}
