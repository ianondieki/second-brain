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
  /**
   * The page's content runs on to the window's right edge (SignedInShell `bleed`, P27): the bar's frame does too, the
   * wordmark staying level with the rail (the same left padding as the shell's), so the bar is never narrower than the
   * content under it. Below 1152 px nothing changes.
   */
  bleed?: boolean;
}

/**
 * A bleeding page's frame from 1024 px (SignedInShell and the top bar share it): the 72 rem frame's own left edge
 * (half of what is left beside 72 rem, plus its 24 px; `100%` is the body's width, scrollbar excluded), and a 24 px
 * margin on the right, at the window's edge.
 */
export const BLEED_FRAME = "lg:pr-6 lg:pl-[max(1.5rem,calc((100%_-_72rem)/2_+_1.5rem))]";

/**
 * Skip link plus the top bar: a quiet white band with a hairline under it, the wordmark (a link home) on the left and
 * at most one control on the right. No badge and no lattice (D-65: the honesty label lives with the demo data, the
 * lattice frames the hero, the certificate and the footer). Sticky only on signed-in screens from 1024 px, with the
 * page's scroll padding clearing it, so it never covers a focused control. Without
 * next/link in its module (see components/anchor.ts); pages use TopBar.
 */
export async function TopBarBase({
  homeHref = "/",
  Anchor: Home,
  children,
  sticky = false,
  bleed = false,
}: TopBarBaseProps) {
  const t = await getTranslations("shell");
  return (
    <>
      <a
        href="#main"
        className={
          "sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-4 focus:z-30 focus:rounded-control focus:shadow-overlay " +
          "focus:bg-field focus:px-4 focus:py-2.5 focus:min-h-11 focus:font-semibold focus:text-accent"
        }
      >
        {t("skipToContent")}
      </a>
      <header
        data-top-bar=""
        data-sticky={sticky ? "" : undefined}
        className={
          sticky ? "border-b border-line bg-field lg:sticky lg:top-0 lg:z-20" : "border-b border-line bg-field"
        }
      >
        <div
          className={
            bleed
              ? `flex min-h-16 w-full items-center justify-between gap-4 px-4 sm:px-6 ${BLEED_FRAME}`
              : "mx-auto flex min-h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6"
          }
        >
          <Home
            href={homeHref}
            className="-mx-1 inline-flex min-h-11 items-center px-1 no-underline"
            aria-label={t("workingName")}
          >
            <Wordmark size={30} />
          </Home>
          {children}
        </div>
      </header>
    </>
  );
}
