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
 * Signed-out screens (D-52): the top bar, the form in one raised card (30 rem from 1024 px), and beside it on
 * desktop the seal with "How it works" in three steps. Nothing here is a second primary action.
 */
export async function AuthShell({ children, topBarAction }: AuthShellProps) {
  const t = await getTranslations("panel");
  return (
    <>
      <TopBar>{topBarAction}</TopBar>
      <div
        className={
          "mx-auto grid w-full max-w-6xl flex-1 grid-cols-1 content-start gap-12 px-4 pt-6 pb-16 sm:px-6 sm:pt-10 " +
          "lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] lg:gap-20 lg:pt-16"
        }
      >
        <main id="main" tabIndex={-1} className="w-full focus:outline-none">
          <Card as="div" className="p-5 sm:p-8">
            {children}
          </Card>
        </main>
        <aside aria-labelledby="how-it-works" className="hidden self-start pt-2 lg:block">
          <Seal size={96} />
          <h2 id="how-it-works" className="mt-6 text-lg text-ink">
            {t("title")}
          </h2>
          <ol className="mt-4 flex max-w-[40ch] flex-col gap-5">
            {STEPS.map(({ key, Icon }, index) => (
              <li key={key} className="flex gap-4">
                <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-wash text-accent">
                  <Icon className="size-4" />
                </span>
                <p className="text-ink-soft">
                  <span className="mr-2 font-display text-lg font-medium text-accent tabular-nums">{index + 1}.</span>
                  {t(key)}
                </p>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </>
  );
}
