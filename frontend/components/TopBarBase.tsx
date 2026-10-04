import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import type { AnchorComponent } from "./anchor";
import { Wordmark } from "./brand/Logo";
import { Lattice } from "./ui/Lattice";

export interface TopBarBaseProps {
  homeHref?: string;
  /** next/link on pages (TopBar), a plain "a" on the static not-found screen. */
  Anchor: AnchorComponent;
  children?: ReactNode;
}

/**
 * Skip link plus the top bar: the lattice band, the wordmark (a link home) and the prototype badge on the left, at
 * most one control on the right. Not sticky. Without
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
        <Lattice />
        <div className="mx-auto flex min-h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <span className="flex min-w-0 items-center gap-2.5">
            <Home href={homeHref} className="-mx-1 inline-flex min-h-11 items-center px-1 no-underline" aria-label={t("workingName")}>
              <Wordmark size={26} />
            </Home>
            {/* The honesty label: this is the prototype, said once per screen, small and muted. */}
            <span data-prototype-badge="" className="rounded-full bg-accent-wash px-2.5 py-0.5 text-xs font-semibold text-accent">
              {t("prototypeBadge")}
            </span>
          </span>
          {children}
        </div>
      </header>
    </>
  );
}
