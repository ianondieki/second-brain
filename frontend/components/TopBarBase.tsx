import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import type { AnchorComponent } from "./anchor";
import { Wordmark } from "./brand/Logo";

export interface TopBarBaseProps {
  homeHref?: string;
  /** next/link on pages (TopBar), a plain "a" on the static not-found screen. */
  Anchor: AnchorComponent;
  children?: ReactNode;
}

/**
 * Skip link plus the top bar: a quiet white band with a hairline under it, the wordmark (a link home) on the left and
 * at most one control on the right. No badge and no lattice (D-65: the honesty label lives with the demo data, the
 * lattice frames the hero, the certificate and the footer). Not sticky, so it never covers a focused control. Without
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
          "focus:bg-field focus:px-4 focus:py-2.5 focus:min-h-11 focus:font-semibold focus:text-accent"
        }
      >
        {t("skipToContent")}
      </a>
      <header className="border-b border-line bg-field">
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
