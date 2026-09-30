import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import type { AnchorComponent } from "./anchor";

export interface TopBarBaseProps {
  homeHref?: string;
  /** next/link on pages (TopBar), a plain "a" in the route loading states. */
  Anchor: AnchorComponent;
  children?: ReactNode;
}

/**
 * Skip link plus the top bar: the working name on the left, at most one control on the right. Not sticky. Without
 * next/link in its module (see components/anchor.ts); pages use TopBar.
 */
export async function TopBarBase({ homeHref = "/", Anchor: Home, children }: TopBarBaseProps) {
  const t = await getTranslations("shell");
  return (
    <>
      <a
        href="#main"
        className={
          "sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-10 focus:rounded-control " +
          "focus:bg-field focus:px-4 focus:py-2.5 focus:min-h-11 focus:font-semibold focus:text-jacaranda"
        }
      >
        {t("skipToContent")}
      </a>
      <header className="border-b border-line">
        <div className="mx-auto flex min-h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <Home
            href={homeHref}
            className="-mx-1 inline-flex min-h-11 items-center px-1 text-base font-semibold tracking-[-0.01em] text-ink no-underline"
          >
            {t("workingName")}
          </Home>
          {children}
        </div>
      </header>
    </>
  );
}
