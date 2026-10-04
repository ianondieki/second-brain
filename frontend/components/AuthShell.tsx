import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { Seal } from "./brand/Seal";
import { TopBar } from "./TopBar";
import { Card } from "./ui/Card";
import { IdeasIcon } from "./ui/icons";
import { LockIcon } from "./ui/status-icons";
import { EngagementsIcon } from "./tracker/icons";

export interface AuthShellProps {
  children: ReactNode;
  /** One control on the right of the top bar (for example "Sign out" on the second-factor page). */
  topBarAction?: ReactNode;
}

const STEPS = [
  { key: "publish", Icon: IdeasIcon },
  { key: "review", Icon: LockIcon },
  { key: "track", Icon: EngagementsIcon },
] as const;

/**
 * Signed-out screens (D-55): the top bar, then from 1024 px two halves: the form on the canvas, and a night panel with
 * the kanga lattice, the seal and "How it works" in three steps (complementary: after the form in reading order, drawn
 * on the left). Under 1024 px the form alone. Nothing here is a second primary action.
 */
export async function AuthShell({ children, topBarAction }: AuthShellProps) {
  const t = await getTranslations("panel");
  return (
    <>
      <TopBar>{topBarAction}</TopBar>
      <div className="flex w-full flex-1 flex-col lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <main id="main" tabIndex={-1} className="flex w-full justify-center px-4 pt-6 pb-16 focus:outline-none sm:px-6 sm:pt-10 lg:items-start lg:px-10 lg:pt-20">
          <Card as="div" className="w-full max-w-[30rem] p-5 sm:p-8">
            {children}
          </Card>
        </main>
        <aside
          aria-labelledby="how-it-works"
          className="relative hidden overflow-hidden bg-night text-on-night lg:order-first lg:flex lg:flex-col lg:justify-between lg:pt-20 lg:pr-14 lg:pb-14 lg:pl-[max(3.5rem,calc((100vw-72rem)/2+1.5rem))]"
        >
          <div>
            <h2 id="how-it-works" className="max-w-[16ch] text-3xl text-on-night">
              {t("title")}
            </h2>
            <ol className="mt-10 flex max-w-[42ch] flex-col gap-7">
              {STEPS.map(({ key, Icon }, index) => (
                <li key={key} className="flex gap-4">
                  <span
                    aria-hidden="true"
                    className="flex size-10 shrink-0 items-center justify-center rounded-full bg-flourish font-display text-lg font-[760] text-night tabular-nums"
                  >
                    {index + 1}
                  </span>
                  <p className="pt-1.5 text-night-soft">
                    <Icon aria-hidden="true" className="mr-2 inline size-4 align-[-2px] text-on-night" />
                    {t(key)}
                  </p>
                </li>
              ))}
            </ol>
          </div>
          <div className="mt-14 flex items-end justify-between gap-6">
            <Seal size={112} />
          </div>
          <div aria-hidden="true" className="lattice-band absolute inset-x-0 bottom-0 opacity-90" />
        </aside>
      </div>
    </>
  );
}
