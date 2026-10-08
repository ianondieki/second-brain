import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { AUTH_PHOTOS } from "@/lib/photos/photos";

import { Seal } from "./brand/Seal";
import { TopBar } from "./TopBar";
import { Card } from "./ui/Card";

export interface AuthShellProps {
  children: ReactNode;
  /** One control on the right of the top bar (for example "Sign out" on the second-factor page). */
  topBarAction?: ReactNode;
  /** The photograph on the night side from 1024 px: Nairobi's jacaranda for signing in, the city at golden hour for
   *  creating an account. */
  photo?: keyof typeof AUTH_PHOTOS;
}

const STEPS = ["publish", "review", "track"] as const;
/** From 1024 px only: below it the night side is not drawn and nothing is fetched. */
const WIDE = "(min-width: 64rem)";
/** A transparent pixel: what a phone's <img> loads (nothing), since only the wide <source>s name a photograph. */
const NOTHING = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

/**
 * Signed-out screens (D-55, D-67): the top bar with the wordmark, then from 1024 px two halves: the form on the paper,
 * and the night side, a licensed photograph of Nairobi under a night gradient with "How it works" in three steps and
 * the seal, credited in its corner (and on /credits). Under 1024 px the form alone, in its card, and no photograph is
 * fetched (its <source>s only match from 1024 px), so a phone on Slow 4G gets the form first. Server-rendered: no
 * script of its own. Nothing here is a second primary action.
 */
export async function AuthShell({ children, topBarAction, photo = "signIn" }: AuthShellProps) {
  const [t, tp] = await Promise.all([getTranslations("panel"), getTranslations("portal")]);
  const picture = AUTH_PHOTOS[photo];
  const base = `${picture.dir}/${picture.slug}`;
  return (
    <>
      <TopBar>{topBarAction}</TopBar>
      <div className="flex w-full flex-1 flex-col lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <main id="main" tabIndex={-1} className="flex w-full justify-center px-4 pt-6 pb-16 focus:outline-none sm:px-6 sm:pt-10 lg:items-start lg:px-10 lg:pt-20">
          {/* A card on a phone; on the paper itself beside the night side. */}
          <Card as="div" className="w-full max-w-[30rem] p-5 sm:p-8 lg:border-transparent lg:bg-transparent lg:px-2 lg:shadow-none">
            {children}
          </Card>
        </main>
        <aside
          aria-labelledby="how-it-works"
          className="auth-night relative hidden overflow-hidden bg-night text-on-night lg:order-first lg:block lg:pt-20 lg:pr-14 lg:pb-24 lg:pl-[max(3.5rem,calc((100vw-72rem)/2+1.5rem))]"
          data-auth-photo={picture.slug}
        >
          <div className="auth-photo" aria-hidden="true">
            <picture>
              <source media={WIDE} type="image/avif" srcSet={`${base}-800.avif 800w, ${base}-1600.avif 1600w`} sizes="55vw" />
              <source media={WIDE} type="image/webp" srcSet={`${base}-800.webp 800w, ${base}-1600.webp 1600w`} sizes="55vw" />
              <img src={NOTHING} alt="" width={picture.width} height={picture.height} decoding="async" fetchPriority="high" />
            </picture>
          </div>
          {/* Sticky, so a long form (sign-up) scrolls past the panel's content instead of leaving it behind. */}
          <div className="relative lg:sticky lg:top-24">
            <h2 id="how-it-works" className="max-w-[16ch] text-3xl text-on-night">
              {t("title")}
            </h2>
            <ol className="mt-10 flex max-w-[42ch] flex-col gap-7">
              {STEPS.map((key, index) => (
                <li key={key} className="flex gap-4">
                  <span
                    aria-hidden="true"
                    className="flex size-10 shrink-0 items-center justify-center rounded-full bg-flourish font-figure text-lg font-[760] text-night tabular-nums"
                  >
                    {index + 1}
                  </span>
                  <p className="pt-1.5 text-on-night">{t(key)}</p>
                </li>
              ))}
            </ol>
            <Seal size={112} className="mt-14 block" />
          </div>
          <p className="auth-credit" data-photo-credit="">
            <span>{picture.credit}</span>
            <Link href="/credits" className="underline decoration-1 underline-offset-2 hover:decoration-2">
              {tp("auth.credits")}
            </Link>
          </p>
          <div aria-hidden="true" className="lattice-band absolute inset-x-0 bottom-0 opacity-90" />
        </aside>
      </div>
    </>
  );
}
