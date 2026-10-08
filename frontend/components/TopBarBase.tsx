import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import type { AnchorComponent } from "./anchor";
import { Wordmark } from "./brand/Logo";

export interface TopBarBaseProps {
  homeHref?: string;
  /** next/link on pages (TopBar), a plain "a" on the static not-found screen. */
  Anchor: AnchorComponent;
  children?: ReactNode;
  /** Signed-in screens (P25): the bar stays at the top from 1024 px, where the rail and the Search sit under it and
   *  the page's scroll padding keeps a focused control clear of it (globals.css). Phones keep the whole height. */
  sticky?: boolean;
}

/**
 * Skip link plus the top bar: a quiet white band with a hairline under it, the wordmark (a link home) on the left and
 * at most one control on the right. No badge and no lattice (D-65: the honesty label lives with the demo data, the
 * lattice frames the hero, the certificate and the footer). Sticky only on signed-in screens from 1024 px, with the
 * page's scroll padding clearing it, so it never covers a focused control. Without
 * next/link in its module (see components/anchor.ts); pages use TopBar.
 */
export async function TopBarBase({ homeHref = "/", Anchor: Home, children, sticky = false }: TopBarBaseProps) {
  const t = await getTranslations("shell");
  return (
    <>
      <a
        href="#main"
        className={
          "sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-10 focus:rounded-control " +
          "focus:bg-field focus:px-4 focus:py-2.5 focus:min-h-11 focus:font-semibold focus:text-accent"
        }
      >
        {t("skipToContent")}
      </a>
      <header
        data-top-bar=""
        data-sticky={sticky ? "" : undefined}
        className={sticky ? "border-b border-line bg-field lg:sticky lg:top-0 lg:z-20" : "border-b border-line bg-field"}
      >
        <div className="mx-auto flex min-h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <Home href={homeHref} className="-mx-1 inline-flex min-h-11 items-center px-1 no-underline" aria-label={t("workingName")}>
            <Wordmark size={30} />
          </Home>
          {children}
        </div>
      </header>
    </>
  );
}
